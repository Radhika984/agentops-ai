from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.test_case import TestCase


class TestCaseRepository:
    """Database access for test cases. No ownership rules, no ground
    -truth validation, no HTTP concerns — matches
    app/repositories/agent_version_repository.py's own convention. All
    domain rules (ground-truth requirement, PATCH revalidation) live in
    app/services/test_suite_service.py, not here."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, *, suite_id: uuid.UUID, fields: dict[str, Any]) -> TestCase:
        case = TestCase(suite_id=suite_id, **fields)
        self._session.add(case)
        await self._session.flush()
        await self._session.refresh(case)
        return case

    async def list_by_suite(self, suite_id: uuid.UUID) -> list[TestCase]:
        result = await self._session.execute(
            select(TestCase).where(TestCase.suite_id == suite_id).order_by(TestCase.created_at)
        )
        return list(result.scalars().all())

    async def list_active_by_suite(self, suite_id: uuid.UUID) -> list[TestCase]:
        """Phase 20: the Suite Runner's own case source — excludes
        `status="candidate"` rows (a proposed regression test from a real
        production failure, not yet accepted by a human — see
        app/models/test_case.py's own docstring). list_by_suite() above
        is unchanged and still returns every case, candidates included,
        for listing/visibility endpoints."""
        result = await self._session.execute(
            select(TestCase)
            .where(TestCase.suite_id == suite_id, TestCase.status == "active")
            .order_by(TestCase.created_at)
        )
        return list(result.scalars().all())

    async def get_by_id(self, case_id: uuid.UUID) -> TestCase | None:
        result = await self._session.execute(select(TestCase).where(TestCase.id == case_id))
        return result.scalar_one_or_none()

    async def update(self, case: TestCase, **fields: Any) -> TestCase:
        for key, value in fields.items():
            setattr(case, key, value)
        await self._session.flush()
        await self._session.refresh(case)
        return case

    async def delete(self, case: TestCase) -> None:
        await self._session.delete(case)
        await self._session.flush()
