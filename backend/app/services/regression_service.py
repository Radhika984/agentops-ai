"""Phase 17 — Regression Comparison: baseline SuiteRun vs. candidate
SuiteRun of the SAME TestSuite, computed entirely on read.

    TestSuite -> baseline AgentVersion (is_baseline=true)
              -> latest baseline SuiteRun for this suite
              -> candidate SuiteRun (explicitly requested by the caller)
              -> join TestCaseResults by test_case_id
              -> app.regression.diff (pure, deterministic, no DB/LLM)
              -> RegressionResponse

No RegressionResult table exists, no migration was added, and nothing
computed here is ever persisted — every call recomputes the comparison
fresh from TestSuite/AgentVersion/SuiteRun/TestCaseResult, per the locked
Phase 17 brief (§25).

Ownership is resolved the same way every other suite-scoped service
already resolves it: reusing TestSuiteService.get_suite() (itself
composing AgentService -> ProjectService), never reimplementing the
chain. The baseline AgentVersion and baseline SuiteRun are derived
strictly from the caller-owned TestSuite's own Agent — nothing here ever
accepts a baseline identifier from the request.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import InvalidStateError, NotFoundError
from app.models.suite_run import SuiteRun
from app.models.test_case_result import TestCaseResult
from app.regression.diff import (
    classify_verdict_change,
    diff_grounding,
    diff_latency,
    diff_output,
    diff_safety,
    diff_tool_trajectory,
)
from app.repositories.agent_version_repository import AgentVersionRepository
from app.repositories.suite_run_repository import SuiteRunRepository
from app.repositories.test_case_result_repository import TestCaseResultRepository
from app.schemas.regression import (
    CaseComparison,
    RegressionResponse,
    RegressionSummary,
    TrialSummary,
)
from app.services.test_suite_service import TestSuiteService

# The same two terminal values app/services/suite_runner.py's own
# _TERMINAL_STATUSES already uses (that name is private to suite_runner's
# module scope, so not imported directly) — a SuiteRun is only
# comparable once it has stopped changing; "pending"/"running"/
# "cancelling" are rejected (§6).
_COMPARABLE_STATUSES = ("completed", "failed")

# TestCaseResult.verdict's DB CHECK constraint only ever allows PASS/
# FAIL/INCONCLUSIVE (models/test_case_result.py) — SKIPPED never appears
# as a case-level verdict today (there is no case-level "skip" condition
# yet, matching suite_runner.py's own skipped_count comment). The bucket
# is still counted the same way as the other three, from TestCaseResults
# (§18's exact instruction), so it stays correct without guessing if a
# later phase ever introduces one.
_VERDICT_BUCKETS = ("PASS", "FAIL", "INCONCLUSIVE", "SKIPPED")


class RegressionService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._suites = TestSuiteService(session)
        self._suite_runs = SuiteRunRepository(session)
        self._results = TestCaseResultRepository(session)
        self._versions = AgentVersionRepository(session)

    async def compare(
        self, *, suite_id: uuid.UUID, owner_id: uuid.UUID, candidate_run_id: uuid.UUID
    ) -> RegressionResponse:
        # Ownership chain: TestSuite -> Agent -> Project, reused verbatim
        # (never reimplemented) — raises NotFoundError/PermissionDeniedError.
        suite = await self._suites.get_suite(suite_id=suite_id, owner_id=owner_id)

        candidate_run = await self._suite_runs.get_by_id(candidate_run_id)
        if candidate_run is None or candidate_run.suite_id != suite.id:
            # Same-suite requirement (§5) and "never leak whether an
            # inaccessible SuiteRun exists" (§22) collapse into one
            # response: a candidate run from a different suite (whether
            # or not the caller owns that other suite) is indistinguishable
            # from one that doesn't exist — the exact same compound-key
            # convention SuiteRunService.get_result() already uses for
            # result_id vs suite_run_id.
            raise NotFoundError(
                f"Suite run not found for test suite {suite_id}: {candidate_run_id}"
            )

        baseline_version = await self._versions.get_baseline(suite.agent_id)
        if baseline_version is None:
            raise NotFoundError(
                f"Agent {suite.agent_id} has no baseline AgentVersion set — "
                "promote one (POST /agents/{agent_id}/versions/{version_id}/baseline) "
                "before requesting a regression comparison."
            )

        baseline_run = await self._suite_runs.get_latest_by_suite_and_version(
            suite_id=suite.id, agent_version_id=baseline_version.id
        )
        if baseline_run is None:
            raise NotFoundError(
                f"No SuiteRun exists for the baseline AgentVersion "
                f"{baseline_version.id} on test suite {suite.id} — run the "
                "suite against the baseline version before comparing."
            )

        self._require_comparable(baseline_run, role="baseline")
        self._require_comparable(candidate_run, role="candidate")

        baseline_results = await self._results.list_by_suite_run(baseline_run.id)
        candidate_results = await self._results.list_by_suite_run(candidate_run.id)

        return self._build_response(
            suite_id=suite.id,
            baseline_run=baseline_run,
            candidate_run=candidate_run,
            baseline_results=baseline_results,
            candidate_results=candidate_results,
        )

    @staticmethod
    def _require_comparable(suite_run: SuiteRun, *, role: str) -> None:
        if suite_run.status not in _COMPARABLE_STATUSES:
            raise InvalidStateError(
                f"the {role} suite run {suite_run.id} has status "
                f"'{suite_run.status}' — regression comparison requires both "
                "suite runs to have finished (completed or failed), not "
                "pending, running, or cancelling."
            )

    def _build_response(
        self,
        *,
        suite_id: uuid.UUID,
        baseline_run: SuiteRun,
        candidate_run: SuiteRun,
        baseline_results: list[TestCaseResult],
        candidate_results: list[TestCaseResult],
    ) -> RegressionResponse:
        # Joined by test_case_id only (§7) — never by result id, never by
        # array position, never assuming identical execution order.
        baseline_by_case = {r.test_case_id: r for r in baseline_results}
        candidate_by_case = {r.test_case_id: r for r in candidate_results}

        matched_ids = sorted(set(baseline_by_case) & set(candidate_by_case), key=str)
        new_ids = sorted(set(candidate_by_case) - set(baseline_by_case), key=str)
        missing_ids = sorted(set(baseline_by_case) - set(candidate_by_case), key=str)

        cases = [
            self._compare_case(baseline_by_case[case_id], candidate_by_case[case_id])
            for case_id in matched_ids
        ]

        summary = self._summarize(
            cases=cases,
            new_count=len(new_ids),
            missing_count=len(missing_ids),
            baseline_results=baseline_results,
            candidate_results=candidate_results,
        )

        return RegressionResponse(
            suite_id=suite_id,
            baseline_suite_run_id=baseline_run.id,
            baseline_agent_version_id=baseline_run.agent_version_id,
            candidate_suite_run_id=candidate_run.id,
            candidate_agent_version_id=candidate_run.agent_version_id,
            summary=summary,
            cases=cases,
            new_test_case_ids=new_ids,
            missing_test_case_ids=missing_ids,
        )

    @staticmethod
    def _compare_case(baseline: TestCaseResult, candidate: TestCaseResult) -> CaseComparison:
        # Primary classification uses the FINAL, majority-aggregated
        # TestCaseResult.verdict only (§17/§23) — never a per-trial verdict.
        return CaseComparison(
            test_case_id=baseline.test_case_id,
            classification=classify_verdict_change(baseline.verdict, candidate.verdict),
            baseline_verdict=baseline.verdict,
            candidate_verdict=candidate.verdict,
            output_diff=diff_output(baseline.actual_output, candidate.actual_output),
            tool_trajectory_diff=diff_tool_trajectory(baseline.checks, candidate.checks),
            latency_diff=diff_latency(baseline.latency_ms, candidate.latency_ms),
            safety_diff=diff_safety(baseline.checks, candidate.checks),
            grounding_diff=diff_grounding(baseline.checks, candidate.checks),
            # Phase 16 trial evidence, summarized (not rescored/reranked)
            # for visibility only — never used for classification.
            trial_summary=TrialSummary(
                baseline_trial_verdicts=[str(t.get("verdict", "")) for t in baseline.trials],
                candidate_trial_verdicts=[str(t.get("verdict", "")) for t in candidate.trials],
            ),
        )

    @staticmethod
    def _summarize(
        *,
        cases: list[CaseComparison],
        new_count: int,
        missing_count: int,
        baseline_results: list[TestCaseResult],
        candidate_results: list[TestCaseResult],
    ) -> RegressionSummary:
        regressions = sum(1 for c in cases if c.classification == "regression")
        improvements = sum(1 for c in cases if c.classification == "improvement")
        unchanged = sum(1 for c in cases if c.classification == "unchanged")
        changed = sum(1 for c in cases if c.classification == "changed")

        def _counts(results: list[TestCaseResult]) -> dict[str, int]:
            # One TestCaseResult == one count, regardless of trial_count
            # (§18/§19 — "do not count individual trials"): the majority
            # -aggregated verdict Phase 16 already computed is what's
            # counted here, exactly once per case.
            counts = dict.fromkeys(_VERDICT_BUCKETS, 0)
            for result in results:
                counts[result.verdict] = counts.get(result.verdict, 0) + 1
            return counts

        baseline_counts = _counts(baseline_results)
        candidate_counts = _counts(candidate_results)
        baseline_total = len(baseline_results)
        candidate_total = len(candidate_results)

        def _rate(count: int, total: int) -> float | None:
            return None if total == 0 else count / total

        baseline_pass_rate = _rate(baseline_counts["PASS"], baseline_total)
        candidate_pass_rate = _rate(candidate_counts["PASS"], candidate_total)
        baseline_inconclusive_rate = _rate(baseline_counts["INCONCLUSIVE"], baseline_total)
        candidate_inconclusive_rate = _rate(candidate_counts["INCONCLUSIVE"], candidate_total)

        return RegressionSummary(
            total_matched_cases=len(cases),
            regressions=regressions,
            improvements=improvements,
            unchanged=unchanged,
            changed=changed,
            new_cases=new_count,
            missing_cases=missing_count,
            baseline_pass_count=baseline_counts["PASS"],
            candidate_pass_count=candidate_counts["PASS"],
            baseline_fail_count=baseline_counts["FAIL"],
            candidate_fail_count=candidate_counts["FAIL"],
            baseline_inconclusive_count=baseline_counts["INCONCLUSIVE"],
            candidate_inconclusive_count=candidate_counts["INCONCLUSIVE"],
            baseline_skipped_count=baseline_counts["SKIPPED"],
            candidate_skipped_count=candidate_counts["SKIPPED"],
            baseline_pass_rate=baseline_pass_rate,
            candidate_pass_rate=candidate_pass_rate,
            pass_rate_delta=(
                None
                if baseline_pass_rate is None or candidate_pass_rate is None
                else candidate_pass_rate - baseline_pass_rate
            ),
            baseline_inconclusive_rate=baseline_inconclusive_rate,
            candidate_inconclusive_rate=candidate_inconclusive_rate,
            inconclusive_rate_delta=(
                None
                if baseline_inconclusive_rate is None or candidate_inconclusive_rate is None
                else candidate_inconclusive_rate - baseline_inconclusive_rate
            ),
            safety_changes=sum(1 for c in cases if c.safety_diff.changed),
            grounding_changes=sum(1 for c in cases if c.grounding_diff.changed),
            latency_changes=sum(1 for c in cases if c.latency_diff.changed),
            tool_changes=sum(1 for c in cases if c.tool_trajectory_diff.changed),
        )
