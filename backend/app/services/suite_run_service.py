"""Phase 14 — SuiteRun creation and read/poll access.

Owns only ownership-chain verification and the pending SuiteRun row's
creation; actual execution (adapter invocation + Phase 13 evaluation +
TestCaseResult persistence) is app/services/suite_runner.py's job,
scheduled as a background task from the API layer — this service never
executes a suite itself, matching the locked separation:

    API route -> SuiteRunService.create_suite_run() (persist pending row)
              -> BackgroundTasks.add_task(suite_runner.execute_suite_run)
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.suite_run import SuiteRun
from app.models.test_case_result import TestCaseResult
from app.repositories.suite_run_repository import SuiteRunRepository
from app.repositories.test_case_result_repository import TestCaseResultRepository
from app.schemas.dashboard import TestCaseResultSummary
from app.services.agent_service import AgentService
from app.services.test_suite_service import TestSuiteService


def _to_result_summary(result: TestCaseResult) -> TestCaseResultSummary:
    suite = result.suite_run.suite
    return TestCaseResultSummary(
        id=result.id,
        suite_run_id=result.suite_run_id,
        test_case_id=result.test_case_id,
        test_case_name=result.test_case.name,
        suite_id=suite.id,
        suite_name=suite.name,
        agent_id=suite.agent_id,
        agent_name=suite.agent.name,
        verdict=result.verdict,
        latency_ms=result.latency_ms,
        error=result.error,
        created_at=result.created_at,
    )


class SuiteRunService:
    """Ownership and business rules for SuiteRun/TestCaseResult reads.
    Raises framework-independent domain exceptions only — matching
    AgentService/TestSuiteService's own convention exactly.

    Ownership is always resolved the same way: SuiteRun belongs to a
    TestSuite that belongs to an Agent that belongs to a Project
    (verified via real TestSuiteService/AgentService instances, never a
    reimplementation of their ownership chains).
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._agents = AgentService(session)
        self._suites = TestSuiteService(session)
        self._suite_runs = SuiteRunRepository(session)
        self._results = TestCaseResultRepository(session)

    async def create_suite_run(
        self,
        *,
        suite_id: uuid.UUID,
        owner_id: uuid.UUID,
        agent_version_id: uuid.UUID,
        max_concurrency: int,
    ) -> SuiteRun:
        # Raises NotFoundError / PermissionDeniedError if the suite
        # doesn't exist or its agent's project isn't owned by owner_id.
        suite = await self._suites.get_suite(suite_id=suite_id, owner_id=owner_id)

        # Raises NotFoundError if the version doesn't exist or belongs to
        # a *different* agent than this suite — this is exactly what
        # enforces "the supplied AgentVersion belongs to the same Agent
        # as the Suite" (requirement §3.4), by scoping the ownership
        # lookup to `suite.agent_id` rather than any agent the user owns.
        await self._agents.get_version(
            agent_id=suite.agent_id, version_id=agent_version_id, owner_id=owner_id
        )

        suite_run = await self._suite_runs.create(
            suite_id=suite.id,
            agent_version_id=agent_version_id,
            max_concurrency=max_concurrency,
        )
        await self._session.commit()
        return suite_run

    async def get_suite_run(self, *, suite_run_id: uuid.UUID, owner_id: uuid.UUID) -> SuiteRun:
        suite_run = await self._suite_runs.get_by_id(suite_run_id)
        if suite_run is None:
            raise NotFoundError(f"Suite run not found: {suite_run_id}")
        await self._suites.get_suite(suite_id=suite_run.suite_id, owner_id=owner_id)
        return suite_run

    async def list_results(
        self, *, suite_run_id: uuid.UUID, owner_id: uuid.UUID
    ) -> list[TestCaseResult]:
        await self.get_suite_run(suite_run_id=suite_run_id, owner_id=owner_id)
        return await self._results.list_by_suite_run(suite_run_id)

    async def get_result(
        self, *, suite_run_id: uuid.UUID, result_id: uuid.UUID, owner_id: uuid.UUID
    ) -> TestCaseResult:
        await self.get_suite_run(suite_run_id=suite_run_id, owner_id=owner_id)
        result = await self._results.get_by_id(result_id)
        if result is None or result.suite_run_id != suite_run_id:
            raise NotFoundError(f"Test case result not found: {result_id}")
        return result

    async def list_all_results_for_owner(
        self,
        *,
        owner_id: uuid.UUID,
        limit: int = 20,
        offset: int = 0,
        verdicts: list[str] | None = None,
    ) -> tuple[list[TestCaseResultSummary], int]:
        """The account-wide "Evaluation" nav page (all verdicts) and, with
        verdicts=["FAIL", "INCONCLUSIVE"], the "RCA" nav page — every
        TestCaseResult across every SuiteRun this owner can see, via the
        same "join IS the ownership rule" pattern SuiteRunRepository/
        TestSuiteRepository already use for their own account-wide
        listings."""
        results = await self._results.list_for_owner(
            owner_id, limit=limit, offset=offset, verdicts=verdicts
        )
        total = await self._results.count_for_owner(owner_id, verdicts=verdicts)
        return [_to_result_summary(r) for r in results], total
