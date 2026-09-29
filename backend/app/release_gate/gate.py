"""Phase 18 — deterministic Release Gate for SuiteRuns.

Pure, model-free functions over already-persisted TestCaseResult
evidence — no database access, no adapter call, no LLM call, matching
app/agents/release_decision.py's own "every Ship/Hold decision is
reconstructable from logged gate inputs" discipline exactly.

`soft_score()` below REUSES app.agents.release_decision.compute_soft_score()
UNMODIFIED (§18 of the locked Phase 18 brief) — only its INPUT
construction is adapted for Suite-Run evidence, never its formula.

`evaluate_suite_hard_gate()` is NOT a call into
app.agents.release_decision.evaluate_hard_gate(): that function's hard
-gate whitelist is exactly two legacy Run FlagRecord agent tags
("safety", "hallucination") and cannot express three of Suite-Run
testing's five locked hard-gate categories (forbidden tool, missing
required tool, schema failure — concepts introduced by Phase 13/15/17
that the legacy Run flow never had). Reusing it by faking FlagRecord
entries would also incorrectly make grounding ("hallucination") hard
-gate SuiteRuns, which the locked §15 hard-gate list deliberately does
NOT include (grounding is a soft signal here — see this module's own
classification, documented in the Phase 18 verification report). This
function is therefore new, dedicated logic for the new evidence shape —
the same "reuse the primitive, write new orchestration where the shape
genuinely differs" pattern Phase 15 already established for Safety/
Grounding relative to the legacy agents/safety.py and
agents/hallucination.py.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from app.agents.release_decision import SoftScore, compute_soft_score
from app.rca.evidence import (
    CATEGORY_CORRECTNESS_FAILURE,
    DeterministicFinding,
    find_correctness_failures,
    find_forbidden_tool_called,
    find_missing_required_tool_calls,
    find_safety_flags,
    find_schema_failures,
)

# The locked §15 hard-gate categories, in the order they're listed there.
HARD_GATE_CATEGORIES = (
    "safety_flag",
    "forbidden_tool_called",
    "missing_required_tool_call",
    "schema_failure",
    CATEGORY_CORRECTNESS_FAILURE,
)


@dataclass(frozen=True)
class HardGateReason:
    category: str
    test_case_id: uuid.UUID
    check_type: str
    detail: str


@dataclass(frozen=True)
class HardGateResult:
    passed: bool
    reasons: list[HardGateReason]


def evaluate_case_hard_gate(
    test_case_id: uuid.UUID, verdict: str, checks: list[dict[str, Any]]
) -> list[HardGateReason]:
    """The locked §15 5-category hard gate for ONE TestCaseResult. Reuses
    the same deterministic detectors app/rca/evidence.py's RCA whitelist
    uses for the safety/forbidden-tool/missing-tool/schema categories, so
    RCA and the Release Gate can never silently disagree about what
    counts as e.g. a forbidden tool call.

    §22/§30's classification, implemented exactly, evidence-first:
      - safety_flag: any failing `safety:*` check -> hard.
      - forbidden_tool_called: `forbidden_tool_calls` FAIL -> hard.
      - missing_required_tool_call: a `tool_call[i]:tool` FAIL that means
        "never called" -> hard.
      - schema_failure: any `output_schema` FAIL -> hard (broader than
        RCA's narrower `schema_field_missing`; every schema validation
        failure is hard, not only a missing-required-field one).
      - correctness_failure: an actual failing `expected_output`/
        `assertion[i]`/`tool_call_order`/argument-constraint check —
        app/rca/evidence.py's `find_correctness_failures()` — evaluated
        ONLY when verdict == "FAIL". This is deliberately NOT
        `verdict == "FAIL"` by itself (a real bug fixed in this
        correction): a case can legitimately FAIL solely because of
        `latency`, which §15's hard-gate list does not include, and
        treating every FAIL verdict as a correctness hard gate would
        have wrongly hard-gated that case too. `find_correctness_failures()`
        itself excludes `latency`/`grounding`/`rubric` and anything
        already covered by the other four named categories above.

        The `verdict == "FAIL"` guard here (rather than always scanning
        for correctness-check evidence) exists specifically so an
        INCONCLUSIVE trial-majority-tie case (Phase 16 — its outer
        `checks` mirror only its LAST trial, which may itself have
        genuinely failed on correctness) is never hard-gated merely
        because of that one trial's own checks — the case's real,
        majority-aggregated verdict is INCONCLUSIVE, not FAIL, and
        correctness ambiguity from a trial split is not the same claim
        as an unambiguous failure. Safety/forbidden-tool/missing-tool/
        schema are NOT guarded this way: those represent objectively
        -observed events (something unsafe/forbidden/missing/malformed
        genuinely happened in that trial), not a correctness
        interpretation, so they remain hard-gate-eligible regardless of
        the case's aggregated verdict, exactly matching §26 ("no trial
        majority can override a safety hard gate").

    Deliberately NOT hard-gated here (documented, considered scope,
    §15/§22/§30/§31): grounding FAIL/INCONCLUSIVE/SKIPPED, latency_exceeded
    (a real, separate RCA category — §6/§9 — but not one of §15's five
    named hard-gate categories), and any INCONCLUSIVE verdict (rubric
    -only or trial-majority-tie) considered on its own — all remain
    soft/visible-only signals, never an automatic HOLD.
    """
    findings: list[DeterministicFinding] = [
        *find_safety_flags(checks),
        *find_forbidden_tool_called(checks),
        *find_missing_required_tool_calls(checks),
        *find_schema_failures(checks),
    ]
    if verdict == "FAIL":
        findings.extend(find_correctness_failures(checks))
    return [HardGateReason(f.category, test_case_id, f.check_type, f.detail) for f in findings]


def evaluate_suite_hard_gate(
    results: list[tuple[uuid.UUID, str, list[dict[str, Any]]]],
) -> HardGateResult:
    """`results`: (test_case_id, verdict, checks) for every TestCaseResult
    in the SuiteRun being gated. HOLDS (passed=False) if ANY case
    produces at least one hard-gate reason — a single unsafe tool call,
    forbidden tool call, missing required tool, schema failure, or FAIL
    verdict anywhere in the suite blocks the whole release, regardless of
    how many other cases passed (§26-29: none of these can be outvoted
    by pass rate, soft score, or trial majority)."""
    all_reasons: list[HardGateReason] = []
    for test_case_id, verdict, checks in results:
        all_reasons.extend(evaluate_case_hard_gate(test_case_id, verdict, checks))
    return HardGateResult(passed=not all_reasons, reasons=all_reasons)


def soft_score(*, pass_rate: float | None) -> SoftScore:
    """Reuses app.agents.release_decision.compute_soft_score() UNMODIFIED
    (§18) — only its inputs are adapted for Suite-Run evidence.
    `retry_count=0` and `auto_fix_applied=False` are not placeholders:
    Phase 19 AutoFix does not exist yet, and the Suite Runner has no
    retry concept of its own (a retried suite run's already-resulted
    cases are skipped, never re-attempted — app/services/suite_runner.py),
    so zero/False are the actually-correct values today, exactly per
    §17's explicit "represent the input as zero/not-applicable" instruction.
    """
    base = pass_rate if pass_rate is not None else 0.0
    return compute_soft_score(evaluations=[{"score": base}], retry_count=0, auto_fix_applied=False)
