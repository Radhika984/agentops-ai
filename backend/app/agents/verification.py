"""Verification node: confirms the plan actually meets spec.

Per the blueprint ("Runs the actual test suite / schema validation —
deterministic, not LLM judgment where possible"), the check itself stays
deterministic: a plan only counts as verified if it decomposes the goal
into more than one step.

Phase 5: that check is now executed via the sandboxed `run_python` tool
(app/tools/servers/exec_server.py) rather than being inline Python in this
node — the blueprint's "Verification agents need a standard way to call
external tools... without hand-rolling a bespoke tool-calling layer per
tool" applies to Verification as much as Planner. The plan is embedded in
the generated snippet via repr() (it's our own trusted data, not
user-controlled code, so this is safe) and the tool's stdout ("PASS" or
"FAIL") drives the result. If the tool call itself fails or is blocked
for any reason, verification fails safe (treated as not passed) rather
than trusting an unverifiable result.

Phase 7: the plan's task text (LLM-generated, ultimately derived from the
user-supplied goal) is embedded in that same code string — so it's still
possible for a Safety deny-pattern to match here too, even though this
call's *shape* is our own trusted template. A block is recorded as a flag
the same way planner.py records one for `web_search`.
"""

from __future__ import annotations

from app.agents.state import AgentState, FlagRecord, ToolCallRecord
from app.tools.registry import call_tool

MIN_TASKS_TO_VERIFY = 2

_CHECK_TEMPLATE = """
plan = {plan!r}
min_tasks = {min_tasks!r}
print("PASS" if len(plan) >= min_tasks else "FAIL")
"""


def build_verification_code(plan: list[str]) -> str:
    """The exact sandboxed check both verification_node (below) and
    Phase 9's Auto Fix re-verify step (agents/auto_fix.py) run — a single
    source of truth for what "passes verification" means, rather than
    two copies that could silently drift apart.
    """
    return _CHECK_TEMPLATE.format(plan=plan, min_tasks=MIN_TASKS_TO_VERIFY)


async def verification_node(state: AgentState) -> AgentState:
    code = build_verification_code(state["plan"])

    tool_result = await call_tool("run_python", {"code": code})
    tool_call_record: ToolCallRecord = {
        "tool_name": tool_result.tool_name,
        "input": tool_result.input,
        "output": tool_result.output,
        "duration_ms": tool_result.duration_ms,
        "ok": tool_result.ok,
    }

    new_flags: list[FlagRecord] = []
    if tool_result.blocked_by_safety:
        new_flags.append(
            FlagRecord(
                agent="safety",
                type=tool_result.safety_type or "blocked",
                severity=tool_result.safety_severity or "medium",
                details=tool_result.output,
            )
        )

    passed = tool_result.ok and tool_result.output.strip() == "PASS"

    return {
        **state,
        "verification_passed": passed,
        "status": "verifying",
        "tool_calls": [*state["tool_calls"], tool_call_record],
        "flags": [*state["flags"], *new_flags],
    }
