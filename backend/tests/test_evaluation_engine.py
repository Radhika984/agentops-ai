"""Phase 13 — Assertion Engine unit tests.

Pure-Python, no DB, no HTTP, no LLM, no AgentAdapter — evaluate() is
exercised directly against hand-built AgentExecution/EvaluationInput
values, exactly matching the locked separation:

    AgentAdapter -> AgentExecution -> evaluate() -> EvaluationResult
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from app.adapters.execution import AgentExecution, ToolCallRecord
from app.evaluation.checks.latency import check_latency
from app.evaluation.engine import evaluate, from_test_case
from app.evaluation.models import (
    CheckStatus,
    Determinism,
    EvaluationInput,
    OverallVerdict,
)


def _execution(
    *,
    output: object = None,
    tool_calls: list[ToolCallRecord] | None = None,
    latency_ms: int = 100,
    status: str = "ok",
) -> AgentExecution:
    now = datetime.now(UTC)
    return AgentExecution(
        request_id=uuid.uuid4(),
        input={"question": "test"},
        output=output,
        status=status,  # type: ignore[arg-type]
        error=None,
        latency_ms=latency_ms,
        started_at=now,
        finished_at=now,
        tool_calls=tool_calls or [],
    )


def _case(**overrides: object) -> EvaluationInput:
    return EvaluationInput.model_validate(overrides)


# ---- Expected output --------------------------------------------------


def test_expected_output_exact_string_match() -> None:
    result = evaluate(_case(expected_output="hello world"), _execution(output="hello world"))
    assert result.verdict == OverallVerdict.PASS
    assert result.checks[0].status == CheckStatus.PASS


def test_expected_output_mismatch() -> None:
    result = evaluate(_case(expected_output="hello world"), _execution(output="goodbye"))
    assert result.verdict == OverallVerdict.FAIL
    assert result.checks[0].status == CheckStatus.FAIL


def test_expected_output_structured_json_equality() -> None:
    result = evaluate(
        _case(expected_output='{"status": "eligible", "amount": 50}'),
        _execution(output={"status": "eligible", "amount": 50}),
    )
    assert result.verdict == OverallVerdict.PASS


def test_expected_output_structured_json_mismatch() -> None:
    result = evaluate(
        _case(expected_output='{"status": "eligible"}'),
        _execution(output={"status": "ineligible"}),
    )
    assert result.verdict == OverallVerdict.FAIL


def test_expected_output_missing_actual_output_is_fail_not_pass() -> None:
    result = evaluate(_case(expected_output="hello"), _execution(output=None))
    assert result.verdict == OverallVerdict.FAIL
    assert "missing" in result.checks[0].detail


# ---- Assertions --------------------------------------------------------


def test_assertion_field_exists() -> None:
    result = evaluate(
        _case(assertions=[{"path": "$.status", "op": "exists"}]),
        _execution(output={"status": "eligible"}),
    )
    assert result.verdict == OverallVerdict.PASS


def test_assertion_field_does_not_exist() -> None:
    result = evaluate(
        _case(assertions=[{"path": "$.missing_field", "op": "exists"}]),
        _execution(output={"status": "eligible"}),
    )
    assert result.verdict == OverallVerdict.FAIL


def test_assertion_equality() -> None:
    result = evaluate(
        _case(assertions=[{"path": "$.status", "op": "equals", "value": "eligible"}]),
        _execution(output={"status": "eligible"}),
    )
    assert result.verdict == OverallVerdict.PASS


def test_assertion_inequality() -> None:
    result = evaluate(
        _case(assertions=[{"path": "$.status", "op": "not_equals", "value": "denied"}]),
        _execution(output={"status": "eligible"}),
    )
    assert result.verdict == OverallVerdict.PASS


def test_assertion_contains() -> None:
    result = evaluate(
        _case(assertions=[{"path": "$.message", "op": "contains", "value": "refund"}]),
        _execution(output={"message": "your refund has been approved"}),
    )
    assert result.verdict == OverallVerdict.PASS


def test_assertion_not_contains_fails_when_present() -> None:
    result = evaluate(
        _case(assertions=[{"path": "$.message", "op": "not_contains", "value": "denied"}]),
        _execution(output={"message": "your request was denied"}),
    )
    assert result.verdict == OverallVerdict.FAIL


def test_assertion_numeric_gt_gte_lt_lte() -> None:
    output = {"confidence": 0.85}
    for op, threshold, expected_pass in [
        ("gt", 0.8, True),
        ("gt", 0.9, False),
        ("gte", 0.85, True),
        ("lt", 0.9, True),
        ("lte", 0.85, True),
        ("lte", 0.8, False),
    ]:
        result = evaluate(
            _case(assertions=[{"path": "$.confidence", "op": op, "value": threshold}]),
            _execution(output=output),
        )
        assert (result.verdict == OverallVerdict.PASS) is expected_pass, op


def test_assertion_numeric_comparison_against_non_numeric_fails() -> None:
    result = evaluate(
        _case(assertions=[{"path": "$.status", "op": "gt", "value": 5}]),
        _execution(output={"status": "eligible"}),
    )
    assert result.verdict == OverallVerdict.FAIL


def test_assertion_list_length() -> None:
    result = evaluate(
        _case(assertions=[{"path": "$.rows", "op": "length_eq", "value": 5}]),
        _execution(output={"rows": [1, 2, 3, 4, 5]}),
    )
    assert result.verdict == OverallVerdict.PASS


def test_assertion_list_length_mismatch() -> None:
    result = evaluate(
        _case(assertions=[{"path": "$.rows", "op": "length_eq", "value": 5}]),
        _execution(output={"rows": [1, 2]}),
    )
    assert result.verdict == OverallVerdict.FAIL


def test_assertion_nested_path() -> None:
    result = evaluate(
        _case(assertions=[{"path": "$.order.customer.name", "op": "equals", "value": "Jane"}]),
        _execution(output={"order": {"customer": {"name": "Jane"}}}),
    )
    assert result.verdict == OverallVerdict.PASS


def test_assertion_nested_path_with_list_index() -> None:
    result = evaluate(
        _case(assertions=[{"path": "$.rows[0].id", "op": "equals", "value": 42}]),
        _execution(output={"rows": [{"id": 42}, {"id": 43}]}),
    )
    assert result.verdict == OverallVerdict.PASS


def test_multiple_assertions_all_evaluated_independently() -> None:
    result = evaluate(
        _case(
            assertions=[
                {"path": "$.status", "op": "equals", "value": "eligible"},
                {"path": "$.amount", "op": "gte", "value": 1000},  # will fail
            ]
        ),
        _execution(output={"status": "eligible", "amount": 50}),
    )
    assert result.verdict == OverallVerdict.FAIL
    assert len(result.checks) == 2
    assert result.checks[0].status == CheckStatus.PASS
    assert result.checks[1].status == CheckStatus.FAIL
    assert result.passed_count == 1
    assert result.failed_count == 1


def test_malformed_assertion_missing_op_is_fail_not_crash() -> None:
    result = evaluate(
        _case(assertions=[{"path": "$.status"}]),
        _execution(output={"status": "eligible"}),
    )
    assert result.verdict == OverallVerdict.FAIL
    assert result.checks[0].status == CheckStatus.FAIL
    assert "malformed" in result.checks[0].detail


def test_unsupported_operator_is_rejected_as_malformed() -> None:
    result = evaluate(
        _case(assertions=[{"path": "$.status", "op": "regex", "value": ".*"}]),
        _execution(output={"status": "eligible"}),
    )
    assert result.verdict == OverallVerdict.FAIL
    assert result.checks[0].status == CheckStatus.FAIL


def test_arbitrary_code_operator_is_rejected_never_executed() -> None:
    marker_file = Path(__file__).parent / "_should_never_be_created.tmp"
    marker_file.unlink(missing_ok=True)
    try:
        result = evaluate(
            _case(
                assertions=[
                    {
                        "path": "$.status",
                        "op": "eval",
                        "value": f"__import__('pathlib').Path({str(marker_file)!r}).touch()",
                    }
                ]
            ),
            _execution(output={"status": "eligible"}),
        )
        assert result.verdict == OverallVerdict.FAIL
        assert not marker_file.exists()
    finally:
        marker_file.unlink(missing_ok=True)


# ---- Tool calls --------------------------------------------------------


def _tool_call(name: str, ok: bool = True, **input_kwargs: object) -> ToolCallRecord:
    return ToolCallRecord(tool_name=name, input=input_kwargs, output="ok", ok=ok)


def test_required_tool_call_present() -> None:
    result = evaluate(
        _case(expected_tool_calls=[{"tool": "check_order_eligibility"}]),
        _execution(tool_calls=[_tool_call("check_order_eligibility")]),
    )
    assert result.verdict == OverallVerdict.PASS


def test_required_tool_call_missing() -> None:
    result = evaluate(
        _case(expected_tool_calls=[{"tool": "check_order_eligibility"}]),
        _execution(tool_calls=[]),
    )
    assert result.verdict == OverallVerdict.FAIL
    assert "missing required tool call" in result.checks[0].detail


def test_forbidden_tool_call_present() -> None:
    result = evaluate(
        _case(allowed_tools=["check_order_eligibility"]),
        _execution(
            tool_calls=[_tool_call("check_order_eligibility"), _tool_call("delete_account")]
        ),
    )
    assert result.verdict == OverallVerdict.FAIL
    assert "forbidden" in result.checks[-1].detail
    assert "delete_account" in result.checks[-1].detail


def test_no_forbidden_tool_call() -> None:
    result = evaluate(
        _case(allowed_tools=["check_order_eligibility"]),
        _execution(tool_calls=[_tool_call("check_order_eligibility")]),
    )
    assert result.verdict == OverallVerdict.PASS


def test_expected_tool_call_order_passes() -> None:
    result = evaluate(
        _case(
            expected_tool_calls=[
                {"tool": "check_order_eligibility", "order_index": 0},
                {"tool": "issue_refund", "order_index": 1},
            ]
        ),
        _execution(tool_calls=[_tool_call("check_order_eligibility"), _tool_call("issue_refund")]),
    )
    assert result.verdict == OverallVerdict.PASS


def test_expected_tool_call_order_fails() -> None:
    result = evaluate(
        _case(
            expected_tool_calls=[
                {"tool": "check_order_eligibility", "order_index": 0},
                {"tool": "issue_refund", "order_index": 1},
            ]
        ),
        _execution(tool_calls=[_tool_call("issue_refund"), _tool_call("check_order_eligibility")]),
    )
    assert result.verdict == OverallVerdict.FAIL
    order_check = next(c for c in result.checks if c.check_type == "tool_call_order")
    assert order_check.status == CheckStatus.FAIL


def test_malformed_expected_tool_call_specification() -> None:
    result = evaluate(
        _case(expected_tool_calls=[{"not_a_tool_field": "x"}]),
        _execution(tool_calls=[]),
    )
    assert result.verdict == OverallVerdict.FAIL
    assert "malformed" in result.checks[0].detail


def test_empty_expected_tool_calls_list_is_not_a_requirement() -> None:
    result = evaluate(_case(expected_tool_calls=[], expected_output="hi"), _execution(output="hi"))
    assert result.verdict == OverallVerdict.PASS
    assert len(result.checks) == 1  # only expected_output — no tool check emitted


def test_tool_call_argument_constraint() -> None:
    result = evaluate(
        _case(
            expected_tool_calls=[
                {
                    "tool": "issue_refund",
                    "args_constraints": [{"path": "amount", "op": "lte", "value": 100}],
                }
            ]
        ),
        _execution(tool_calls=[_tool_call("issue_refund", amount=50)]),
    )
    assert result.verdict == OverallVerdict.PASS


def test_tool_call_argument_constraint_failing() -> None:
    result = evaluate(
        _case(
            expected_tool_calls=[
                {
                    "tool": "issue_refund",
                    "args_constraints": [{"path": "amount", "op": "lte", "value": 100}],
                }
            ]
        ),
        _execution(tool_calls=[_tool_call("issue_refund", amount=5000)]),
    )
    assert result.verdict == OverallVerdict.FAIL


# ---- Output schema -------------------------------------------------


_STATUS_OBJECT_SCHEMA = {
    "type": "object",
    "required": ["status"],
    "properties": {"status": {"type": "string"}},
}


def test_schema_valid_output() -> None:
    result = evaluate(
        _case(output_schema=_STATUS_OBJECT_SCHEMA), _execution(output={"status": "eligible"})
    )
    assert result.verdict == OverallVerdict.PASS


def test_schema_invalid_output() -> None:
    result = evaluate(_case(output_schema=_STATUS_OBJECT_SCHEMA), _execution(output={"other": 1}))
    assert result.verdict == OverallVerdict.FAIL


def test_schema_malformed_schema_does_not_silently_pass() -> None:
    malformed_schema = {"type": "not-a-real-json-schema-type"}
    result = evaluate(_case(output_schema=malformed_schema), _execution(output={"a": 1}))
    assert result.verdict == OverallVerdict.FAIL
    assert "not a valid JSON Schema" in result.checks[0].detail


# ---- Latency -------------------------------------------------------


def test_latency_within_threshold() -> None:
    result = evaluate(_case(latency_threshold_ms=1000), _execution(latency_ms=500))
    assert result.verdict == OverallVerdict.PASS


def test_latency_over_threshold() -> None:
    result = evaluate(_case(latency_threshold_ms=1000), _execution(latency_ms=5000))
    assert result.verdict == OverallVerdict.FAIL


def test_latency_missing_does_not_pass() -> None:
    check = check_latency(1000, None)
    assert check.status == CheckStatus.FAIL


def test_no_latency_check_when_no_threshold_configured() -> None:
    result = evaluate(_case(expected_output="hi"), _execution(output="hi", latency_ms=999_999))
    assert not any(c.check_type == "latency" for c in result.checks)


# ---- Rubric boundary -------------------------------------------------


def test_rubric_only_case_requires_llm_not_pass_not_fail() -> None:
    result = evaluate(
        _case(rubric="Is the tone empathetic?"), _execution(output="Sure, happy to help!")
    )
    assert result.verdict == OverallVerdict.REQUIRES_LLM
    assert result.needs_llm_judge is True
    rubric_check = next(c for c in result.checks if c.check_type == "rubric")
    assert rubric_check.status == CheckStatus.PENDING_LLM
    assert rubric_check.determinism == Determinism.REQUIRES_LLM


def test_rubric_only_case_is_never_pass() -> None:
    result = evaluate(_case(rubric="anything"), _execution(output="anything"))
    assert result.verdict != OverallVerdict.PASS


def test_rubric_only_case_is_never_fail() -> None:
    result = evaluate(_case(rubric="anything"), _execution(output=None))  # even with no output
    assert result.verdict != OverallVerdict.FAIL


# ---- Combined checks -------------------------------------------------


def test_all_deterministic_checks_pass() -> None:
    result = evaluate(
        _case(
            expected_output="Refund approved",
            expected_tool_calls=[{"tool": "check_order_eligibility"}],
            output_schema={"type": "string"},
            latency_threshold_ms=1000,
        ),
        _execution(
            output="Refund approved",
            tool_calls=[_tool_call("check_order_eligibility")],
            latency_ms=200,
        ),
    )
    assert result.verdict == OverallVerdict.PASS
    assert result.failed_count == 0
    assert result.passed_count == len(result.checks)


def test_one_check_fails_among_several() -> None:
    result = evaluate(
        _case(expected_output="Refund approved", latency_threshold_ms=100),
        _execution(output="Refund approved", latency_ms=5000),
    )
    assert result.verdict == OverallVerdict.FAIL
    assert result.passed_count == 1
    assert result.failed_count == 1


def test_multiple_checks_fail() -> None:
    result = evaluate(
        _case(expected_output="Refund approved", latency_threshold_ms=100),
        _execution(output="wrong answer", latency_ms=5000),
    )
    assert result.verdict == OverallVerdict.FAIL
    assert result.failed_count == 2


def test_deterministic_pass_plus_rubric_still_needs_llm_judge() -> None:
    result = evaluate(
        _case(expected_output="Refund approved", rubric="Is the tone empathetic?"),
        _execution(output="Refund approved"),
    )
    assert result.verdict == OverallVerdict.PASS  # deterministic portion passed
    assert result.needs_llm_judge is True  # but the rubric still needs a judge later


# ---- Security -------------------------------------------------------


def test_no_eval_exec_or_shell_execution_in_evaluation_package_source() -> None:
    """A structural guarantee, not just behavioral: the whole package is
    scanned for the specific dangerous constructs the locked brief
    prohibits, so a future edit can't quietly reintroduce one."""
    forbidden_substrings = ["eval(", "exec(", "subprocess", "os.system", "__import__"]
    package_dir = Path(__file__).resolve().parent.parent / "app" / "evaluation"
    offending: list[str] = []
    for path in package_dir.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for needle in forbidden_substrings:
            if needle in text:
                offending.append(f"{path.name}: {needle!r}")
    assert offending == []


def test_engine_does_not_mutate_agent_execution() -> None:
    execution = _execution(output={"status": "eligible"})
    before = execution.model_dump(mode="json")
    evaluate(_case(expected_output='{"status": "eligible"}'), execution)
    assert execution.model_dump(mode="json") == before


def test_from_test_case_does_not_mutate_the_test_case() -> None:
    fake_test_case = SimpleNamespace(
        expected_output="hi",
        assertions=None,
        reference_context=None,
        expected_tool_calls=None,
        allowed_tools=None,
        output_schema=None,
        latency_threshold_ms=None,
        rubric=None,
    )
    before = dict(vars(fake_test_case))

    evaluation_input = from_test_case(fake_test_case)  # type: ignore[arg-type]

    assert dict(vars(fake_test_case)) == before
    assert evaluation_input.expected_output == "hi"
