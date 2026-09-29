"""Global search — real, owner-scoped substring matches against actual
persisted entity names/labels, each result pointing at the real,
already-existing frontend route for that entity (never a placeholder
route). Every query is scoped to the current user's own data via the
same ownership-chain joins every other cross-entity query in this app
uses (see app/repositories/approval_repository.py's own precedent) —
never a global, unscoped search.

SuiteRun is deliberately NOT one of the searched entity kinds: it has no
user-assigned name/label field (only a UUID and a status/verdict), so an
ILIKE match against it would either match nothing meaningful or require
matching against its id as raw text — neither is a genuine text search,
so it is left out rather than faked. The reference's other five kinds
(Project, Agent, TestSuite, TestCase, AgentVersion) are all real fields.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent
from app.models.agent_version import AgentVersion
from app.models.project import Project
from app.models.test_case import TestCase
from app.models.test_suite import TestSuite
from app.schemas.search import SearchResponse, SearchResult

_MAX_RESULTS_PER_KIND = 5


class SearchService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def search(self, *, owner_id: uuid.UUID, query: str) -> SearchResponse:
        query = query.strip()
        if not query:
            return SearchResponse(query=query, results=[])
        pattern = f"%{query}%"

        results: list[SearchResult] = []
        results.extend(await self._search_projects(owner_id, pattern))
        results.extend(await self._search_agents(owner_id, pattern))
        results.extend(await self._search_test_suites(owner_id, pattern))
        results.extend(await self._search_test_cases(owner_id, pattern))
        results.extend(await self._search_agent_versions(owner_id, pattern))
        return SearchResponse(query=query, results=results)

    async def _search_projects(self, owner_id: uuid.UUID, pattern: str) -> list[SearchResult]:
        rows = (
            await self._session.execute(
                select(Project)
                .where(Project.owner_id == owner_id, Project.name.ilike(pattern))
                .limit(_MAX_RESULTS_PER_KIND)
            )
        ).scalars().all()
        return [
            SearchResult(
                kind="project",
                id=p.id,
                title=p.name,
                subtitle="Project",
                href=f"/projects/{p.id}/chat",
            )
            for p in rows
        ]

    async def _search_agents(self, owner_id: uuid.UUID, pattern: str) -> list[SearchResult]:
        rows = (
            await self._session.execute(
                select(Agent)
                .join(Project, Project.id == Agent.project_id)
                .where(Project.owner_id == owner_id, Agent.name.ilike(pattern))
                .limit(_MAX_RESULTS_PER_KIND)
            )
        ).scalars().all()
        return [
            SearchResult(
                kind="agent", id=a.id, title=a.name, subtitle="Agent", href=f"/agents/{a.id}"
            )
            for a in rows
        ]

    async def _search_test_suites(self, owner_id: uuid.UUID, pattern: str) -> list[SearchResult]:
        rows = (
            await self._session.execute(
                select(TestSuite)
                .join(Agent, Agent.id == TestSuite.agent_id)
                .join(Project, Project.id == Agent.project_id)
                .where(Project.owner_id == owner_id, TestSuite.name.ilike(pattern))
                .limit(_MAX_RESULTS_PER_KIND)
            )
        ).scalars().all()
        return [
            SearchResult(
                kind="test_suite",
                id=s.id,
                title=s.name,
                subtitle="Test Suite",
                href=f"/agents/{s.agent_id}/test-suites/{s.id}",
            )
            for s in rows
        ]

    async def _search_test_cases(self, owner_id: uuid.UUID, pattern: str) -> list[SearchResult]:
        rows = (
            await self._session.execute(
                select(TestCase, TestSuite.agent_id)
                .join(TestSuite, TestSuite.id == TestCase.suite_id)
                .join(Agent, Agent.id == TestSuite.agent_id)
                .join(Project, Project.id == Agent.project_id)
                .where(Project.owner_id == owner_id, TestCase.name.ilike(pattern))
                .limit(_MAX_RESULTS_PER_KIND)
            )
        ).all()
        return [
            SearchResult(
                kind="test_case",
                id=case.id,
                title=case.name,
                subtitle="Test Case",
                href=f"/agents/{agent_id}/test-suites/{case.suite_id}/test-cases/{case.id}/edit",
            )
            for case, agent_id in rows
        ]

    async def _search_agent_versions(self, owner_id: uuid.UUID, pattern: str) -> list[SearchResult]:
        rows = (
            await self._session.execute(
                select(AgentVersion)
                .join(Agent, Agent.id == AgentVersion.agent_id)
                .join(Project, Project.id == Agent.project_id)
                .where(Project.owner_id == owner_id, AgentVersion.label.ilike(pattern))
                .limit(_MAX_RESULTS_PER_KIND)
            )
        ).scalars().all()
        return [
            SearchResult(
                kind="agent_version",
                id=v.id,
                title=v.label,
                subtitle="Agent Version",
                href=f"/agents/{v.agent_id}",
            )
            for v in rows
        ]
