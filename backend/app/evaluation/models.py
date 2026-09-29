"""Typed models for the Assertion Engine — the assertion/expected-tool
-call JSON formats a TestCase's `assertions`/`expected_tool_calls` JSONB
columns are interpreted as (app/models/test_case.py stores them as plain
JSONB; Phase 12 deliberately left their *internal* shape undefined —
this module is where Phase 13 defines it), plus the engine's own result
types.

None of these are persisted — Phase 14 will define its own
TestCaseResult persistence shape, informed by (but not identical to)
EvaluationResult below.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field

# ---- Assertion format ---------------------------------------------------
#
# One entry in TestCase.assertions, e.g.:
#   {"path": "$.status", "op": "equals", "value": "eligible"}
#   {"path": "$.rows", "op": "length_eq", "value": 5}
#   {"path": "$.confidence", "op": "gte", "value": 0.8}
#
# `path` addresses a location inside AgentExecution.output using the
# safe dotted/bracket syntax implemented in json_path.py — never a full
# JSONPath/jq expression language, and never evaluated as code. `path`
# of "$" or "" addresses the whole output value directly (useful when
# `output` is a plain string/scalar rather than an object).
#
# `op` is a bounded whitelist — nothing here can execute arbitrary code,
# call out to Python, or touch anything beyond the AgentExecution.output
# structure it's given.

AssertionOp = Literal[
    "exists",
    "equals",
    "not_equals",
    "contains",
    "not_contains",
    "gt",
    "gte",
    "lt",
    "lte",
    "length_eq",
]


class Assertion(BaseModel):
    path: str = Field(min_length=1)
    op: AssertionOp
    value: Any = None


# ---- Expected tool call format -------------------------------------
#
# One entry in TestCase.expected_tool_calls, e.g.:
#   {"tool": "check_order_eligibility", "order_index": 0}
#   {"tool": "issue_refund", "order_index": 1, "required": false,
#    "args_constraints": [{"path": "amount", "op": "lte", "value": 500}]}
#
# `args_constraints` reuses the exact same Assertion model above,
# resolved against the matching ToolCallRecord.input dict instead of
# AgentExecution.output — the smallest compatible schema decision
# available (see this module's own docstring / the Phase 13 report):
# one constraint language, two things it can be checked against.


class ExpectedToolCall(BaseModel):
    tool: str = Field(min_length=1)
    args_constraints: list[Assertion] | None = None
    order_index: int | None = None
    required: bool = True


# ---- Results ---------------------------------------------------------


class CheckStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    # A check that cannot be resolved deterministically at all (the
    # rubric check, always) — distinct from FAIL so a rubric-only case
    # is never reported as having failed anything.
    PENDING_LLM = "pending_llm"
    # Phase 15: the check was not applicable at all — no input existed to
    # evaluate it against (e.g. grounding with no TestCase.reference_context,
    # or tool-call safety at Observability Level 1, where tool calls simply
    # aren't observable). Never conflated with PASS: "not evaluated" is not
    # the same claim as "evaluated and found safe/grounded."
    SKIPPED = "skipped"
    # Phase 15: the check *was* applicable (its required input existed)
    # but a transient failure (e.g. the entailment model was unreachable)
    # left it genuinely undecided — distinct from SKIPPED (never
    # applicable) and from FAIL (applicable, evaluated, and failed).
    INCONCLUSIVE = "inconclusive"


class Determinism(str, Enum):
    DETERMINISTIC = "deterministic"
    REQUIRES_LLM = "requires_llm"


class Check(BaseModel):
    """One evaluated (or explicitly not-yet-evaluable) check — the unit
    a later phase's TestCaseResult.checks[] JSONB array is expected to
    store roughly one-to-one."""

    check_type: str
    status: CheckStatus
    determinism: Determinism
    detail: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class OverallVerdict(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    # No deterministic ground truth was applicable at all (e.g. a
    # rubric-only case) — deterministic evaluation is insufficient, not
    # a pass and not a failure. Phase 13 never fabricates INCONCLUSIVE
    # (that is a Phase 16 multi-trial concept); this is a distinct,
    # narrower state meaning "nothing deterministic to conclude from."
    REQUIRES_LLM = "requires_llm"


class EvaluationInput(BaseModel):
    """A framework-independent snapshot of the ground-truth fields
    engine.py needs from a TestCase — deliberately not the SQLAlchemy
    TestCase model itself, so the engine (and its unit tests) never
    depend on an ORM session/DB. engine.py's `from_test_case()` builds
    one of these from a real, persisted TestCase row; nothing else in
    this package imports app.models.test_case.

    `reference_context` is intentionally not evaluated here — grounding/
    faithfulness checking against it requires an LLM (Phase 15+), so
    Phase 13 only carries it through for completeness of the snapshot,
    unused by any check in this phase.
    """

    expected_output: str | None = None
    assertions: list[dict[str, Any]] | None = None
    reference_context: str | None = None
    expected_tool_calls: list[dict[str, Any]] | None = None
    allowed_tools: list[str] | None = None
    output_schema: dict[str, Any] | None = None
    latency_threshold_ms: int | None = None
    rubric: str | None = None


class EvaluationResult(BaseModel):
    verdict: OverallVerdict
    checks: list[Check]
    passed_count: int
    failed_count: int
    # True whenever the TestCase declares a rubric, independent of
    # `verdict` — a case can deterministically PASS/FAIL *and* still
    # need an LLM judge for its separate subjective criterion (Phase 19
    # consumes this flag; it never affects `verdict` itself).
    needs_llm_judge: bool
