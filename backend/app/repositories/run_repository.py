from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.state import AgentState
from app.models.run import Run


class RunRepository:
    """Database access for runs. No ownership rules, no HTTP concerns."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, *, project_id: uuid.UUID, goal: str, state: AgentState) -> Run:
        run = Run(project_id=project_id, goal=goal, status=state["status"], state=dict(state))
        self._session.add(run)
        await self._session.flush()
        await self._session.refresh(run)
        return run

    async def get_by_id(self, run_id: uuid.UUID) -> Run | None:
        result = await self._session.execute(select(Run).where(Run.id == run_id))
        return result.scalar_one_or_none()

    async def update_state(
        self, run: Run, *, state: AgentState, extra: dict[str, object] | None = None
    ) -> Run:
        """`extra` merges additional keys into the persisted state blob
        that aren't part of AgentState itself — e.g. Phase 7's `trace`
        (see run_service.py), which is pure observability data the graph
        nodes neither produce nor consume, so it doesn't belong in the
        TypedDict the graph actually operates on.
        """
        run.state = {**dict(state), **(extra or {})}
        run.status = state["status"]
        await self._session.flush()
        await self._session.refresh(run)
        return run

    async def merge_state_extra(self, run: Run, *, key: str, value: object) -> Run:
        """Phase 9: merges a single top-level key into the already
        -persisted state blob without touching anything else in it —
        used for `run.state["release"]` (see app/approvals/service.py).
        Deliberately separate from update_state(): that method persists
        a *new* AgentState (the graph's own output) plus extras in one
        step; this one only ever layers an extra key onto whatever state
        is already there, for a workflow that runs entirely after the
        graph itself has already finished and is not itself an AgentState
        producer.
        """
        run.state = {**run.state, key: value}
        await self._session.flush()
        await self._session.refresh(run)
        return run
