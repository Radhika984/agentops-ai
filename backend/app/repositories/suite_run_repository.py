from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.agent import Agent
from app.models.project import Project
from app.models.suite_run import SuiteRun
from app.models.test_suite import TestSuite


class SuiteRunRepository:
    """Database access for suite runs. No ownership rules, no scheduling
    /execution logic, no HTTP concerns — matches
    app/repositories/agent_version_repository.py's own convention.
    `list_for_owner()`/`count_for_owner()` are the one exception (same
    "the join IS the ownership rule" reasoning as
    app/repositories/approval_repository.py's own list_for_owner_suite_run(),
    over the identical SuiteRun -> TestSuite -> Agent -> Project chain)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self, *, suite_id: uuid.UUID, agent_version_id: uuid.UUID, max_concurrency: int
    ) -> SuiteRun:
        suite_run = SuiteRun(
            suite_id=suite_id,
            agent_version_id=agent_version_id,
            max_concurrency=max_concurrency,
            status="pending",
        )
        self._session.add(suite_run)
        await self._session.flush()
        await self._session.refresh(suite_run)
        return suite_run

    async def get_by_id(self, suite_run_id: uuid.UUID) -> SuiteRun | None:
        result = await self._session.execute(
            select(SuiteRun).where(SuiteRun.id == suite_run_id)
        )
        return result.scalar_one_or_none()

    async def update(self, suite_run: SuiteRun, **fields: Any) -> SuiteRun:
        for key, value in fields.items():
            setattr(suite_run, key, value)
        await self._session.flush()
        await self._session.refresh(suite_run)
        return suite_run

    async def mark_running(self, suite_run: SuiteRun, *, started_at: datetime) -> SuiteRun:
        return await self.update(suite_run, status="running", started_at=started_at)

    async def get_latest_by_suite_and_version(
        self, *, suite_id: uuid.UUID, agent_version_id: uuid.UUID
    ) -> SuiteRun | None:
        """Phase 17: the baseline SuiteRun for a regression comparison —
        the most recently created SuiteRun of `suite_id` that ran against
        `agent_version_id`. Ordered by created_at desc so a re-run
        baseline always compares against its latest execution, never an
        arbitrary or oldest one."""
        result = await self._session.execute(
            select(SuiteRun)
            .where(SuiteRun.suite_id == suite_id, SuiteRun.agent_version_id == agent_version_id)
            .order_by(SuiteRun.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def mark_terminal(
        self,
        suite_run: SuiteRun,
        *,
        status: str,
        completed_at: datetime,
        pass_count: int,
        fail_count: int,
        inconclusive_count: int,
        skipped_count: int,
        llm_judge_invocation_count: int,
    ) -> SuiteRun:
        return await self.update(
            suite_run,
            status=status,
            completed_at=completed_at,
            pass_count=pass_count,
            fail_count=fail_count,
            inconclusive_count=inconclusive_count,
            skipped_count=skipped_count,
            llm_judge_invocation_count=llm_judge_invocation_count,
        )

    def _owner_scoped_query(self, owner_id: uuid.UUID) -> Select[tuple[SuiteRun]]:
        return (
            select(SuiteRun)
            .join(TestSuite, TestSuite.id == SuiteRun.suite_id)
            .join(Agent, Agent.id == TestSuite.agent_id)
            .join(Project, Project.id == Agent.project_id)
            .where(Project.owner_id == owner_id)
        )

    async def list_for_owner(
        self, owner_id: uuid.UUID, *, limit: int = 20, offset: int = 0
    ) -> list[SuiteRun]:
        """The account-wide "Runs" nav page AND the dashboard's "Recent
        Suite Runs" widget share this exact method (just a different
        `limit`) — one real capability, two UI surfaces, not two
        parallel implementations. Eager-loads exactly the relationships
        the SuiteRunSummary schema needs (suite name, agent/project name
        via suite.agent.project, version label) so rendering a page of
        rows never issues N+1 lazy-load queries."""
        query = (
            self._owner_scoped_query(owner_id)
            .options(
                selectinload(SuiteRun.suite).selectinload(TestSuite.agent).selectinload(Agent.project),
                selectinload(SuiteRun.agent_version),
            )
            .order_by(SuiteRun.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self._session.execute(query)
        return list(result.scalars().unique().all())

    async def count_for_owner(self, owner_id: uuid.UUID) -> int:
        query = select(func.count()).select_from(self._owner_scoped_query(owner_id).subquery())
        result = await self._session.execute(query)
        return int(result.scalar_one())

    async def performance_by_day_for_owner(
        self, owner_id: uuid.UUID, *, since: datetime
    ) -> list[tuple[Any, int, int, int]]:
        """Performance Overview's real data source — every SuiteRun that
        *completed* (status='completed', so an in-progress or crashed run
        never contributes a partial day) on or after `since`, grouped by
        the calendar date it completed on, summing its own already
        -persisted pass/fail/inconclusive counters. A day with zero
        completed runs simply produces no row — app/services/
        dashboard_service.py never pads the result with an invented 0%
        entry for a day nothing happened."""
        day = func.date(SuiteRun.completed_at)
        query = (
            select(
                day.label("day"),
                func.sum(SuiteRun.pass_count),
                func.sum(SuiteRun.fail_count),
                func.sum(SuiteRun.inconclusive_count),
            )
            .select_from(SuiteRun)
            .join(TestSuite, TestSuite.id == SuiteRun.suite_id)
            .join(Agent, Agent.id == TestSuite.agent_id)
            .join(Project, Project.id == Agent.project_id)
            .where(
                Project.owner_id == owner_id,
                SuiteRun.status == "completed",
                SuiteRun.completed_at >= since,
            )
            .group_by(day)
            .order_by(day)
        )
        result = await self._session.execute(query)
        return [
            (row[0], int(row[1] or 0), int(row[2] or 0), int(row[3] or 0)) for row in result.all()
        ]

