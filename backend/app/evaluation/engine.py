"""The Assertion Engine orchestrator.

    AgentAdapter -> AgentExecution -> [evaluate()] -> EvaluationResult

`evaluate()` never calls an AgentAdapter (it is handed an AgentExecution
that already exists — see this package's own docstring) and never calls
an LLM. Every check family below is invoked only when its corresponding
TestCase field is actually set — an unset field means "not applicable,"
never "fails" or "passes by default." All applicable checks are
evaluated (no short-circuiting on the first failure); a malformed
individual assertion/expected-tool-call entry is isolated to its own
FAIL check by the check modules themselves, so it never prevents other,
well-formed checks from running.

Neither the TestCase nor the AgentExecution passed in is ever mutated —
both are only read from; AgentExecution is a frozen Pydantic model
(app/adapters/execution.py) and this module never calls setattr on the
TestCase ORM object either.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.adapters.execution import AgentExecution
from app.evaluation.checks.assertions import check_assertions
from app.evaluation.checks.expected_output import check_expected_output
from app.evaluation.checks.latency import check_latency
from app.evaluation.checks.output_schema import check_output_schema
from app.evaluation.checks.tool_trajectory import check_tool_trajectory
from app.evaluation.models import (
    Check,
    CheckStatus,
    Determinism,
    EvaluationInput,
    EvaluationResult,
    OverallVerdict,
)

if TYPE_CHECKING:
    from app.models.test_case import TestCase


def from_test_case(test_case: TestCase) -> EvaluationInput:
    """Builds a framework-independent EvaluationInput from a persisted
    TestCase row. Read-only — never mutates `test_case`."""
    return EvaluationInput(
        expected_output=test_case.expected_output,
        assertions=test_case.assertions,
        reference_context=test_case.reference_context,
        expected_tool_calls=test_case.expected_tool_calls,
        allowed_tools=test_case.allowed_tools,
        output_schema=test_case.output_schema,
        latency_threshold_ms=test_case.latency_threshold_ms,
        rubric=test_case.rubric,
    )


def evaluate(test_case: EvaluationInput, execution: AgentExecution) -> EvaluationResult:
    checks: list[Check] = []

    if test_case.expected_output:
        checks.append(check_expected_output(test_case.expected_output, execution.output))

    if test_case.assertions:
        checks.extend(check_assertions(test_case.assertions, execution.output))

    if test_case.expected_tool_calls or test_case.allowed_tools:
        checks.extend(
            check_tool_trajectory(
                test_case.expected_tool_calls, test_case.allowed_tools, execution.tool_calls
            )
        )

    if test_case.output_schema:
        checks.append(check_output_schema(test_case.output_schema, execution.output))

    if test_case.latency_threshold_ms:
        checks.append(check_latency(test_case.latency_threshold_ms, execution.latency_ms))

    needs_llm_judge = bool(test_case.rubric)
    if test_case.rubric:
        checks.append(
            Check(
                check_type="rubric",
                status=CheckStatus.PENDING_LLM,
                determinism=Determinism.REQUIRES_LLM,
                detail=(
                    "subjective rubric criterion — deterministic evaluation does not "
                    "apply; an LLM judge is required (Phase 19), not invoked here"
                ),
            )
        )

    deterministic_checks = [c for c in checks if c.determinism == Determinism.DETERMINISTIC]
    passed_count = sum(1 for c in deterministic_checks if c.status == CheckStatus.PASS)
    failed_count = sum(1 for c in deterministic_checks if c.status == CheckStatus.FAIL)

    if not deterministic_checks:
        # No deterministic ground truth was applicable at all (e.g. a
        # rubric-only case) — deterministic evaluation is insufficient
        # to conclude anything. Never fabricated as PASS or FAIL.
        verdict = OverallVerdict.REQUIRES_LLM
    elif failed_count > 0:
        verdict = OverallVerdict.FAIL
    else:
        verdict = OverallVerdict.PASS

    return EvaluationResult(
        verdict=verdict,
        checks=checks,
        passed_count=passed_count,
        failed_count=failed_count,
        needs_llm_judge=needs_llm_judge,
    )


__all__ = ["AgentExecution", "EvaluationInput", "EvaluationResult", "evaluate", "from_test_case"]
