"""Phase 15 — Safety repointed at real AgentExecution data.

Reuses app.agents.safety.check_tool_call() verbatim — the exact same
deterministic policy engine + LLM-fallback classifier Phase 7 already
built and Phase 5's tool registry already calls for the legacy Run path.
Nothing about that mechanism is rewritten here; only its CALLER and DATA
SOURCE change:

  OLD (agents/planner.py, agents/verification.py): checked AgentOps's
  own web_search/run_python tool calls, made while generating its own
  plan.
  NEW (this module): checks the real System Under Test's tool calls, as
  actually reported by AgentExecution.tool_calls — never reconstructed
  from planner state, LangGraph messages, or anything else.

`determinism=DETERMINISTIC` on every Check here, even the ones where
check_tool_call()'s LLM fallback was consulted: unlike a rubric (which
is never resolved without Phase 19), Safety's LLM fallback resolves to a
real, final allow/deny answer right now, in this phase — it is an
already-approved (Phase 7) part of the deterministic-first evaluation
surface, not a deferred Phase 19 judge call. Whether the fallback fired
is preserved in `metadata["used_llm_fallback"]` for auditability.

Per the locked audit: these checks are recorded for visibility/
attribution (which TestCaseResult, which tool call, which policy) only
— they do not influence TestCaseResult.verdict in this phase (that
remains exactly Phase 14's existing Phase-13-only computation). Making
Safety failures gate anything is Phase 18's Release Gate, not this one.
"""

from __future__ import annotations

import json
from typing import Any

from app.adapters.execution import ToolCallRecord
from app.agents.safety import check_tool_call
from app.evaluation.models import Check, CheckStatus, Determinism

# Per the locked audit's Observability Model: tool-call visibility starts
# at Level 2. Below that, tool calls simply are not part of what the
# connected agent exposes — see this module's own SKIPPED detail text.
MIN_OBSERVABILITY_LEVEL_FOR_TOOL_SAFETY = 2

_OUTPUT_SAFETY_TOOL_NAME = "agent_output"


async def evaluate_tool_call_safety(
    tool_calls: list[ToolCallRecord], observability_level: int
) -> list[Check]:
    """One Check per real, observed tool call (Level 2+), via
    check_tool_call() unmodified. Below Level 2, tool calls are not
    observable at all — returns a single SKIPPED check, never a
    fabricated PASS ("no unsafe tool calls" is not the same claim as
    "no tool calls were visible"). An agent that made zero real tool
    calls at Level 2+ is genuinely different from that and is reported
    as such (a real PASS: there was something to check, and it checked
    out empty)."""
    if observability_level < MIN_OBSERVABILITY_LEVEL_FOR_TOOL_SAFETY:
        return [
            Check(
                check_type="safety:tool_calls",
                status=CheckStatus.SKIPPED,
                determinism=Determinism.DETERMINISTIC,
                detail=(
                    f"tool-call safety not evaluable at observability level "
                    f"{observability_level} — tool calls are not observable at this "
                    "level. This is not evidence that no unsafe tool call occurred, "
                    "only that none could be observed."
                ),
                metadata={"observability_level": observability_level},
            )
        ]

    if not tool_calls:
        return [
            Check(
                check_type="safety:tool_calls",
                status=CheckStatus.PASS,
                determinism=Determinism.DETERMINISTIC,
                detail="0 tool calls were observed — nothing to check",
            )
        ]

    checks: list[Check] = []
    for index, tool_call in enumerate(tool_calls):
        result = await check_tool_call(tool_call.tool_name, tool_call.input)
        checks.append(
            Check(
                check_type=f"safety:tool_call[{index}]:{tool_call.tool_name}",
                status=CheckStatus.PASS if result.allowed else CheckStatus.FAIL,
                determinism=Determinism.DETERMINISTIC,
                detail=result.reason
                or ("allowed by policy" if result.allowed else "blocked by policy"),
                metadata={
                    "tool_name": tool_call.tool_name,
                    "policy_type": result.type,
                    "severity": result.severity,
                    "used_llm_fallback": result.used_llm_fallback,
                },
            )
        )
    return checks


async def evaluate_output_safety(output: Any) -> Check:
    """Runs check_tool_call() once against the agent's real final output
    text — available at every observability level (output is the one
    thing every adapter, even Level 1 black-box, always returns). The
    output is passed to the policy engine/LLM classifier purely as DATA
    to examine (wrapped as a single-key argument dict, exactly like a
    real tool call's arguments) — it is never treated as an instruction,
    and this call can only ever *deny* based on it, never execute it.
    """
    if output is None:
        return Check(
            check_type="safety:output",
            status=CheckStatus.PASS,
            determinism=Determinism.DETERMINISTIC,
            detail="no output to evaluate for safety (the agent execution produced none)",
        )

    output_text = output if isinstance(output, str) else json.dumps(output, sort_keys=True)
    result = await check_tool_call(_OUTPUT_SAFETY_TOOL_NAME, {"output": output_text})
    return Check(
        check_type="safety:output",
        status=CheckStatus.PASS if result.allowed else CheckStatus.FAIL,
        determinism=Determinism.DETERMINISTIC,
        detail=result.reason or ("allowed by policy" if result.allowed else "blocked by policy"),
        metadata={
            "policy_type": result.type,
            "severity": result.severity,
            "used_llm_fallback": result.used_llm_fallback,
        },
    )
