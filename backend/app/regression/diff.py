"""Phase 17 — Regression Comparison: pure, deterministic diff helpers.

Every function here takes already-persisted TestCaseResult data (from two
different SuiteRuns of the SAME TestSuite — one baseline, one candidate)
and returns a factual comparison. Nothing here performs a database query,
invokes an AgentAdapter, or calls an LLM — the locked Phase 17 brief
requires regression comparison to be entirely reproducible from persisted
evidence alone. app/services/regression_service.py is the only module
that touches the database or the ORM; this module is its pure
computation layer, matching exactly how app/evaluation/engine.py (Phase
13) separates evaluation logic from app/services/suite_runner.py's
persistence/orchestration.

Tool-call evidence: the only place raw, real (not ground-truth-declared)
tool-call data survives into persisted checks[] is Phase 15's Safety
check, `safety:tool_call[{index}]:{tool_name}` (app/evaluation/checks/
safety.py) — present whenever observability_level >= 2, independent of
whether the TestCase declares any `expected_tool_calls` at all. Raw
argument values are never part of the persisted evidence (only Phase
13's tool_trajectory.py records whether an expected call's argument
constraints were satisfied, as a PASS/FAIL check) — so "changed tool
arguments" here means "the same argument-constraint check flipped
between baseline and candidate," not a raw before/after argument diff.
This is documented explicitly in the Phase 17 verification report as a
genuine, considered scope boundary, not an oversight.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from app.evaluation.models import CheckStatus
from app.schemas.regression import (
    GroundingDiff,
    LatencyDiff,
    OutputDiff,
    SafetyDiff,
    ToolTrajectoryDiff,
    VerdictClassification,
)

# Phase 15's per-observed-call safety check_type, e.g. "safety:tool_call[0]:search".
_OBSERVED_TOOL_CALL_RE = re.compile(r"^safety:tool_call\[\d+\]:")
# Phase 13's per-expected-call trajectory check_type, e.g. "tool_call[0]:search"
# — deliberately does not match "expected_tool_call[...]" (the malformed
# -spec error check_type) or "safety:tool_call[...]" (a different namespace).
_EXPECTED_TOOL_CALL_RE = re.compile(r"^tool_call\[\d+\]:")
_SAFETY_CHECK_RE = re.compile(r"^safety:")

GROUNDING_CHECK_TYPE = "grounding"

# The locked Phase 17 verdict-transition rule (§8/§9) — the only source
# of truth for what counts as a regression or improvement.
_REGRESSIONS = {("PASS", "FAIL"), ("PASS", "INCONCLUSIVE")}
_IMPROVEMENTS = {("FAIL", "PASS"), ("INCONCLUSIVE", "PASS")}


def classify_verdict_change(baseline_verdict: str, candidate_verdict: str) -> VerdictClassification:
    """PASS->FAIL and PASS->INCONCLUSIVE are regressions; FAIL->PASS and
    INCONCLUSIVE->PASS are improvements; identical verdicts are
    unchanged; every other transition (FAIL<->INCONCLUSIVE) is a real,
    observable difference but is deliberately not classified as either,
    per the locked brief's explicit "do not incorrectly classify" rule
    (§9/§10) — reported as "changed" instead of being silently dropped.
    """
    pair = (baseline_verdict, candidate_verdict)
    if pair in _REGRESSIONS:
        return "regression"
    if pair in _IMPROVEMENTS:
        return "improvement"
    if baseline_verdict == candidate_verdict:
        return "unchanged"
    return "changed"


def diff_output(baseline_output: Any, candidate_output: Any) -> OutputDiff:
    """Deterministic structural comparison of already-parsed JSON values.
    Both sides come straight from TestCaseResult.actual_output, a JSONB
    column SQLAlchemy already deserializes into plain Python dict/list/
    str/None — Python's own `==` on parsed structures IS "semantic JSON
    comparison, not serialized-string comparison": dict equality never
    depends on key insertion order, so two structurally-identical
    outputs built in a different key order compare equal.
    """
    return OutputDiff(
        baseline_output=baseline_output,
        candidate_output=candidate_output,
        output_changed=baseline_output != candidate_output,
    )


def diff_checks_by_type(
    baseline_checks: list[dict[str, Any]], candidate_checks: list[dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    """Generic, reusable check-status diff, keyed by `check_type`, over
    the union of both sides' check_types. A `check_type` present on only
    one side (e.g. an observability-level difference between the
    baseline and candidate AgentVersions makes per-tool-call safety
    checks appear/disappear) is itself a real, factual difference, not
    an error — its missing side's status is reported as `None`. Every
    category-specific diff below (tool trajectory, safety) is built on
    top of this one function rather than duplicating the union/lookup
    logic per category (per the locked brief's §29 "small deterministic
    utility, no duplicated evaluator logic" instruction).
    """
    baseline_by_type = {c["check_type"]: c["status"] for c in baseline_checks}
    candidate_by_type = {c["check_type"]: c["status"] for c in candidate_checks}

    diff: dict[str, dict[str, Any]] = {}
    for check_type in sorted(set(baseline_by_type) | set(candidate_by_type)):
        baseline_status = baseline_by_type.get(check_type)
        candidate_status = candidate_by_type.get(check_type)
        diff[check_type] = {
            "baseline_status": baseline_status,
            "candidate_status": candidate_status,
            "changed": baseline_status != candidate_status,
        }
    return diff


def _observed_tool_names(checks: list[dict[str, Any]]) -> list[str]:
    """The ordered list of tool names Phase 15's Safety check actually
    observed via the real AgentExecution.tool_calls it was given — list
    order matches checks[] array order, which matches invocation order
    (safety.py builds these via `enumerate(tool_calls)`), never re-sorted
    here."""
    names: list[str] = []
    for check in checks:
        check_type = check.get("check_type", "")
        if _OBSERVED_TOOL_CALL_RE.match(check_type):
            metadata = check.get("metadata") or {}
            tool_name = metadata.get("tool_name")
            if tool_name is not None:
                names.append(str(tool_name))
    return names


def diff_tool_trajectory(
    baseline_checks: list[dict[str, Any]], candidate_checks: list[dict[str, Any]]
) -> ToolTrajectoryDiff:
    baseline_tools = _observed_tool_names(baseline_checks)
    candidate_tools = _observed_tool_names(candidate_checks)
    baseline_multiset = Counter(baseline_tools)
    candidate_multiset = Counter(candidate_tools)

    added_tools = sorted((candidate_multiset - baseline_multiset).elements())
    removed_tools = sorted((baseline_multiset - candidate_multiset).elements())
    # Same tools, same counts, different sequence — a real trajectory
    # -order change, distinct from an added/removed tool.
    order_changed = baseline_tools != candidate_tools and baseline_multiset == candidate_multiset

    check_diff = diff_checks_by_type(baseline_checks, candidate_checks)
    argument_changes = sorted(
        check_type
        for check_type, entry in check_diff.items()
        if _EXPECTED_TOOL_CALL_RE.match(check_type) and entry["changed"]
    )

    changed = bool(added_tools or removed_tools or order_changed or argument_changes)

    return ToolTrajectoryDiff(
        baseline_tools=baseline_tools,
        candidate_tools=candidate_tools,
        added_tools=added_tools,
        removed_tools=removed_tools,
        order_changed=order_changed,
        argument_changes=argument_changes,
        changed=changed,
    )


def diff_latency(baseline_latency_ms: int | None, candidate_latency_ms: int | None) -> LatencyDiff:
    """Raw factual delta only — no invented threshold, no subjective
    "meaningfully slower" judgement (the locked brief explicitly forbids
    both). `changed` is strictly `delta_ms != 0`. Either side missing
    means the comparison itself is unavailable, not zero."""
    if baseline_latency_ms is None or candidate_latency_ms is None:
        return LatencyDiff(
            baseline_latency_ms=baseline_latency_ms,
            candidate_latency_ms=candidate_latency_ms,
            delta_ms=None,
            available=False,
            changed=False,
        )
    delta_ms = candidate_latency_ms - baseline_latency_ms
    return LatencyDiff(
        baseline_latency_ms=baseline_latency_ms,
        candidate_latency_ms=candidate_latency_ms,
        delta_ms=delta_ms,
        available=True,
        changed=delta_ms != 0,
    )


def diff_safety(
    baseline_checks: list[dict[str, Any]], candidate_checks: list[dict[str, Any]]
) -> SafetyDiff:
    """Compares every `safety:*` check_type (both the per-tool-call and
    the output check) between baseline and candidate. Computed entirely
    from the persisted checks[] array — completely independent of
    TestCaseResult.verdict, so a candidate safety failure stays visible
    even when the overall verdict happens to be PASS (the locked brief's
    explicit "do not hide safety changes behind the overall verdict"
    rule)."""
    check_diff = diff_checks_by_type(baseline_checks, candidate_checks)
    safety_entries = {k: v for k, v in check_diff.items() if _SAFETY_CHECK_RE.match(k)}

    newly_unsafe = sorted(
        check_type
        for check_type, entry in safety_entries.items()
        if entry["baseline_status"] != CheckStatus.FAIL.value
        and entry["candidate_status"] == CheckStatus.FAIL.value
    )
    resolved = sorted(
        check_type
        for check_type, entry in safety_entries.items()
        if entry["baseline_status"] == CheckStatus.FAIL.value
        and entry["candidate_status"] != CheckStatus.FAIL.value
    )

    def _aggregate(side: str) -> str:
        statuses = {entry[side] for entry in safety_entries.values() if entry[side] is not None}
        if CheckStatus.FAIL.value in statuses:
            return CheckStatus.FAIL.value
        if statuses and statuses <= {CheckStatus.SKIPPED.value}:
            return CheckStatus.SKIPPED.value
        if statuses:
            return CheckStatus.PASS.value
        return CheckStatus.SKIPPED.value

    return SafetyDiff(
        baseline_status=_aggregate("baseline_status"),
        candidate_status=_aggregate("candidate_status"),
        newly_unsafe=newly_unsafe,
        resolved=resolved,
        changed=bool(newly_unsafe or resolved),
    )


def diff_grounding(
    baseline_checks: list[dict[str, Any]], candidate_checks: list[dict[str, Any]]
) -> GroundingDiff:
    """Compares the single `grounding` check_type between baseline and
    candidate, exposing the raw PASS/FAIL/SKIPPED/INCONCLUSIVE status on
    each side as-is — SKIPPED is never coerced into PASS."""
    baseline_status = next(
        (c["status"] for c in baseline_checks if c.get("check_type") == GROUNDING_CHECK_TYPE), None
    )
    candidate_status = next(
        (c["status"] for c in candidate_checks if c.get("check_type") == GROUNDING_CHECK_TYPE), None
    )
    return GroundingDiff(
        baseline_status=baseline_status,
        candidate_status=candidate_status,
        changed=baseline_status != candidate_status,
    )
