"""Phase 19 — LLM Judge: the bounded, deterministic-first resolution of
Phase 13's rubric `PENDING_LLM` placeholder check.

Phase 13's engine.py already appends a `check_type="rubric"` check with
`status=PENDING_LLM` whenever `TestCase.rubric` is set, and reports
`OverallVerdict.REQUIRES_LLM` when that is the ONLY thing evaluable
(rubric-only case) — engine.py itself is untouched; this module is the
new, separate caller that actually resolves that placeholder, the same
"reuse the primitive, add a new caller for the new concern" pattern
Phase 15 established for Safety/Grounding relative to the legacy
agents/safety.py and agents/hallucination.py.

Deterministic-first gating (`should_invoke_judge()`) reuses the exact
same objective-hard-failure detectors app/release_gate/gate.py's hard
gate and app/rca/service.py's RCA whitelist already use
(app/rca/evidence.py) — the LLM judge can therefore never be invoked
"merely to override" a safety failure, forbidden tool call, missing
required tool call, schema failure, or objective correctness failure,
by construction, not by convention.

The judge's own resolved check_type is `"rubric_judge"` — deliberately
distinct from Phase 13's own `"rubric"` placeholder (left in `checks[]`
unmodified) and explicitly excluded from app/rca/evidence.py's
`find_correctness_failures()`, so a subjective judge FAIL can never
silently become a Phase 18 correctness hard-gate reason.

Every value passed into the prompt (test case input, actual output,
reference context) is untrusted test content — it is described to the
model as DATA to evaluate, never treated as an instruction, and no tool
execution capability is exposed to the judge at all (call_model() only
ever returns a validated, schema-bound Pydantic object, never lets the
model invoke anything). AgentVersion.adapter_config (where credentials
would live) is never read or passed here.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from app.adapters.execution import ToolCallRecord
from app.ai.client import AIClientError, call_model
from app.evaluation.models import Check, CheckStatus, Determinism
from app.rca.evidence import (
    find_correctness_failures,
    find_forbidden_tool_called,
    find_missing_required_tool_calls,
    find_safety_flags,
    find_schema_failures,
)

CHECK_TYPE = "rubric_judge"

_PROMPT_PATH = (
    Path(__file__).resolve().parent.parent.parent / "agents" / "prompts" / "rubric_judge.txt"
)


class RubricJudgeOutput(BaseModel):
    """Structured, validated judge output (§C) — score only; PASS/FAIL is
    computed deterministically from `score >= TestCase.rubric_threshold`
    (§D) rather than trusted as the model's own boolean, so threshold
    enforcement stays 100% auditable from a single persisted number."""

    score: float = Field(ge=0.0, le=1.0)
    rationale: str = Field(min_length=1, max_length=1000)


def has_objective_hard_failure(checks: list[dict[str, Any]]) -> bool:
    """True if `checks` already contains any of the locked §15 hard-gate
    -eligible objective failures (safety, forbidden tool, missing
    required tool, schema, or a real deterministic correctness FAIL) —
    reused unchanged from app/rca/evidence.py, the exact same evidence
    app/release_gate/gate.py's hard gate itself inspects."""
    return bool(
        find_safety_flags(checks)
        or find_forbidden_tool_called(checks)
        or find_missing_required_tool_calls(checks)
        or find_schema_failures(checks)
        or find_correctness_failures(checks)
    )


def should_invoke_judge(rubric: str | None, checks_so_far: list[dict[str, Any]]) -> bool:
    """The locked §A decision, in one place: no rubric -> never invoke;
    rubric declared but an objective hard failure already exists ->
    never invoke (the failure is already authoritative and the judge
    could not override it — §A.5/§A.6); otherwise -> invoke."""
    if not rubric:
        return False
    return not has_objective_hard_failure(checks_so_far)


def _format_tool_calls(tool_calls: list[ToolCallRecord]) -> str:
    if not tool_calls:
        return "(no tool calls observed)"
    return "\n".join(f"- {tc.tool_name}({tc.input})" for tc in tool_calls)


async def evaluate_rubric_judge(
    *,
    rubric: str,
    rubric_threshold: float,
    test_case_input: dict[str, Any],
    actual_output: Any,
    expected_output: str | None,
    reference_context: str | None,
    tool_calls: list[ToolCallRecord],
) -> Check:
    """Invokes the bounded LLM judge exactly once. Never fabricates a
    PASS or FAIL when the call itself fails (§G) — returns INCONCLUSIVE
    instead, with the failure recorded in `detail`. The caller (app/
    services/suite_runner.py) is responsible for counting this as one
    real invocation toward `SuiteRun.llm_judge_invocation_count`
    regardless of whether it ultimately succeeded or failed, since an
    invocation genuinely occurred either way."""
    output_text = (
        actual_output
        if isinstance(actual_output, str)
        else json.dumps(actual_output, sort_keys=True, default=str)
    )
    prompt = _PROMPT_PATH.read_text(encoding="utf-8").format(
        rubric=rubric,
        input=json.dumps(test_case_input, sort_keys=True, default=str),
        actual_output=output_text,
        expected_output=expected_output or "(none provided)",
        reference_context=reference_context or "(none provided)",
        tool_calls=_format_tool_calls(tool_calls),
    )

    try:
        result = await call_model(
            prompt, RubricJudgeOutput, agent="rubric_judge", model_group="judgment", cacheable=True
        )
    except AIClientError as exc:
        return Check(
            check_type=CHECK_TYPE,
            status=CheckStatus.INCONCLUSIVE,
            determinism=Determinism.REQUIRES_LLM,
            detail=f"LLM judge invocation failed: {exc}",
            metadata={"used_llm": True, "rubric_threshold": rubric_threshold},
        )

    passed = result.score >= rubric_threshold
    return Check(
        check_type=CHECK_TYPE,
        status=CheckStatus.PASS if passed else CheckStatus.FAIL,
        determinism=Determinism.REQUIRES_LLM,
        detail=result.rationale,
        metadata={
            "used_llm": True,
            "score": result.score,
            "rubric_threshold": rubric_threshold,
        },
    )
