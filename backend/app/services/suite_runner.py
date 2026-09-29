"""Phase 14/15/16 — the Suite Runner: the background task that actually
connects Agent Registry + AgentVersion + TestSuite/TestCase + the Phase
13 Assertion Engine + Phase 15 Safety/Grounding + Phase 16 repeated
trials.

    TestSuite -> SuiteRun -> for each TestCase, trial_count independent
    adapter invocations -> one AgentExecution per trial -> Phase 13
    evaluate() + Phase 15 Safety/Grounding per trial -> strict-majority
    aggregation across that case's trials -> one persisted
    TestCaseResult -> SuiteRun aggregate counts/status

Runs as a FastAPI BackgroundTasks callback scheduled from
app/api/v1/suite_runs.py, exactly matching the existing legacy Run
pattern (app/services/run_service.py's run_graph_and_persist): it
executes after the HTTP response has already been sent, so it opens its
own DB session via AsyncSessionLocal rather than reusing the request's
(which is already closed by then).

This module owns scheduling, execution, and persistence only — it is
the "clean composition layer" the locked Phase 15 brief asks for,
combining independent evaluation components without duplicating any of
their internals:
  - app.evaluation.engine.evaluate() (Phase 13 — unchanged, untouched)
  - app.evaluation.checks.safety (Phase 15 — real AgentExecution.tool_calls
    + output, via app.agents.safety.check_tool_call() unmodified)
  - app.evaluation.checks.grounding (Phase 15 — TestCase.reference_context
    + real AgentExecution.output, via the same entailment mechanism
    app.agents.hallucination.py already uses)

Per the locked Phase 15 brief, Safety/Grounding checks are captured and
attributed to the right TestCaseResult for visibility, but do NOT
influence TestCaseResult.verdict in this phase; that remains exactly
Phase 13's own deterministic per-trial verdict, aggregated by strict
majority across trials (Phase 16) the same way a single trial's verdict
was used directly before. Making Safety/Grounding gate anything is
Phase 18's Release Gate, not this module.

Phase 16 concurrency note: every adapter invocation — whether it belongs
to a different TestCase or a different trial of the same TestCase — is
dispatched through the exact same `asyncio.Semaphore(suite_run.
max_concurrency)` Phase 14 already created. There is deliberately no
second, trial-level semaphore: that would risk multiplying concurrency
beyond the configured suite-level bound, which the locked Phase 16 brief
explicitly forbids.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections import Counter, defaultdict
from datetime import UTC, datetime
from typing import Any

from app.adapters.base import AgentAdapter
from app.adapters.exceptions import AdapterConfigError
from app.adapters.execution import AgentExecution
from app.adapters.factory import build_adapter
from app.ai.client import owner_call_context
from app.db.session import AsyncSessionLocal
from app.evaluation.checks.grounding import evaluate_grounding
from app.evaluation.checks.llm_judge import evaluate_rubric_judge, should_invoke_judge
from app.evaluation.checks.safety import evaluate_output_safety, evaluate_tool_call_safety
from app.evaluation.engine import evaluate, from_test_case
from app.evaluation.models import Check, CheckStatus, OverallVerdict
from app.models.agent_version import AgentVersion
from app.models.test_case import TestCase
from app.repositories.agent_version_repository import AgentVersionRepository
from app.repositories.suite_run_repository import SuiteRunRepository
from app.repositories.test_case_repository import TestCaseRepository
from app.repositories.test_case_result_repository import TestCaseResultRepository
from app.services.activity_service import ActivityService, resolve_suite_run_owner_id

logger = logging.getLogger(__name__)

# Phase 13's OverallVerdict has no DB representation of its own — this is
# the one, single place that maps it onto the three verdict strings the
# locked schema requires, used for every *trial's* verdict (Phase 16)
# exactly as it was previously used for a case's only trial (Phase 14).
# REQUIRES_LLM (no deterministic ground truth was applicable — e.g. a
# rubric-only case) becomes INCONCLUSIVE: nothing in this phase calls an
# LLM judge, so a trial that needs one cannot be reported as PASS or
# FAIL, only as "not yet conclusively evaluated."
_VERDICT_MAP: dict[OverallVerdict, str] = {
    OverallVerdict.PASS: "PASS",
    OverallVerdict.FAIL: "FAIL",
    OverallVerdict.REQUIRES_LLM: "INCONCLUSIVE",
}

_TERMINAL_STATUSES = ("completed", "failed")

# Phase 19: the LLM judge's own resolved status maps directly onto the
# same three trial-verdict strings every other check family already
# produces — used ONLY when Phase 13's engine reported REQUIRES_LLM
# (i.e. nothing deterministic was applicable at all, so the judge's
# answer IS the trial's real answer); see _evaluate_trial()'s own
# docstring for why a deterministic PASS/FAIL is never overridden by it.
_JUDGE_STATUS_TO_VERDICT: dict[CheckStatus, str] = {
    CheckStatus.PASS: "PASS",
    CheckStatus.FAIL: "FAIL",
    CheckStatus.INCONCLUSIVE: "INCONCLUSIVE",
}

# One (case, trial_index) invocation task's outcome — trial_index is
# 0-based (0..trial_count-1), matching the field name/shape Phase 14
# already persisted for its one, implicit trial (see TrialEntry below).
TrialInvocation = tuple[TestCase, int, AgentExecution | None, str | None]


async def _invoke_trial(
    adapter: AgentAdapter, case: TestCase, trial_index: int, semaphore: asyncio.Semaphore
) -> TrialInvocation:
    """Invokes one trial of one case's input through the suite's
    adapter, bounded by the single shared `semaphore` — this is the
    actual concurrency control: at most `suite_run.max_concurrency` of
    these run at once, across every case and every trial in the suite
    combined, never per-case or per-trial. A per-invocation
    AdapterConfigError (e.g. a transient DNS/SSRF-validation failure) is
    captured here, not raised, so one trial's connectivity problem never
    aborts the case's remaining trials or any other case."""
    async with semaphore:
        try:
            # Every trial receives the exact same, unmutated case.input —
            # this is what lets repeated execution actually observe a
            # nondeterministic agent's real variance, rather than testing
            # trial_index itself.
            execution = await adapter.invoke(case.input)
        except AdapterConfigError as exc:
            return case, trial_index, None, str(exc)
        return case, trial_index, execution, None


