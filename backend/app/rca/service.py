"""Phase 18 — Root Cause Analysis for SuiteRun TestCaseResults.

Reuses the existing two-tier RCA mechanism's underlying primitives
(app/agents/root_cause_analysis.py): a deterministic pattern match first,
an LLM hypothesis only for what the whitelist doesn't cover, via the
exact same `call_model(..., RootCauseHypothesis, agent="rca",
model_group="reasoning")` shape that module already uses. It is NOT
rewritten — `analyze_failure()`'s own goal/plan/flags/tool_calls shape
and its one whitelisted pattern ("too_few_tasks", a Planner-specific
concept) describe the legacy Run flow and have no equivalent meaning for
a SuiteRun's TestCaseResults, so this module is a sibling orchestrator
for a different evidence shape, not a modification of that one.

Two-tier order, matching the locked Phase 18 brief exactly:
  1. Deterministic whitelist (app/rca/evidence.py's `classify_deterministic()`
     — the same 4-category detector app/release_gate/gate.py's hard gate
     also uses) — zero LLM calls.
  2. Only when nothing in the whitelist matches: an LLM hypothesis, built
     strictly from this case's own failing/inconclusive checks (plus,
     when available, Phase 17's regression comparison for the same
     case) — never from anything not already persisted, never a rerun
     of the Agent, Safety, or Grounding.

If a case has no failing/inconclusive evidence at all to reason about,
this never calls the LLM — it returns the explicit "insufficient
observable evidence" tier instead of fabricating a cause.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.agents.schemas import RootCauseHypothesis
from app.ai.client import AIClientError, call_model
from app.models.test_case import TestCase
from app.models.test_case_result import TestCaseResult
from app.rca.evidence import classify_deterministic
from app.schemas.rca import RCAEvidenceItem, RCARegressionEvidence, RCAResponse
from app.schemas.regression import CaseComparison

_PROMPT_PATH = (
    Path(__file__).resolve().parent.parent
    / "agents"
    / "prompts"
    / "suite_case_root_cause_analysis.txt"
)

_RELEVANT_STATUSES = ("fail", "inconclusive")


def _relevant_checks(checks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Evidence worth reasoning about — failing or inconclusive checks
    only, never a PASS/SKIPPED entry (those aren't part of "why did this
    go wrong")."""
    return [c for c in checks if c.get("status") in _RELEVANT_STATUSES]


def _extract_trace_span_ids(result: TestCaseResult) -> list[str]:
    """Phase 10's AgentExecution carries an optional `trace: list[
    TraceSpanRecord]`, but app/services/suite_runner.py's `_evaluate_trial()`
    (Phase 14/16, already approved) never persists it into TestCaseResult
    — only output/latency_ms/error/checks are stored. So trace evidence
    is, today, always unavailable at this layer; this function still
    exists as the single, explicit place that would surface it (from a
    `trace` key, were one ever added to `checks`/`trials` entries by a
    later phase) rather than silently omitting the capability. No new
    Trace/Span table or migration is introduced to change that."""
    span_ids: list[str] = []
    for trial in result.trials:
        trace = trial.get("trace")
        if isinstance(trace, list):
            span_ids.extend(
                str(span["span_id"])
                for span in trace
                if isinstance(span, dict) and "span_id" in span
            )
    return span_ids


def _regression_evidence(case_comparison: CaseComparison | None) -> RCARegressionEvidence | None:
    if case_comparison is None:
        return None
    return RCARegressionEvidence(
        baseline_verdict=case_comparison.baseline_verdict,
        candidate_verdict=case_comparison.candidate_verdict,
        classification=case_comparison.classification,
        output_changed=case_comparison.output_diff.output_changed,
        tool_changed=case_comparison.tool_trajectory_diff.changed,
        safety_changed=case_comparison.safety_diff.changed,
        grounding_changed=case_comparison.grounding_diff.changed,
    )


