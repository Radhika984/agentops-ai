"""Deterministic comparison of AgentExecution.output against
TestCase.expected_output.

TestCase.expected_output is always a plain string (a TEXT column — see
app/models/test_case.py). The comparison strategy branches on the
*actual* output's type, not on guessing whether the expected string
"looks like JSON":

  - actual_output is a string/scalar -> normalized (whitespace-stripped)
    string equality against expected_output.
  - actual_output is a dict/list (structured) -> expected_output is
    parsed as JSON and compared for structural equality; if it isn't
    valid JSON, that's a deterministic FAIL (there's nothing meaningful
    to structurally compare against), not a silent string fallback.

No fuzzy/semantic matching, no LLM call.
"""

from __future__ import annotations

import json
from typing import Any

from app.evaluation.models import Check, CheckStatus, Determinism

CHECK_TYPE = "expected_output"


def check_expected_output(expected_output: str, actual_output: Any) -> Check:
    if actual_output is None:
        return Check(
            check_type=CHECK_TYPE,
            status=CheckStatus.FAIL,
            determinism=Determinism.DETERMINISTIC,
            detail="actual output is missing (the agent execution returned no output)",
        )

    if isinstance(actual_output, dict | list):
        try:
            parsed_expected = json.loads(expected_output)
        except ValueError:
            return Check(
                check_type=CHECK_TYPE,
                status=CheckStatus.FAIL,
                determinism=Determinism.DETERMINISTIC,
                detail=(
                    "actual output is structured (object/array) but expected_output "
                    "is not valid JSON to structurally compare against"
                ),
            )
        if parsed_expected == actual_output:
            return Check(
                check_type=CHECK_TYPE,
                status=CheckStatus.PASS,
                determinism=Determinism.DETERMINISTIC,
                detail="actual output structurally equals expected_output",
            )
        return Check(
            check_type=CHECK_TYPE,
            status=CheckStatus.FAIL,
            determinism=Determinism.DETERMINISTIC,
            detail=f"structural mismatch: expected {parsed_expected!r}, got {actual_output!r}",
        )

    actual_text = actual_output if isinstance(actual_output, str) else str(actual_output)
    if actual_text.strip() == expected_output.strip():
        return Check(
            check_type=CHECK_TYPE,
            status=CheckStatus.PASS,
            determinism=Determinism.DETERMINISTIC,
            detail="actual output matches expected_output",
        )
    return Check(
        check_type=CHECK_TYPE,
        status=CheckStatus.FAIL,
        determinism=Determinism.DETERMINISTIC,
        detail=f"mismatch: expected {expected_output.strip()!r}, got {actual_text.strip()!r}",
    )