def aggregate_trial_verdicts(verdicts: list[str]) -> str:
    """The locked Phase 16 strict-majority rule: a verdict wins only if
    it has *more than half* of the completed trials — not a plurality.
    With no strict majority (including a tie, or three-way splits with
    INCONCLUSIVE trials mixed in), the case-level result is
    INCONCLUSIVE. Pure function, no DB/IO — trivially unit-testable.

    trial_count=1 is not a special case: a single verdict is trivially a
    strict majority of itself (threshold 1 of 1), so PASS/FAIL/
    INCONCLUSIVE pass straight through, preserving Phase 14's exact
    single-trial behavior.
    """
    if not verdicts:
        return "INCONCLUSIVE"

    counts = Counter(verdicts)
    threshold = len(verdicts) // 2 + 1
    for verdict, count in counts.items():
        if count >= threshold:
            return verdict
    return "INCONCLUSIVE"


async def _evaluate_trial(
    case: TestCase,
    version: AgentVersion,
    execution: AgentExecution | None,
    config_error: str | None,
) -> dict[str, Any]:
    """Runs the full per-trial evaluation pipeline (Phase 13 + Phase 15 +
    Phase 19 LLM judge) against exactly one trial's own AgentExecution
    and returns its persistable entry. Never reuses another trial's
    execution, checks, or output — each call only ever sees what its own
    `execution` parameter carries.
    """
    if execution is None:
        # Same existing Phase 14 semantic, now applied per-trial rather
        # than per-case: an adapter/config-level failure is a real,
        # attributable FAIL for that trial — never silently dropped from
        # `trials`, never turned into a PASS.
        return {
            "verdict": "FAIL",
            "status": "error",
            "checks": [],
            "actual_output": None,
            "latency_ms": None,
            "error": config_error,
            "llm_judge_invoked": False,
        }

    evaluation_input = from_test_case(case)
    eval_result = evaluate(evaluation_input, execution)
    verdict = _VERDICT_MAP[eval_result.verdict]

    # Phase 15: Safety (real tool_calls[] + output) and Grounding
    # (TestCase.reference_context + this trial's real output) — composed
    # here, not inside evaluate() itself, so Phase 13's own behavior/
    # tests stay completely untouched. Computed fresh per trial: a
    # trial's tool calls/output never influence another trial's checks.
    safety_checks = await evaluate_tool_call_safety(
        execution.tool_calls, version.observability_level
    )
    output_safety_check = await evaluate_output_safety(execution.output)
    grounding_check = await evaluate_grounding(case.reference_context, execution.output)
    all_checks: list[Check] = [
        *eval_result.checks,
        *safety_checks,
        output_safety_check,
        grounding_check,
    ]

    # Phase 19: the bounded LLM judge — invoked at most once per trial,
    # deterministic-first (should_invoke_judge() never fires when an
    # objective hard failure is already present in all_checks, and never
    # fires at all when the TestCase declares no rubric). A deterministic
    # PASS/FAIL is never overridden: the judge's own resolved status only
    # replaces `verdict` when Phase 13's engine had nothing deterministic
    # to say at all (REQUIRES_LLM, i.e. a rubric-only case) — otherwise
    # it is recorded as its own, separately-visible "rubric_judge" check
    # and the deterministic verdict remains authoritative, matching the
    # locked brief's "deterministic evaluation remains the primary
    # evaluation mechanism."
    llm_judge_invoked = False
    if case.rubric and should_invoke_judge(
        case.rubric, [c.model_dump(mode="json") for c in all_checks]
    ):
        judge_check = await evaluate_rubric_judge(
            rubric=case.rubric,
            rubric_threshold=case.rubric_threshold,
            test_case_input=case.input,
            actual_output=execution.output,
            expected_output=case.expected_output,
            reference_context=case.reference_context,
            tool_calls=execution.tool_calls,
        )
        llm_judge_invoked = True
        all_checks.append(judge_check)
        if eval_result.verdict == OverallVerdict.REQUIRES_LLM:
            verdict = _JUDGE_STATUS_TO_VERDICT[judge_check.status]

    return {
        "verdict": verdict,
        "status": execution.status,
        "checks": [check.model_dump(mode="json") for check in all_checks],
        "actual_output": execution.output,
        "latency_ms": execution.latency_ms,
        "error": execution.error,
        "llm_judge_invoked": llm_judge_invoked,
    }


