"""A toy "agent" module for LocalAdapter tests — stands in for a real
locally-importable agent a developer would point AgentOps at."""

from __future__ import annotations

import asyncio
from typing import Any


def invoke(input: dict[str, Any]) -> dict[str, Any]:
    return {"output": f"echo: {input.get('question', '')}"}


async def invoke_async(input: dict[str, Any]) -> dict[str, Any]:
    return {
        "output": {"answer": "42"},
        "tool_calls": [
            {"tool_name": "calculator", "input": {"expr": "6*7"}, "output": "42", "ok": True}
        ],
    }


def invoke_plain_string(input: dict[str, Any]) -> str:
    return "just a plain string answer"


def invoke_raises(input: dict[str, Any]) -> dict[str, Any]:
    raise RuntimeError("the toy agent broke")


# ---- Phase 14: concurrency-tracking fixture --------------------------
#
# A module-level counter, not a per-instance one: LocalAdapter imports
# this module fresh via importlib for each AgentVersion, but Python
# caches modules in sys.modules — every LocalAdapter instance within one
# test process shares this same counter, which is exactly what lets a
# test observe the Suite Runner's real peak concurrency.

_concurrency_state = {"current": 0, "peak": 0}


async def invoke_track_concurrency(input: dict[str, Any]) -> dict[str, Any]:
    _concurrency_state["current"] += 1
    _concurrency_state["peak"] = max(_concurrency_state["peak"], _concurrency_state["current"])
    await asyncio.sleep(0.1)
    _concurrency_state["current"] -= 1
    return {"output": "ok"}


def reset_concurrency_state() -> None:
    _concurrency_state["current"] = 0
    _concurrency_state["peak"] = 0


def get_peak_concurrency() -> int:
    return _concurrency_state["peak"]


# ---- Phase 15: Safety/Grounding fixtures ------------------------------
#
# "rm -rf" / "password=..." are real entries in
# app/observability/policy_rules.yaml's deny_patterns — matching them
# triggers a genuine deterministic Safety FAIL with no LLM call
# involved, exactly like a real unsafe tool call would.


async def invoke_with_safe_tool_call(input: dict[str, Any]) -> dict[str, Any]:
    return {
        "output": "done",
        "tool_calls": [
            {
                "tool_name": "search",
                "input": {"query": "weather today"},
                "output": "sunny",
                "ok": True,
            }
        ],
    }


async def invoke_with_unsafe_tool_call(input: dict[str, Any]) -> dict[str, Any]:
    return {
        "output": "done",
        "tool_calls": [
            {
                "tool_name": "shell",
                "input": {"command": "rm -rf /tmp/data"},
                "output": "",
                "ok": True,
            }
        ],
    }


async def invoke_with_multiple_tool_calls(input: dict[str, Any]) -> dict[str, Any]:
    return {
        "output": "done",
        "tool_calls": [
            {"tool_name": "search", "input": {"query": "weather"}, "output": "sunny", "ok": True},
            {"tool_name": "shell", "input": {"command": "rm -rf /"}, "output": "", "ok": True},
        ],
    }


def invoke_unsafe_output(input: dict[str, Any]) -> dict[str, Any]:
    return {"output": "here is the password=hunter2 for the admin account"}


def invoke_safe_output(input: dict[str, Any]) -> dict[str, Any]:
    return {"output": "the weather today is sunny"}


# ---- Phase 16: nondeterministic-trial fixtures ------------------------
#
# Every trial of the same TestCase sends the identical `input` (per the
# locked Phase 16 rule), so a fixture that must produce genuinely
# different output per call has no choice but to key off call count —
# real nondeterministic agents are externally stateful in exactly this
# same sense. Module-level state (not per-instance) for the same reason
# as the concurrency tracker above: LocalAdapter re-imports this module
# per invocation, but Python caches it, so all trials of one test share
# the same counter.

_call_counter = {"count": 0}


async def invoke_incrementing(input: dict[str, Any]) -> dict[str, Any]:
    """A distinct output every call — proves trials are genuinely
    independent executions, never a cached/reused result."""
    _call_counter["count"] += 1
    return {"output": f"call-{_call_counter['count']}"}


def reset_call_counter() -> None:
    _call_counter["count"] = 0


def get_call_count() -> int:
    return _call_counter["count"]


_alternating_state = {"count": 0}


async def invoke_alternating_output(input: dict[str, Any]) -> dict[str, Any]:
    """Toggles "yes"/"no" by call parity. Regardless of the order trials
    actually complete in under concurrency, N calls from a freshly-reset
    counter always produce the same *multiset* of outputs (ceil(N/2)
    "yes", floor(N/2) "no") — which is what makes this fixture safe to
    use for deterministic majority-aggregation tests without depending
    on execution ordering."""
    _alternating_state["count"] += 1
    if _alternating_state["count"] % 2 == 1:
        return {"output": "yes"}
    return {"output": "no"}


def reset_alternating_state() -> None:
    _alternating_state["count"] = 0


_fail_second_state = {"count": 0}


async def invoke_with_reordered_tool_calls(input: dict[str, Any]) -> dict[str, Any]:
    """The exact same two tool calls as invoke_with_multiple_tool_calls,
    but in swapped order — Phase 17's tool-trajectory-order regression
    fixture: same multiset of tools, different sequence."""
    return {
        "output": "done",
        "tool_calls": [
            {"tool_name": "shell", "input": {"command": "rm -rf /"}, "output": "", "ok": True},
            {"tool_name": "search", "input": {"query": "weather"}, "output": "sunny", "ok": True},
        ],
    }


async def invoke_with_different_tool_args(input: dict[str, Any]) -> dict[str, Any]:
    """Calls the same tool as invoke_with_safe_tool_call ("search") but
    with different arguments — Phase 17's argument-change regression
    fixture."""
    return {
        "output": "done",
        "tool_calls": [
            {
                "tool_name": "search",
                "input": {"query": "a completely different query"},
                "output": "sunny",
                "ok": True,
            }
        ],
    }


def invoke_fail_on_second_call(input: dict[str, Any]) -> dict[str, Any]:
    """Succeeds on every call except the 2nd — proves one failing trial
    does not stop the remaining trials of the same TestCase."""
    _fail_second_state["count"] += 1
    if _fail_second_state["count"] == 2:
        raise RuntimeError("simulated failure on the second trial only")
    return {"output": "ok"}


def reset_fail_second_state() -> None:
    _fail_second_state["count"] = 0


# ---- Phase 18: latency fixture -----------------------------------------


async def invoke_slow(input: dict[str, Any]) -> dict[str, Any]:
    """Deliberately exceeds any small latency_threshold_ms a Phase 18
    test configures (e.g. 50ms) — proves the deterministic
    `latency_exceeded` RCA/hard-gate category fires from a real measured
    latency, not a synthetic one."""
    await asyncio.sleep(0.15)
    return {"output": "done"}


async def invoke_conditional_tool_call(input: dict[str, Any]) -> dict[str, Any]:
    """Calls an unsafe tool only when `input["unsafe"]` is true;
    otherwise returns a clean, tool-free response with the same output.
    Lets a single TestCase within an otherwise-clean SuiteRun (all cases
    share one AgentVersion/callable) independently trigger a hard-gate
    -eligible failure — proving a high pass rate cannot outvote it."""
    if input.get("unsafe"):
        return {
            "output": "done",
            "tool_calls": [
                {
                    "tool_name": "shell",
                    "input": {"command": "rm -rf /tmp/data"},
                    "output": "",
                    "ok": True,
                }
            ],
        }
    return {"output": "done"}
