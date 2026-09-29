"""Deterministic JSON Schema validation of AgentExecution.output against
TestCase.output_schema, via the standard `jsonschema` library (Draft
2020-12 validator, auto-detected from the schema's own `$schema` keyword
when present) — purely declarative schema checking, never an LLM
"judge" of structure.
"""

from __future__ import annotations

from typing import Any

import jsonschema

from app.evaluation.models import Check, CheckStatus, Determinism

CHECK_TYPE = "output_schema"


def check_output_schema(output_schema: dict[str, Any], actual_output: Any) -> Check:
    if actual_output is None:
        return Check(
            check_type=CHECK_TYPE,
            status=CheckStatus.FAIL,
            determinism=Determinism.DETERMINISTIC,
            detail="actual output is missing; cannot validate against output_schema",
        )

    try:
        validator_cls = jsonschema.validators.validator_for(output_schema)
        validator_cls.check_schema(output_schema)
    except jsonschema.exceptions.SchemaError as exc:
        return Check(
            check_type=CHECK_TYPE,
            status=CheckStatus.FAIL,
            determinism=Determinism.DETERMINISTIC,
            detail=f"output_schema itself is not a valid JSON Schema: {exc.message}",
        )

    validator = validator_cls(output_schema)
    errors = sorted(validator.iter_errors(actual_output), key=lambda e: e.path)
    if not errors:
        return Check(
            check_type=CHECK_TYPE,
            status=CheckStatus.PASS,
            determinism=Determinism.DETERMINISTIC,
            detail="actual output conforms to output_schema",
        )

    first = errors[0]
    location = "/".join(str(p) for p in first.path) or "<root>"
    return Check(
        check_type=CHECK_TYPE,
        status=CheckStatus.FAIL,
        determinism=Determinism.DETERMINISTIC,
        detail=f"schema validation failed at {location}: {first.message}",
        metadata={"error_count": len(errors)},
    )