async def execute_suite_run(suite_run_id: uuid.UUID) -> None:
    """Executes `suite_run_id` end to end and persists the outcome.
    Never raises — a genuine, unexpected failure is caught, logged, and
    turned into `SuiteRun.status = "failed"` rather than propagating out
    of a BackgroundTasks callback (which has no caller left to observe
    an exception by the time this runs)."""
    async with AsyncSessionLocal() as session:
        suite_run_repo = SuiteRunRepository(session)
        case_repo = TestCaseRepository(session)
        result_repo = TestCaseResultRepository(session)
        version_repo = AgentVersionRepository(session)

        suite_run = await suite_run_repo.get_by_id(suite_run_id)
        if suite_run is None:
            logger.error("execute_suite_run: suite run %s not found", suite_run_id)
            return

        if suite_run.status in _TERMINAL_STATUSES:
            # Idempotency guard: a retried/duplicate trigger for a suite
            # run that has already reached a terminal state is a no-op,
            # not a re-execution.
            logger.info(
                "execute_suite_run: suite run %s already %s — skipping",
                suite_run_id,
                suite_run.status,
            )
            return

        try:
            await suite_run_repo.mark_running(suite_run, started_at=datetime.now(UTC))
            await session.commit()

            version = await version_repo.get_by_id(suite_run.agent_version_id)
            if version is None:
                raise RuntimeError(f"agent version {suite_run.agent_version_id} not found")

            # Resolved once, up front, and reused both to attribute every
            # model_calls row this run's trials trigger (grounding,
            # rubric-judge, safety's LLM fallback — see
            # app/ai/client.py's owner_call_context) and, further below,
            # for the real Recent Activity event — never queried twice
            # for the same suite_run.
            owner_id = await resolve_suite_run_owner_id(session, suite_run.suite_id)

            adapter = build_adapter(version.adapter_type, version.adapter_config)
            # Phase 20: excludes any TestCase still status="candidate" —
            # a proposed regression test from a real production failure
            # must never silently execute until a human accepts it.
            cases = await case_repo.list_active_by_suite(suite_run.suite_id)

            # Idempotency, checked *before* any invocation (not only at
            # persistence time as Phase 14 did): a retried suite run must
            # never re-invoke a real external agent for a case that
            # already has a persisted result.
            already_resulted = await result_repo.existing_test_case_ids(suite_run.id)
            cases_to_run = [case for case in cases if case.id not in already_resulted]

            semaphore = asyncio.Semaphore(suite_run.max_concurrency)
            # Every (case, trial) pair across the *entire* suite shares
            # this one gather/semaphore — this is what makes
            # max_concurrency a true suite-wide bound rather than a
            # per-case one; a case with trial_count=4 does not get its
            # own independent concurrency budget.
            trial_tasks = [
                _invoke_trial(adapter, case, trial_index, semaphore)
                for case in cases_to_run
                for trial_index in range(case.trial_count)
            ]
            invocations = await asyncio.gather(*trial_tasks) if trial_tasks else []

            invocations_by_case: dict[uuid.UUID, list[TrialInvocation]] = defaultdict(list)
            for invocation in invocations:
                invocations_by_case[invocation[0].id].append(invocation)

            with owner_call_context(owner_id):
                for case in cases_to_run:
                    # Deterministic numeric order regardless of which
                    # trial happened to finish first under concurrency.
                    case_trials = sorted(invocations_by_case[case.id], key=lambda inv: inv[1])

                    trial_entries: list[dict[str, Any]] = []
                    trial_verdicts: list[str] = []
                    for _, trial_index, execution, config_error in case_trials:
                        trial_result = await _evaluate_trial(
                            case, version, execution, config_error
                        )
                        trial_entries.append({"trial_index": trial_index, **trial_result})
                        trial_verdicts.append(trial_result["verdict"])

                    final_verdict = aggregate_trial_verdicts(trial_verdicts)
                    # The outer (case-level) checks/actual_output/
                    # latency_ms/error fields mirror the *last* trial's —
                    # a single, deterministic, always-defined summary;
                    # the complete per-trial history (including every
                    # earlier trial's own checks/output/latency/error)
                    # remains fully intact and independently inspectable
                    # in `trials` below.
                    last_trial = trial_entries[-1]

                    await result_repo.create(
                        suite_run_id=suite_run.id,
                        test_case_id=case.id,
                        verdict=final_verdict,
                        verdict_method="majority",
                        checks=last_trial["checks"],
                        trials=trial_entries,
                        actual_output=last_trial["actual_output"],
                        latency_ms=last_trial["latency_ms"],
                        error=last_trial["error"],
                        # AutoFix is Phase 19 — never populated here.
                        suggested_fix=None,
                    )

            await session.commit()

            counts = await result_repo.aggregate_counts(suite_run.id)
            # Phase 19: recomputed from the full persisted set (like
            # every other counter above), not accumulated in memory for
            # just this execution — correct even if the runner is
            # retried mid-run and some results (and their own earlier
            # judge invocations) already existed from a prior attempt.
            all_results = await result_repo.list_by_suite_run(suite_run.id)
            llm_judge_invocation_count = sum(
                1
                for result in all_results
                for trial in result.trials
                for check in trial.get("checks", [])
                if isinstance(check, dict) and check.get("check_type") == "rubric_judge"
            )
            await suite_run_repo.mark_terminal(
                suite_run,
                status="completed",
                completed_at=datetime.now(UTC),
                pass_count=counts["PASS"],
                fail_count=counts["FAIL"],
                inconclusive_count=counts["INCONCLUSIVE"],
                # Never incremented — no case-level "skip" condition
                # exists yet (see models/suite_run.py). Aggregate counts
                # are per TestCaseResult (one row per case, holding the
                # already-majority-aggregated verdict), never per trial —
                # a 4-trial case contributes exactly one count, to
                # exactly one bucket, regardless of trial_count.
                skipped_count=suite_run.skipped_count,
                llm_judge_invocation_count=llm_judge_invocation_count,
            )
            await session.commit()

            # Recent Activity: a real, one-time occurrence — this branch
            # only runs once per SuiteRun (the idempotency guard at the
            # top of this function returns early for an already-terminal
            # run), so no dedupe is needed here, unlike Release Gate's
            # re-checkable evaluate(). owner_id was already resolved
            # above (and used to attribute this run's model_calls rows);
            # reused here rather than queried again. A dangling suite_id
            # (owner_id is None) should never happen given the FK, but is
            # defensively handled by simply skipping the event, never
            # raising.
            if owner_id is not None:
                total = counts["PASS"] + counts["FAIL"] + counts["INCONCLUSIVE"]
                await ActivityService(session).record(
                    owner_id=owner_id,
                    event_type="suite_run_completed",
                    title="Suite Run Completed",
                    description=(
                        f"{counts['PASS']}/{total} passed, {counts['FAIL']} failed, "
                        f"{counts['INCONCLUSIVE']} inconclusive."
                    ),
                    entity_type="suite_run",
                    entity_id=suite_run.id,
                    metadata={
                        "pass_count": counts["PASS"],
                        "fail_count": counts["FAIL"],
                        "inconclusive_count": counts["INCONCLUSIVE"],
                    },
                )

        except Exception:
            logger.exception("execute_suite_run: suite run %s failed", suite_run_id)
            await session.rollback()
            failed_run = await suite_run_repo.get_by_id(suite_run_id)
            if failed_run is not None:
                await suite_run_repo.mark_terminal(
                    failed_run,
                    status="failed",
                    completed_at=datetime.now(UTC),
                    pass_count=failed_run.pass_count,
                    fail_count=failed_run.fail_count,
                    inconclusive_count=failed_run.inconclusive_count,
                    skipped_count=failed_run.skipped_count,
                    llm_judge_invocation_count=failed_run.llm_judge_invocation_count,
                )
                await session.commit()
