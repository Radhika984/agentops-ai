"""Deterministic evaluation of TestCase.expected_tool_calls /
allowed_tools against the real AgentExecution.tool_calls the connected
agent actually reported — reusing app.adapters.execution.ToolCallRecord
directly (Phase 10's own structure), never a parallel ToolCall
representation.

Per the locked audit, tool-trajectory checks only ever run against
`tool_calls` the agent's adapter actually returned — an agent registered
at Observability Level 1 (black box) never has `tool_calls` populated
(app.adapters — envelope convention), so `expected_tool_calls`
requirements against it will correctly, deterministically FAIL as
"missing" rather than fabricate a pass; the engine never inspects an
AgentVersion's observability_level itself (Phase 11 concern) — it just
evaluates whatever tool_calls list it is actually given.

An empty `expected_tool_calls` list (`[]`) is treated as "no tool
-trajectory requirement" — identical to it being unset — never as "zero
tool calls required."
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from app.adapters.execution import ToolCallRecord
from app.evaluation.json_path import InvalidPathError, resolve_path
from app.evaluation.models import Check, CheckStatus, Determinism, ExpectedToolCall
from app.evaluation.operators import evaluate_operator


def check_tool_trajectory(
    raw_expected_tool_calls: list[dict[str, Any]] | None,
    allowed_tools: list[str] | None,
    actual_tool_calls: list[ToolCallRecord],
) -> list[Check]:
    checks: list[Check] = []

    if raw_expected_tool_calls:
        parsed: list[tuple[int, ExpectedToolCall]] = []
        for index, raw in enumerate(raw_expected_tool_calls):
            try:
                parsed.append((index, ExpectedToolCall.model_validate(raw)))
            except ValidationError as exc:
                checks.append(
                    Check(
                        check_type=f"expected_tool_call[{index}]",
                        status=CheckStatus.FAIL,
                        determinism=Determinism.DETERMINISTIC,
                        detail=(
                            "malformed expected tool call specification: "
                            f"{exc.errors()[0]['msg'] if exc.errors() else exc}"
                        ),
                        metadata={"index": index, "raw": raw},
                    )
                )

        for index, expected in parsed:
            checks.append(_check_single_call(index, expected, actual_tool_calls))

        ordered = [(i, e) for i, e in parsed if e.order_index is not None]
        if len(ordered) >= 2:
            checks.append(_check_ordering(ordered, actual_tool_calls))

    if allowed_tools:
        checks.append(_check_forbidden_tools(allowed_tools, actual_tool_calls))

    return checks


def _matching_calls(tool_name: str, actual: list[ToolCallRecord]) -> list[ToolCallRecord]:
    return [tc for tc in actual if tc.tool_name == tool_name]


def _check_single_call(
    index: int, expected: ExpectedToolCall, actual: list[ToolCallRecord]
) -> Check:
    check_type = f"tool_call[{index}]:{expected.tool}"
    candidates = _matching_calls(expected.tool, actual)

    if not candidates:
        if expected.required:
            return Check(
                check_type=check_type,
                status=CheckStatus.FAIL,
                determinism=Determinism.DETERMINISTIC,
                detail=f"missing required tool call: '{expected.tool}' was never called",
                metadata={"tool": expected.tool},
            )
        return Check(
            check_type=check_type,
            status=CheckStatus.PASS,
            determinism=Determinism.DETERMINISTIC,
            detail=f"optional tool call '{expected.tool}' was not made (not required)",
            metadata={"tool": expected.tool},
        )

    if not expected.args_constraints:
        return Check(
            check_type=check_type,
            status=CheckStatus.PASS,
            determinism=Determinism.DETERMINISTIC,
            detail=f"required tool call '{expected.tool}' was made",
            metadata={"tool": expected.tool},
        )

    for candidate in candidates:
        ok, _ = _check_args_constraints(candidate, expected.args_constraints)
        if ok:
            return Check(
                check_type=check_type,
                status=CheckStatus.PASS,
                determinism=Determinism.DETERMINISTIC,
                detail=f"tool call '{expected.tool}' matched with satisfying arguments",
                metadata={"tool": expected.tool},
            )

    _, reason = _check_args_constraints(candidates[-1], expected.args_constraints)
    return Check(
        check_type=check_type,
        status=CheckStatus.FAIL,
        determinism=Determinism.DETERMINISTIC,
        detail=f"tool '{expected.tool}' was called, but no call satisfied its argument "
        f"constraints (last attempt: {reason})",
        metadata={"tool": expected.tool},
    )


def _check_args_constraints(call: ToolCallRecord, constraints: list[Any]) -> tuple[bool, str]:
    for constraint in constraints:
        try:
            found, value = resolve_path(call.input, constraint.path)
        except InvalidPathError as exc:
            return False, f"invalid path {constraint.path!r}: {exc}"
        passed, detail = evaluate_operator(
            constraint.op, found=found, value=value, expected=constraint.value
        )
        if not passed:
            return False, detail
    return True, "all argument constraints satisfied"


def _check_ordering(
    ordered_expected: list[tuple[int, ExpectedToolCall]], actual: list[ToolCallRecord]
) -> Check:
    ordered_sorted = sorted(ordered_expected, key=lambda pair: pair[1].order_index or 0)

    positions: list[tuple[str, int]] = []
    for _, expected in ordered_sorted:
        candidates = _matching_calls(expected.tool, actual)
        if candidates:
            # Earliest actual occurrence — the first time the expected
            # tool was called establishes its place in the trajectory.
            first_index = min(actual.index(c) for c in candidates)
            positions.append((expected.tool, first_index))

    is_ordered = all(
        positions[i][1] <= positions[i + 1][1] for i in range(len(positions) - 1)
    )
    order_desc = " -> ".join(name for name, _ in positions)

    if is_ordered:
        return Check(
            check_type="tool_call_order",
            status=CheckStatus.PASS,
            determinism=Determinism.DETERMINISTIC,
            detail=f"tool calls occurred in the expected relative order: {order_desc}",
        )
    return Check(
        check_type="tool_call_order",
        status=CheckStatus.FAIL,
        determinism=Determinism.DETERMINISTIC,
        detail=f"tool calls did not occur in the expected relative order: {order_desc}",
    )


def _check_forbidden_tools(allowed_tools: list[str], actual: list[ToolCallRecord]) -> Check:
    allowed = set(allowed_tools)
    forbidden_calls = [tc.tool_name for tc in actual if tc.tool_name not in allowed]

    if forbidden_calls:
        return Check(
            check_type="forbidden_tool_calls",
            status=CheckStatus.FAIL,
            determinism=Determinism.DETERMINISTIC,
            detail=f"forbidden tool call(s) made: {', '.join(sorted(set(forbidden_calls)))}",
            metadata={"forbidden": sorted(set(forbidden_calls))},
        )
    return Check(
        check_type="forbidden_tool_calls",
        status=CheckStatus.PASS,
        determinism=Determinism.DETERMINISTIC,
        detail="no tool calls outside the allowed list were made",
    )