def _build_prompt(
    test_case: TestCase,
    result: TestCaseResult,
    relevant_checks: list[dict[str, Any]],
    case_comparison: CaseComparison | None,
) -> str:
    checks_text = "\n".join(
        f"- {c.get('check_type')} [{c.get('status')}]: {c.get('detail')}" for c in relevant_checks
    )
    if case_comparison is not None:
        regression_text = (
            f"baseline verdict={case_comparison.baseline_verdict}, "
            f"candidate verdict={case_comparison.candidate_verdict}, "
            f"classification={case_comparison.classification}, "
            f"output changed={case_comparison.output_diff.output_changed}, "
            f"tools changed={case_comparison.tool_trajectory_diff.changed}"
        )
    else:
        regression_text = "(no baseline comparison available)"

    return _PROMPT_PATH.read_text(encoding="utf-8").format(
        test_case_name=test_case.name,
        verdict=result.verdict,
        checks=checks_text or "(none)",
        regression=regression_text,
    )


async def analyze_case(
    *,
    test_case: TestCase,
    result: TestCaseResult,
    case_comparison: CaseComparison | None = None,
) -> RCAResponse:
    """Runs the two-tier RCA for one TestCaseResult. Never reruns the
    Agent, Safety, or Grounding — every input here is already-persisted
    evidence (TestCaseResult.checks/trials, and Phase 17's already
    -computed CaseComparison, if the caller has one)."""
    regression_evidence = _regression_evidence(case_comparison)

    deterministic = classify_deterministic(result.checks)
    if deterministic:
        primary = deterministic[0]
        return RCAResponse(
            test_case_id=test_case.id,
            suite_run_id=result.suite_run_id,
            verdict=result.verdict,
            tier="deterministic",
            root_cause_category=primary.category,
            all_matched_categories=sorted({f.category for f in deterministic}),
            explanation=(f"Deterministic match ({primary.category}): {primary.detail}"),
            evidence_references=[
                RCAEvidenceItem(check_type=f.check_type, status="fail", detail=f.detail)
                for f in deterministic
            ],
            related_check_types=[f.check_type for f in deterministic],
            trace_span_ids=_extract_trace_span_ids(result),
            regression=regression_evidence,
        )

    relevant_checks = _relevant_checks(result.checks)
    if result.verdict == "PASS" and not relevant_checks:
        return RCAResponse(
            test_case_id=test_case.id,
            suite_run_id=result.suite_run_id,
            verdict=result.verdict,
            tier="not_applicable",
            root_cause_category=None,
            all_matched_categories=[],
            explanation=(
                "This test case passed with no failing or inconclusive checks; "
                "no root cause to analyze."
            ),
            evidence_references=[],
            related_check_types=[],
            trace_span_ids=[],
            regression=regression_evidence,
        )

    if not relevant_checks:
        return RCAResponse(
            test_case_id=test_case.id,
            suite_run_id=result.suite_run_id,
            verdict=result.verdict,
            tier="insufficient_evidence",
            root_cause_category=None,
            all_matched_categories=[],
            explanation="insufficient observable evidence to analyze this result",
            evidence_references=[],
            related_check_types=[],
            trace_span_ids=_extract_trace_span_ids(result),
            regression=regression_evidence,
        )

    trace_span_ids = _extract_trace_span_ids(result)
    prompt = _build_prompt(test_case, result, relevant_checks, case_comparison)
    evidence_references = [
        RCAEvidenceItem(
            check_type=c.get("check_type", ""), status=c.get("status"), detail=c.get("detail", "")
        )
        for c in relevant_checks
    ]

    try:
        hypothesis = await call_model(
            prompt, RootCauseHypothesis, agent="rca", model_group="reasoning"
        )
    except AIClientError:
        return RCAResponse(
            test_case_id=test_case.id,
            suite_run_id=result.suite_run_id,
            verdict=result.verdict,
            tier="insufficient_evidence",
            root_cause_category=None,
            all_matched_categories=[],
            explanation=(
                "No deterministic root cause matched, and no LLM hypothesis could be "
                "generated (model unavailable). Manual review required."
            ),
            evidence_references=evidence_references,
            related_check_types=[c.get("check_type", "") for c in relevant_checks],
            trace_span_ids=trace_span_ids,
            regression=regression_evidence,
        )

    return RCAResponse(
        test_case_id=test_case.id,
        suite_run_id=result.suite_run_id,
        verdict=result.verdict,
        tier="llm_hypothesis",
        root_cause_category=None,
        all_matched_categories=[],
        explanation=hypothesis.hypothesis,
        evidence_references=evidence_references,
        related_check_types=[c.get("check_type", "") for c in relevant_checks],
        trace_span_ids=trace_span_ids,
        regression=regression_evidence,
    )
