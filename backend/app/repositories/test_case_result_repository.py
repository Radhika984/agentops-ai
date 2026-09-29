from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.agent import Agent
from app.models.project import Project
from app.models.suite_run import SuiteRun
from app.models.test_case_result import TestCaseResult
from app.models.test_suite import TestSuite


class TestCaseResultRepository:
    """Database access for test case results. No ownership rules, no
    evaluation logic (that's app/evaluation/, Phase 13, untouched), no
    HTTP concerns — matches app/repositories/agent_version_repository.py's
    own convention. `list_for_owner()`/`verdict_distribution_for_owner()`
    are the one exception (same "the join IS the ownership rule"
    reasoning as app/repositories/approval_repository.py's own
    list_for_owner_suite_run(), one hop further: TestCaseResult ->
    SuiteRun -> TestSuite -> Agent -> Project)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def exists(self, *, suite_run_id: uuid.UUID, test_case_id: uuid.UUID) -> bool:
        """The idempotency check app/services/suite_runner.py runs before
        persisting a result — see models/test_case_result.py's own
        docstring on why (suite_runner.py) + the DB-level unique
        constraint together guard against a retried/duplicate execution
        producing a second row for the same case within the same run."""
        result = await self._session.execute(
            select(TestCaseResult.id).where(
                TestCaseResult.suite_run_id == suite_run_id,
                TestCaseResult.test_case_id == test_case_id,
            )
        )
        return result.scalar_one_or_none() is not None

    async def existing_test_case_ids(self, suite_run_id: uuid.UUID) -> set[uuid.UUID]:
        """Phase 16: one bulk query used to filter out cases that already
        have a persisted result *before* any trials are invoked — so a
        retried suite run never re-invokes a real agent for a case it
        already has a result for, rather than invoking it again and only
        discarding the result at persistence time (the old, only,
        per-case `exists()` check above still exists as a defensive
        backstop, not the primary guard, now that invocation and
        persistence happen in two separate passes — see
        app/services/suite_runner.py)."""
        result = await self._session.execute(
            select(TestCaseResult.test_case_id).where(TestCaseResult.suite_run_id == suite_run_id)
        )
        return set(result.scalars().all())

    async def create(
        self, *, suite_run_id: uuid.UUID, test_case_id: uuid.UUID, **fields: Any
    ) -> TestCaseResult:
        result = TestCaseResult(suite_run_id=suite_run_id, test_case_id=test_case_id, **fields)
        self._session.add(result)
        await self._session.flush()
        await self._session.refresh(result)
        return result

    async def list_by_suite_run(self, suite_run_id: uuid.UUID) -> list[TestCaseResult]:
        result = await self._session.execute(
            select(TestCaseResult)
            .where(TestCaseResult.suite_run_id == suite_run_id)
            .order_by(TestCaseResult.created_at)
        )
        return list(result.scalars().all())

    async def get_by_id(self, result_id: uuid.UUID) -> TestCaseResult | None:
        result = await self._session.execute(
            select(TestCaseResult).where(TestCaseResult.id == result_id)
        )
        return result.scalar_one_or_none()

    async def set_suggested_fix(self, result: TestCaseResult, suggested_fix: str) -> TestCaseResult:
        """Phase 19 — AutoFix Option 4: a NOT-APPLIED natural-language
        suggestion recorded on the already-persisted result. Never
        changes `verdict`/`checks`/anything else on the row — this is
        the one AutoFix path that requires no approval, because it
        changes nothing about the evaluated evidence itself."""
        result.suggested_fix = suggested_fix
        await self._session.flush()
        return result

    async def aggregate_counts(self, suite_run_id: uuid.UUID) -> dict[str, int]:
        """Recomputed from the persisted rows themselves (not accumulated
        in memory during execution) — correct even if the runner is
        retried mid-run and some results already existed from a prior
        attempt."""
        query = (
            select(TestCaseResult.verdict, func.count())
            .where(TestCaseResult.suite_run_id == suite_run_id)
            .group_by(TestCaseResult.verdict)
        )
        rows = (await self._session.execute(query)).all()
        counts = {"PASS": 0, "FAIL": 0, "INCONCLUSIVE": 0}
        for verdict, count in rows:
            counts[verdict] = count
        return counts

    def _owner_scoped_query(self, owner_id: uuid.UUID) -> Select[tuple[TestCaseResult]]:
        return (
            select(TestCaseResult)
            .join(SuiteRun, SuiteRun.id == TestCaseResult.suite_run_id)
            .join(TestSuite, TestSuite.id == SuiteRun.suite_id)
            .join(Agent, Agent.id == TestSuite.agent_id)
            .join(Project, Project.id == Agent.project_id)
            .where(Project.owner_id == owner_id)
        )

    async def list_for_owner(
        self,
        owner_id: uuid.UUID,
        *,
        limit: int = 20,
        offset: int = 0,
        verdicts: list[str] | None = None,
    ) -> list[TestCaseResult]:
        """The account-wide "Evaluation" nav page's data source (all
        verdicts) and, with `verdicts=["FAIL", "INCONCLUSIVE"]`, the
        "RCA" nav page's data source (the results a user would actually
        want to run RCA on) — one real capability serving both, not two
        parallel queries."""
        query = (
            self._owner_scoped_query(owner_id)
            .options(
                selectinload(TestCaseResult.test_case),
                selectinload(TestCaseResult.suite_run)
                .selectinload(SuiteRun.suite)
                .selectinload(TestSuite.agent),
            )
            .order_by(TestCaseResult.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        if verdicts is not None:
            query = query.where(TestCaseResult.verdict.in_(verdicts))
        result = await self._session.execute(query)
        return list(result.scalars().unique().all())

    async def count_for_owner(
        self, owner_id: uuid.UUID, *, verdicts: list[str] | None = None
    ) -> int:
        query = self._owner_scoped_query(owner_id)
        if verdicts is not None:
            query = query.where(TestCaseResult.verdict.in_(verdicts))
        result = await self._session.execute(select(func.count()).select_from(query.subquery()))
        return int(result.scalar_one())

    async def verdict_distribution_for_owner(self, owner_id: uuid.UUID) -> dict[str, int]:
        """Verdict Distribution — a real SQL GROUP BY, not a client-side
        tally over a fetched page, so it's correct regardless of how many
        results exist (never paginated/limited)."""
        query = (
            select(TestCaseResult.verdict, func.count())
            .select_from(TestCaseResult)
            .join(SuiteRun, SuiteRun.id == TestCaseResult.suite_run_id)
            .join(TestSuite, TestSuite.id == SuiteRun.suite_id)
            .join(Agent, Agent.id == TestSuite.agent_id)
            .join(Project, Project.id == Agent.project_id)
            .where(Project.owner_id == owner_id)
            .group_by(TestCaseResult.verdict)
        )
        rows = (await self._session.execute(query)).all()
        counts = {"PASS": 0, "FAIL": 0, "INCONCLUSIVE": 0}
        for verdict, count in rows:
            counts[verdict] = count
        return counts
