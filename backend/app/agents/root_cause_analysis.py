"""Root Cause Analysis: explains *why* a run failed after retries are
exhausted.

Per the blueprint ("Correlates failure signature against known-issue
memory; falls back to LLM reasoning over the trace... No (feeds Planner,
doesn't act)"): two-tier, same shape as Safety's deterministic-then-LLM
design (agents/safety.py) — a failure signature is matched
deterministically against Auto Fix's ONE whitelisted pattern first (see
agents/auto_fix.py's own docstring for why the whitelist is exactly one
pattern); only a non-whitelisted failure falls through to an LLM
hypothesis, which is advisory only — RCA never decides an action itself,
it either identifies a whitelisted pattern (routing to Auto Fix) or
hands a human a written hypothesis (routing to hold_for_human), matching
"No (feeds Planner, doesn't act)" from the per-agent table: this project
adapts "feeds Planner" to "feeds the human reviewing the failed run",
since re-planning automatically from an RCA hypothesis would itself be
an unreviewed automated action, which the same table's Auto Fix row
explicitly requires approval for.

"Known-issue memory" correlation reuses Phase 6's memory manager exactly
as the blueprint's Memory Manager spec describes ("Long/short-term
context store for all agents") — remember() is called for every failure
this module analyzes (source_type="run_failure"), so future RCA calls
can recall() similar past failures. This is advisory context included in
the LLM hypothesis prompt, not a decision input: the whitelist match
itself stays 100% deterministic code, never influenced by what memory
returns (same "never rely solely on the LLM" discipline Safety already
established).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from app.agents.schemas import RootCauseHypothesis
from app.agents.state import FlagRecord, ToolCallRecord
from app.agents.verification import MIN_TASKS_TO_VERIFY
from app.ai.client import AIClientError, call_model
from app.memory import manager as memory_manager

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "root_cause_analysis.txt"

# The one failure signature Auto Fix knows how to fix (see auto_fix.py).
WHITELISTED_PATTERN_TOO_FEW_TASKS = "too_few_tasks"


@dataclass
class RCAResult:
    whitelisted: bool
    pattern: str | None
    hypothesis: str


def _last_verification_output(tool_calls: list[ToolCallRecord]) -> str:
    for tc in reversed(tool_calls):
        if tc["tool_name"] == "run_python":
            return tc["output"]
    return "(no verification tool call found in this run's history)"


def _detect_whitelisted_pattern(plan: list[str], flags: list[FlagRecord]) -> str | None:
    """Deterministic signature match — the ONLY thing that decides
    whether Auto Fix gets a chance to act. A Safety block anywhere in the
    run means the failure isn't a simple "too few tasks" case (Safety
    denied a real tool call; appending a task wouldn't address that), so
    it's excluded from the whitelist even if the plan also happens to be
    short.
    """
    if any(f["agent"] == "safety" for f in flags):
        return None
    if len(plan) < MIN_TASKS_TO_VERIFY:
        return WHITELISTED_PATTERN_TOO_FEW_TASKS
    return None


async def analyze_failure(
    *,
    goal: str,
    plan: list[str],
    flags: list[FlagRecord],
    tool_calls: list[ToolCallRecord],
) -> RCAResult:
    """Analyzes a failed, retries-exhausted run. Never raises — an
    unreviewable failure (LLM unavailable) still returns a usable
    (generic) hypothesis rather than blocking the human's review."""
    pattern = _detect_whitelisted_pattern(plan, flags)

    failure_signature = pattern or "unclassified_failure"
    similar_failures = await memory_manager.recall(
        f"Failure signature: {failure_signature}. Goal: {goal}",
        source_type="run_failure",
        top_k=3,
    )

    # Remembered regardless of whitelist status — even whitelisted
    # failures are useful "known issue" precedent for a future RCA call
    # on a differently-shaped failure with the same underlying signature.
    await memory_manager.remember(
        content=f"Failure signature: {failure_signature}. Goal: {goal}. Plan: {plan}",
        source_type="run_failure",
    )

    if pattern is not None:
        return RCAResult(
            whitelisted=True,
            pattern=pattern,
            hypothesis=(
                f"Plan had only {len(plan)} task(s), below the required minimum of "
                f"{MIN_TASKS_TO_VERIFY} — matches the whitelisted '{pattern}' pattern, "
                "routing to Auto Fix."
            ),
        )

    flags_text = "\n".join(
        f"- {f['agent']}: {f['type']} ({f['severity']}) — {f['details']}" for f in flags
    )
    prompt = _PROMPT_PATH.read_text(encoding="utf-8").format(
        goal=goal,
        plan="\n".join(f"- {task}" for task in plan) or "(empty plan)",
        verification_output=_last_verification_output(tool_calls),
        flags=flags_text or "(none)",
        similar_failures="\n".join(f"- {s}" for s in similar_failures) or "(none found)",
    )

    try:
        result = await call_model(prompt, RootCauseHypothesis, agent="rca", model_group="reasoning")
    except AIClientError:
        logger.warning("RCA: LLM hypothesis unavailable; falling back to a generic note.")
        return RCAResult(
            whitelisted=False,
            pattern=None,
            hypothesis=(
                "Verification failed for a reason outside the known whitelist, and no "
                "LLM hypothesis could be generated (model unavailable). Manual review required."
            ),
        )

    return RCAResult(whitelisted=False, pattern=None, hypothesis=result.hypothesis)
