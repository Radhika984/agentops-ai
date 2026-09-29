"""The bounded operator whitelist shared by both assertion evaluation
(checks/assertions.py, against AgentExecution.output) and tool-call
argument constraints (checks/tool_trajectory.py, against a
ToolCallRecord.input) — one evaluation core, reused, not duplicated.

Every operator here is a plain, declarative comparison over already
-resolved Python values. Nothing in this module executes a string as
code, calls a user-supplied function, or does anything beyond
`==`/`!=`/`in`/`<`/`len()` — the bounded whitelist the locked Phase 13
brief requires.
"""

from __future__ import annotations

from typing import Any

from app.evaluation.models import AssertionOp


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _contains(container: Any, needle: Any) -> bool:
    if isinstance(container, str):
        return isinstance(needle, str) and needle in container
    if isinstance(container, list | tuple | set):
        return needle in container
    if isinstance(container, dict):
        return needle in container.values() or needle in container
    raise TypeError(f"'contains' is not supported for values of type {type(container).__name__}")


def evaluate_operator(
    op: AssertionOp, *, found: bool, value: Any, expected: Any
) -> tuple[bool, str]:
    """Evaluates one operator against an already-resolved (found, value)
    pair. Returns (passed, detail). Never raises for a legitimate
    comparison that simply fails or doesn't apply to the value's type —
    those are reported as `(False, "<reason>")`, exactly like any other
    deterministic failure, never as an exception."""

    if op == "exists":
        return found, ("path exists" if found else "path not found")

    if not found:
        return False, "path not found"

    if op == "equals":
        return value == expected, f"{value!r} == {expected!r}"
    if op == "not_equals":
        return value != expected, f"{value!r} != {expected!r}"

    if op in ("contains", "not_contains"):
        try:
            membership = _contains(value, expected)
        except TypeError as exc:
            return False, str(exc)
        passed = membership if op == "contains" else not membership
        return passed, f"{expected!r} {'in' if op == 'contains' else 'not in'} {value!r}"

    if op in ("gt", "gte", "lt", "lte"):
        if not _is_number(value) or not _is_number(expected):
            return False, (
                f"'{op}' requires numeric values, got {type(value).__name__} "
                f"and {type(expected).__name__}"
            )
        comparisons = {
            "gt": value > expected,
            "gte": value >= expected,
            "lt": value < expected,
            "lte": value <= expected,
        }
        return comparisons[op], f"{value!r} {op} {expected!r}"

    if op == "length_eq":
        try:
            length = len(value)
        except TypeError:
            return False, f"'length_eq' requires a sized value, got {type(value).__name__}"
        return length == expected, f"len({value!r}) == {expected!r} (actual length {length})"

    # Unreachable given AssertionOp's Literal type — kept as an explicit,
    # safe fallback rather than an assert, since `op` may originate from
    # data that bypassed Pydantic validation in a future caller.
    return False, f"unsupported operator: {op!r}"
