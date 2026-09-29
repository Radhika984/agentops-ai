"""Auto Fix: attempts an automated patch for a known failure class.

Per the blueprint ("Only acts on a whitelist of known-safe fix patterns;
anything else routes to a human... Yes, before the fix is applied to
anything beyond a sandbox"): this module implements exactly ONE
whitelisted pattern — a plan with fewer than
verification.MIN_TASKS_TO_VERIFY tasks gets one generic closing task
appended. This is deliberately narrow. The blueprint's own "Common
Mistakes" warns against letting the whitelist "grow informally without
review" — a single, explicitly-reviewed pattern is the honest
implementation of that warning, not a placeholder for more; adding a
second pattern is a real, reviewed design decision for a future phase,
not something this module or its caller should infer on its own.

Two steps, matching the blueprint's "Proposed diff" -> approval ->
"sandboxed apply-and-reverify" shape:
1. propose_fix() — a constrained LLM call (see prompts/auto_fix.txt)
   phrases the one task to append; only ever called after
   root_cause_analysis.py's deterministic whitelist match, never on its
   own initiative.
2. apply_and_reverify() — called only after a human approves the
   proposal (see app/approvals/service.py) — mutates a *copy* of the
   plan and re-runs the exact same sandboxed check verification_node
   uses (build_verification_code()), never the original run's state
   directly, so a rejected/failed re-verify never corrupts anything.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from app.agents.schemas import AutoFixPatch
from app.agents.state import FlagRecord, ToolCallRecord
from app.agents.verification import build_verification_code
from app.ai.client import AIClientError, call_model
from app.tools.registry import call_tool

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "auto_fix.txt"

# Only used if the constrained LLM call itself fails — never a silent
# behavior change, just keeps the whitelisted fix available even when the
# model is unreachable (same fail-open posture as Hallucination).
_FALLBACK_TASK = "Review and confirm all planned steps are complete."


@dataclass
class AutoFixReverifyResult:
    passed: bool
    new_plan: list[str]
    tool_call: ToolCallRecord
    flags: list[FlagRecord]


async def propose_fix(*, goal: str, plan: list[str]) -> str:
    """Returns the one task text to append. Only ever called on a plan
    that root_cause_analysis.py has already deterministically matched
    against the whitelist — this function does not re-check that."""
    from app.agents.verification import MIN_TASKS_TO_VERIFY

    prompt = _PROMPT_PATH.read_text(encoding="utf-8").format(
        min_tasks=MIN_TASKS_TO_VERIFY,
        goal=goal,
        plan="\n".join(f"- {task}" for task in plan) or "(empty plan)",
    )
    try:
        result = await call_model(prompt, AutoFixPatch, agent="auto_fix", model_group="reasoning")
    except AIClientError:
        logger.warning("Auto Fix: LLM patch phrasing unavailable; using the fallback task text.")
        return _FALLBACK_TASK
    return result.additional_task


async def apply_and_reverify(*, plan: list[str], additional_task: str) -> AutoFixReverifyResult:
    """Applies the whitelisted patch to a *copy* of `plan` and re-runs
    the real sandboxed verification check against it — genuinely
    "sandboxed apply-and-reverify", not a simulated pass."""
    new_plan = [*plan, additional_task]
    code = build_verification_code(new_plan)

    tool_result = await call_tool("run_python", {"code": code})
    tool_call: ToolCallRecord = {
        "tool_name": tool_result.tool_name,
        "input": tool_result.input,
        "output": tool_result.output,
        "duration_ms": tool_result.duration_ms,
        "ok": tool_result.ok,
    }

    flags: list[FlagRecord] = []
    if tool_result.blocked_by_safety:
        flags.append(
            FlagRecord(
                agent="safety",
                type=tool_result.safety_type or "blocked",
                severity=tool_result.safety_severity or "medium",
                details=tool_result.output,
            )
        )

    passed = tool_result.ok and tool_result.output.strip() == "PASS"

    return AutoFixReverifyResult(passed=passed, new_plan=new_plan, tool_call=tool_call, flags=flags)
