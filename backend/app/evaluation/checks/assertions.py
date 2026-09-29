"""Deterministic evaluation of TestCase.assertions against
AgentExecution.output.

Each raw JSONB entry is parsed into app.evaluation.models.Assertion
(Pydantic validation against the bounded operator whitelist); a
malformed entry (missing/wrong-typed fields, an operator outside the
whitelist) produces its own FAIL check rather than raising — one bad
assertion never prevents the rest of the list, or any other check
family, from being evaluated.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from app.evaluation.json_path import InvalidPathError, resolve_path
from app.evaluation.models import Assertion, Check, CheckStatus, Determinism
from app.evaluation.operators import evaluate_operator


def check_assertions(raw_assertions: list[dict[str, Any]], actual_output: Any) -> list[Check]:
    checks: list[Check] = []
    for index, raw in enumerate(raw_assertions):
        checks.append(_check_one(index, raw, actual_output))
    return checks


def _check_one(index: int, raw: dict[str, Any], actual_output: Any) -> Check:
    check_type = f"assertion[{index}]"

    try:
        assertion = Assertion.model_validate(raw)
    except ValidationError as exc:
        return Check(
            check_type=check_type,
            status=CheckStatus.FAIL,
            determinism=Determinism.DETERMINISTIC,
            detail=f"malformed assertion: {exc.errors()[0]['msg'] if exc.errors() else exc}",
            metadata={"index": index, "raw": raw},
        )

    try:
        found, value = resolve_path(actual_output, assertion.path)
    except InvalidPathError as exc:
        return Check(
            check_type=check_type,
            status=CheckStatus.FAIL,
            determinism=Determinism.DETERMINISTIC,
            detail=f"invalid assertion path: {exc}",
            metadata={"index": index, "path": assertion.path, "op": assertion.op},
        )

    passed, detail = evaluate_operator(
        assertion.op, found=found, value=value, expected=assertion.value
    )
    return Check(
        check_type=check_type,
        status=CheckStatus.PASS if passed else CheckStatus.FAIL,
        determinism=Determinism.DETERMINISTIC,
        detail=detail,
        metadata={"index": index, "path": assertion.path, "op": assertion.op},
    )
