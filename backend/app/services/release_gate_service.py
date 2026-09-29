"""Phase 18 — Release Gate orchestration for a SuiteRun.

    SuiteRun -> its TestCaseResults (Phase 14/16 final verdicts) ->
    app.release_gate.gate.evaluate_suite_hard_gate() (deterministic,
    model-free) + soft_score() (reuses app.agents.release_decision.
    compute_soft_score() unmodified) -> Phase 17 regression comparison,
    reused best-effort as a soft input -> ReleaseDecisionResponse

Nothing here reruns the Agent, Suite Runner, Safety, or Grounding —
every input is already-persisted TestCaseResult evidence or Phase 17's
own already-computed regression comparison (itself evidence-only, see
app/services/regression_service.py). Nothing here calls an LLM: the
hard-gate/soft-score computation is 100% deterministic, matching
app/agents/release_decision.py's own "no opaque LLM call decides
Ship/Hold" discipline.

Approval integration (§21): when the hard gate passes, a real
`Approval(suite_run_id=..., node="release_decision")` row is created via
the SAME Approval model/table/repository Phase 9's legacy Run workflow
already uses (app/models/approval.py, app/repositories/approval_repository.py)
— not a second approval system. Idempotent: a pending approval already
queued for this SuiteRun is reused, never duplicated. Deciding that
approval (approve/reject) via the legacy decide() workflow is
intentionally out of scope for this phase — see the Phase 18
verification report for why.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import InvalidStateError, NotFoundError
from app.models.test_case_result import TestCaseResult
from app.release_gate.gate import HardGateReason, evaluate_suite_hard_gate, soft_score
from app.repositories.approval_repository import ApprovalRepository
from app.schemas.release import (
    HardGateReasonRead,
    RegressionSoftInput,
    ReleaseDecisionResponse,
    ReleaseDecisionValue,
)
from app.services.activity_service import ActivityService
from app.services.regression_service import RegressionService
from app.services.suite_run_service import SuiteRunService

# The same terminal-status precedent Phase 17's RegressionService already
# established (app/services/regression_service.py's own
# _COMPARABLE_STATUSES) — release evaluation is allowed for a "failed"
# SuiteRun too: a crashed/partial run still has whatever TestCaseResults
# were persisted before it failed, and those remain real evidence worth
# gating on (a partial run will simply show fewer evaluated cases and,
# almost always, a hard-gate-relevant hole — the natural, honest
# consequence of incomplete evidence, not a special-cased rule).
_COMPARABLE_STATUSES = ("completed", "failed")


class ReleaseGateService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._suite_runs = SuiteRunService(session)
        self._approvals = ApprovalRepository(session)
        self._activity = ActivityService(session)

    async def evaluate(
        self, *, suite_run_id: uuid.UUID, owner_id: uuid.UUID
    ) -> ReleaseDecisionResponse:
        # Ownership chain: SuiteRun -> TestSuite -> Agent -> Project,
        # reused verbatim (never reimplemented) — raises NotFoundError/
        # PermissionDeniedError exactly as every other suite-run-scoped
        # service already does.
        suite_run = await self._suite_runs.get_suite_run(
            suite_run_id=suite_run_id, owner_id=owner_id
        )
        if suite_run.status not in _COMPARABLE_STATUSES:
            raise InvalidStateError(
                f"suite run {suite_run_id} has status '{suite_run.status}' — release "
                "evaluation requires a finished suite run (completed or failed), not "
                "pending, running, or cancelling."
            )

        results = await self._suite_runs.list_results(suite_run_id=suite_run_id, owner_id=owner_id)

        hard_gate = evaluate_suite_hard_gate(
            [(r.test_case_id, r.verdict, r.checks) for r in results]
        )

        total = len(results)
        pass_count = sum(1 for r in results if r.verdict == "PASS")
        fail_count = sum(1 for r in results if r.verdict == "FAIL")
        inconclusive_count = sum(1 for r in results if r.verdict == "INCONCLUSIVE")
        rubric_case_count = sum(1 for r in results if _has_rubric_check(r))

        pass_rate = None if total == 0 else pass_count / total
        inconclusive_rate = None if total == 0 else inconclusive_count / total

        safety_flag_count = _count_reasons(hard_gate.reasons, "safety_flag")
        forbidden_tool_count = _count_reasons(hard_gate.reasons, "forbidden_tool_called")
        missing_required_tool_count = _count_reasons(
            hard_gate.reasons, "missing_required_tool_call"
        )
        schema_failure_count = _count_reasons(hard_gate.reasons, "schema_failure")

        regression = await self._try_regression(suite_run.suite_id, suite_run.id, owner_id)
        score = soft_score(pass_rate=pass_rate)

        decision: ReleaseDecisionValue
        reason: str
        approval_required: bool
        if not hard_gate.passed:
            categories = sorted({r.category for r in hard_gate.reasons})
            decision = "hold"
            approval_required = False
            reason = f"Hard gate failed: {', '.join(categories)}."
        else:
            decision = "pass"
            approval_required = True
            reason = (
                f"Hard gate passed; soft score {score.value:.2f}. Ship is a proposal — "
                "human approval is required before this SuiteRun is actually released."
            )
            await self._ensure_pending_approval(suite_run.id, reason)

        # Recent Activity / Release Gate nav page: deduped on (event_type,
        # entity_id, title) — evaluate() is a re-checkable read-mostly
        # operation (a user re-opening the release review page calls this
        # again), so an identical re-check must not flood the feed; a
        # genuinely changed decision (a different title: "Held" vs
        # "Passed") still records as the new fact it is.
        title = "Release Gate Held" if decision == "hold" else "Release Gate Passed"
        await self._activity.record(
            owner_id=owner_id,
            event_type="release_gate_evaluated",
            title=title,
            description=reason,
            entity_type="suite_run",
            entity_id=suite_run.id,
            metadata={"decision": decision, "hard_gate_passed": hard_gate.passed},
            dedupe=True,
        )

        return ReleaseDecisionResponse(
            suite_run_id=suite_run.id,
            decision=decision,
            hard_gate_passed=hard_gate.passed,
            hard_gate_reasons=[
                HardGateReasonRead(
                    category=r.category,
                    test_case_id=r.test_case_id,
                    check_type=r.check_type,
                    detail=r.detail,
                )
                for r in hard_gate.reasons
            ],
            approval_required=approval_required,
            total_cases=total,
            pass_count=pass_count,
            fail_count=fail_count,
            inconclusive_count=inconclusive_count,
            pass_rate=pass_rate,
            inconclusive_rate=inconclusive_rate,
            safety_flag_count=safety_flag_count,
            forbidden_tool_count=forbidden_tool_count,
            missing_required_tool_count=missing_required_tool_count,
            schema_failure_count=schema_failure_count,
            rubric_case_count=rubric_case_count,
            regression=regression,
            soft_score=score.value,
            soft_score_components=score.components,
            reason=reason,
        )

    async def _try_regression(
        self, suite_id: uuid.UUID, suite_run_id: uuid.UUID, owner_id: uuid.UUID
    ) -> RegressionSoftInput:
        """Best-effort reuse of Phase 17 — a soft input only (§25), never
        a precondition for computing a release decision. No baseline, no
        baseline SuiteRun yet, or the baseline not being finished all
        degrade to "regression unavailable" rather than failing release
        evaluation itself."""
        try:
            response = await RegressionService(self._session).compare(
                suite_id=suite_id, owner_id=owner_id, candidate_run_id=suite_run_id
            )
        except (NotFoundError, InvalidStateError):
            return RegressionSoftInput(available=False)
        return RegressionSoftInput(
            available=True,
            regression_count=response.summary.regressions,
            improvement_count=response.summary.improvements,
            pass_rate_delta=response.summary.pass_rate_delta,
        )

    async def _ensure_pending_approval(self, suite_run_id: uuid.UUID, reason: str) -> None:
        existing = await self._approvals.get_pending_for_suite_run(suite_run_id)
        if existing is not None:
            return
        await self._approvals.create(
            suite_run_id=suite_run_id, node="release_decision", reason=reason
        )
        await self._session.commit()


def _has_rubric_check(result: TestCaseResult) -> bool:
    return any(c.get("check_type") == "rubric" for c in result.checks)


def _count_reasons(reasons: list[HardGateReason], category: str) -> int:
    return sum(1 for r in reasons if r.category == category)
