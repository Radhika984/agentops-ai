from __future__ import annotations

import logging
import uuid
from typing import cast

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.graph import agent_graph
from app.agents.state import AgentState, initial_state
from app.ai.client import owner_call_context
from app.core.exceptions import NotFoundError
from app.db.session import AsyncSessionLocal
from app.memory import manager as memory_manager
from app.models.run import Run
from app.observability import tracing
from app.repositories.flag_repository import FlagRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.run_repository import RunRepository
from app.repositories.tool_call_repository import ToolCallRepository
from app.services.project_service import ProjectService

logger = logging.getLogger(__name__)


class RunService:
    """Orchestrates the authenticated /runs flow.

    Verifies project ownership the same way AskService does (delegating to
    ProjectService), then persists a `pending` Run row. The graph itself is
    executed separately by run_graph_and_persist() — see that function's
    docstring for why it needs its own DB session.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._projects = ProjectService(session)
        self._runs = RunRepository(session)

    async def create_run(self, *, project_id: uuid.UUID, owner_id: uuid.UUID, goal: str) -> Run:
        # Raises NotFoundError / PermissionDeniedError if the project does not
        # exist or is not owned by owner_id — checked before creating anything.
        await self._projects.get_project(project_id=project_id, owner_id=owner_id)

        run = await self._runs.create(project_id=project_id, goal=goal, state=initial_state(goal))
        await self._session.commit()
        return run

    async def get_run(
        self, *, project_id: uuid.UUID, run_id: uuid.UUID, owner_id: uuid.UUID
    ) -> Run:
        # Same ownership check as create_run() — a run is only visible
        # through its owner's project.
        await self._projects.get_project(project_id=project_id, owner_id=owner_id)

        run = await self._runs.get_by_id(run_id)
        if run is None or run.project_id != project_id:
            raise NotFoundError(f"Run not found: {run_id}")
        return run


async def run_graph_and_persist(run_id: uuid.UUID) -> None:
    """Executes the agent graph for `run_id` and persists the final state.

    Runs as a FastAPI BackgroundTasks callback, which executes after the
    HTTP response for POST /runs has already been sent — by then the
    request's own DB session (from the `Depends(get_db)` that handled that
    request) has been closed. This function therefore opens its own
    session via AsyncSessionLocal, exactly like the test fixtures do,
    rather than trying to reuse a session that no longer exists.
    """
    async with AsyncSessionLocal() as session:
        repo = RunRepository(session)
        tool_calls_repo = ToolCallRepository(session)
        flags_repo = FlagRepository(session)
        run = await repo.get_by_id(run_id)
        if run is None:
            logger.error("run_graph_and_persist: run %s not found", run_id)
            return

        # Whichever real account owns this run's Project is who every
        # model_calls row the graph triggers (planner/hallucination/
        # safety/rca/auto_fix nodes) gets attributed to for GET
        # /api/v1/cost — see app/ai/client.py's owner_call_context.
        project = await ProjectRepository(session).get_by_id(run.project_id)
        owner_id = project.owner_id if project is not None else None

        # Phase 7: every node's OTel span (see agents/graph.py) is tagged
        # with whatever current_run_id is set to — scoping it here, for
        # the duration of this one run's graph execution, is what lets
        # concurrent runs' spans be told apart later (see
        # observability/tracing.py's docstring).
        run_id_str = str(run_id)
        token = tracing.current_run_id.set(run_id_str)
        try:
            with owner_call_context(owner_id):
                try:
                    # ainvoke()'s declared return type is broader than
                    # AgentState (a LangGraph generics limitation) — every
                    # node in graph.py returns the full AgentState shape by
                    # construction, so the runtime value always conforms.
                    final_state = cast(
                        AgentState, await agent_graph.ainvoke(initial_state(run.goal))
                    )
                except Exception:
                    logger.exception(
                        "run_graph_and_persist: graph execution failed for run %s", run_id
                    )
                    failed_state: AgentState = initial_state(run.goal)
                    failed_state["status"] = "failed"
                    trace = tracing.get_spans_for_run(run_id_str)
                    await repo.update_state(run, state=failed_state, extra={"trace": trace})
                    await session.commit()
                    return
        finally:
            tracing.current_run_id.reset(token)

        trace = tracing.get_spans_for_run(run_id_str)
        tracing.clear_spans_for_run(run_id_str)

        await repo.update_state(run, state=final_state, extra={"trace": trace})
        # Phase 5: nodes accumulate tool calls in state as they happen (no
        # DB access from nodes); persisted to the tool_calls audit table
        # here, once, alongside the final state.
        await tool_calls_repo.bulk_create(run_id=run.id, records=final_state["tool_calls"])
        # Phase 7: same pattern for Safety blocks / Hallucination findings.
        await flags_repo.bulk_create(run_id=run.id, records=final_state["flags"])
        await session.commit()

        # Phase 6: write a summary of this run back to long-term memory for
        # future Planner calls to retrieve — only on success. A failed
        # run's plan isn't a good example to resurface for a similar future
        # goal, so it's deliberately not remembered. Done after the state
        # commit above (and outside that transaction) so a slow/failed
        # embedding call can never cause an otherwise-successful run to be
        # reported as failed — see remember()'s own docstring for the same
        # reasoning at the memory layer.
        if final_state["status"] == "succeeded":
            summary = f"Goal: {run.goal}\nPlan:\n" + "\n".join(
                f"- {task}" for task in final_state["plan"]
            )
            await memory_manager.remember(content=summary, source_type="run", source_id=run.id)
