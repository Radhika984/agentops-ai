from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent
from app.models.project import Project
from app.models.test_suite import TestSuite


class TestSuiteRepository:
    """Database access for test suites. No ownership rules, no HTTP
    concerns — matches app/repositories/agent_repository.py's own
    convention. `list_for_owner()` is the one exception (same reasoning
    as app/repositories/approval_repository.py's own list_for_owner()):
    "which suites can this user see" is inherent to the query, not a
    separate rule layered on top."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, *, agent_id: uuid.UUID, name: str) -> TestSuite:
        suite = TestSuite(agent_id=agent_id, name=name)
        self._session.add(suite)
        await self._session.flush()
        await self._session.refresh(suite)
        return suite

    async def list_by_agent(self, agent_id: uuid.UUID) -> list[TestSuite]:
        result = await self._session.execute(
            select(TestSuite).where(TestSuite.agent_id == agent_id).order_by(TestSuite.created_at)
        )
        return list(result.scalars().all())

    async def get_by_id(self, suite_id: uuid.UUID) -> TestSuite | None:
        result = await self._session.execute(select(TestSuite).where(TestSuite.id == suite_id))
        return result.scalar_one_or_none()

    async def list_for_owner(self, owner_id: uuid.UUID, *, limit: int = 200) -> list[TestSuite]:
        """The account-wide "Test Suites" nav page's data source — every
        TestSuite belonging to any Agent in any Project this user owns,
        via the TestSuite -> Agent -> Project chain (the same chain
        app/repositories/approval_repository.py's list_for_owner_suite_run()
        already walks one hop further)."""
        result = await self._session.execute(
            select(TestSuite)
            .join(Agent, Agent.id == TestSuite.agent_id)
            .join(Project, Project.id == Agent.project_id)
            .where(Project.owner_id == owner_id)
            .order_by(TestSuite.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())
