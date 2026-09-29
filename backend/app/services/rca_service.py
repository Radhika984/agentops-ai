"""Phase 18 — RCA orchestration: ownership + evidence gathering.

Owns only the DB-facing parts (ownership-checked lookups, optionally
pulling in Phase 17's regression comparison for the same case); the
actual two-tier root-cause analysis itself is app/rca/service.py's
`analyze_case()`, which takes already-loaded evidence and never touches
the database — matching how app/evaluation/engine.py's `evaluate()` is
kept separate from app/services/suite_runner.py's DB access.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.client import owner_call_context
from app.core.exceptions import InvalidStateError, NotFoundError
from app.rca.service import analyze_case
from app.repositories.test_case_repository import TestCaseRepository
from app.schemas.rca import RCAResponse
from app.schemas.regression import CaseComparison
from app.services.regression_service import RegressionService
from app.services.suite_run_service import SuiteRunService


class RCAService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._suite_runs = SuiteRunService(session)
        self._cases = TestCaseRepository(session)

    async def analyze(
        self, *, suite_run_id: uuid.UUID, result_id: uuid.UUID, owner_id: uuid.UUID
    ) -> RCAResponse:
        # Ownership chain (SuiteRun -> TestSuite -> Agent -> Project),
        # reused verbatim from Phase 14 — never reimplemented here.
        result = await self._suite_runs.get_result(
            suite_run_id=suite_run_id, result_id=result_id, owner_id=owner_id
        )
        test_case = await self._cases.get_by_id(result.test_case_id)
        if test_case is None:
            raise NotFoundError(f"Test case not found: {result.test_case_id}")

        suite_run = await self._suite_runs.get_suite_run(
            suite_run_id=suite_run_id, owner_id=owner_id
        )
        case_comparison = await self._try_get_case_comparison(
            suite_id=suite_run.suite_id,
            owner_id=owner_id,
            candidate_run_id=suite_run_id,
            test_case_id=test_case.id,
        )

        # Attributes the on-demand LLM-hypothesis tier's model call (if
        # reached — the deterministic tier never calls one) to the
        # already-verified owner_id above, for GET /api/v1/cost.
        with owner_call_context(owner_id):
            return await analyze_case(
                test_case=test_case, result=result, case_comparison=case_comparison
            )

    async def _try_get_case_comparison(
        self,
        *,
        suite_id: uuid.UUID,
        owner_id: uuid.UUID,
        candidate_run_id: uuid.UUID,
        test_case_id: uuid.UUID,
    ) -> CaseComparison | None:
        """Best-effort reuse of Phase 17's regression comparison — never
        required for RCA to function. No baseline set, no baseline
        SuiteRun yet, or either side not yet complete all degrade to
        "no regression evidence available" rather than failing the RCA
        request itself (regression evidence is supplementary context,
        not a precondition for explaining a failure)."""
        try:
            response = await RegressionService(self._session).compare(
                suite_id=suite_id, owner_id=owner_id, candidate_run_id=candidate_run_id
            )
        except (NotFoundError, InvalidStateError):
            return None
        return next((c for c in response.cases if c.test_case_id == test_case_id), None)
