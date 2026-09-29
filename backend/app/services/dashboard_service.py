"""Home dashboard — every number here is a live, owner-scoped aggregate
computed at read time from already-persisted data (Project/Agent/
SuiteRun/TestCaseResult/ActivityEvent). Nothing is cached, precomputed,
or invented; a metric this module cannot honestly compute from real data
(there is no such metric currently exposed) simply would not be added
here rather than approximated.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.suite_run import SuiteRun
from app.repositories.activity_event_repository import ActivityEventRepository
from app.repositories.agent_repository import AgentRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.suite_run_repository import SuiteRunRepository
from app.repositories.test_case_result_repository import TestCaseResultRepository
from app.schemas.dashboard import (
    DashboardStats,
    PerformanceOverview,
    PerformancePoint,
    SuiteRunListResponse,
    SuiteRunSummary,
    VerdictDistribution,
)

DEFAULT_PERFORMANCE_WINDOW_DAYS = 7


def _run_verdict(run: SuiteRun) -> str | None:
    if run.status not in ("completed", "failed"):
        return None
    total = run.pass_count + run.fail_count + run.inconclusive_count
    if total == 0:
        return None
    if run.fail_count > 0:
        return "FAIL"
    if run.inconclusive_count > 0:
        return "INCONCLUSIVE"
    return "PASS"


def _to_summary(run: SuiteRun) -> SuiteRunSummary:
    suite = run.suite
    agent = suite.agent
    project = agent.project
    version = run.agent_version
    return SuiteRunSummary(
        id=run.id,
        suite_id=suite.id,
        suite_name=suite.name,
        agent_id=agent.id,
        agent_name=agent.name,
        project_id=project.id,
        project_name=project.name,
        agent_version_id=version.id,
        version_label=version.label,
        status=run.status,
        verdict=_run_verdict(run),
        pass_count=run.pass_count,
        fail_count=run.fail_count,
        inconclusive_count=run.inconclusive_count,
        started_at=run.started_at,
        completed_at=run.completed_at,
        created_at=run.created_at,
    )


class DashboardService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._projects = ProjectRepository(session)
        self._agents = AgentRepository(session)
        self._suite_runs = SuiteRunRepository(session)
        self._results = TestCaseResultRepository(session)
        self._activity = ActivityEventRepository(session)

    async def get_stats(self, owner_id: uuid.UUID) -> DashboardStats:
        return DashboardStats(
            total_projects=await self._projects.count_by_owner(owner_id),
            total_agents=await self._agents.count_for_owner(owner_id),
            total_suite_runs=await self._suite_runs.count_for_owner(owner_id),
            release_gate_holds=await self._activity.count_release_gate_holds_for_owner(owner_id),
        )

    async def get_recent_suite_runs(
        self, owner_id: uuid.UUID, *, limit: int = 20, offset: int = 0
    ) -> SuiteRunListResponse:
        runs = await self._suite_runs.list_for_owner(owner_id, limit=limit, offset=offset)
        total = await self._suite_runs.count_for_owner(owner_id)
        return SuiteRunListResponse(items=[_to_summary(r) for r in runs], total=total)

    async def get_verdict_distribution(self, owner_id: uuid.UUID) -> VerdictDistribution:
        counts = await self._results.verdict_distribution_for_owner(owner_id)
        total = counts["PASS"] + counts["FAIL"] + counts["INCONCLUSIVE"]
        return VerdictDistribution(
            pass_count=counts["PASS"],
            fail_count=counts["FAIL"],
            inconclusive_count=counts["INCONCLUSIVE"],
            total=total,
        )

    async def get_performance_overview(
        self, owner_id: uuid.UUID, *, days: int = DEFAULT_PERFORMANCE_WINDOW_DAYS
    ) -> PerformanceOverview:
        since = datetime.now(UTC) - timedelta(days=days)
        rows = await self._suite_runs.performance_by_day_for_owner(owner_id, since=since)
        points: list[PerformancePoint] = []
        for day, pass_count, fail_count, inconclusive_count in rows:
            total = pass_count + fail_count + inconclusive_count
            if total == 0:
                # Should not happen (a grouped row implies >=1 completed
                # run), but never divide by zero regardless.
                continue
            points.append(
                PerformancePoint(
                    date=day,
                    pass_rate=pass_count / total,
                    fail_rate=fail_count / total,
                    inconclusive_rate=inconclusive_count / total,
                    total_results=total,
                )
            )
        return PerformanceOverview(points=points, range_days=days)
