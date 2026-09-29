from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class TestSuiteCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class TestSuiteRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    agent_id: uuid.UUID
    name: str
    created_at: datetime
    updated_at: datetime


# ---- Test Case -----------------------------------------------------
#
# Field semantics (locked audit §9 / this phase's exact spec) — storage
# only, nothing here is executed:
#   expected_output      -> concrete expected result
#   assertions            -> deterministic checks (Phase 13 executes these)
#   reference_context      -> grounding/source context (Phase 13+ grounding check)
#   expected_tool_calls    -> expected tool trajectory (Phase 13+ tool check)
#   expected_behavior      -> behavioral requirement (informational, §8)
#   forbidden_behavior     -> prohibited behavior (informational, §8)
#   output_schema          -> structural output requirement (Phase 13 schema check)
#   latency_threshold_ms   -> performance requirement (Phase 13 performance check)
#   rubric                 -> subjective criteria (Phase 19 optional LLM judge)
#   trial_count             -> repeated execution count (Phase 16)
#
# At least one of expected_output / assertions / reference_context /
# expected_tool_calls / output_schema / rubric is required — enforced in
# app/services/test_suite_service.py, not here (Pydantic validates
# per-field shape; the cross-field "at least one" rule is a domain rule,
# and must also re-run on PATCH against the *merged* resulting case, which
# only the service has enough context to compute).


class TestCaseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    input: dict[str, Any]
    history: list[dict[str, Any]] | None = None

    reference_context: str | None = None
    expected_output: str | None = None
    assertions: list[dict[str, Any]] | None = None
    expected_tool_calls: list[dict[str, Any]] | None = None
    rubric: str | None = None

    expected_behavior: list[str] | None = None
    forbidden_behavior: list[str] | None = None
    allowed_tools: list[str] | None = None
    output_schema: dict[str, Any] | None = None
    latency_threshold_ms: int | None = Field(default=None, gt=0)

    rubric_threshold: float = Field(default=0.7, ge=0.0, le=1.0)
    trial_count: int = Field(default=1, ge=1)

    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class TestCasePatch(BaseModel):
    """All fields optional — app/services/test_suite_service.py applies
    only the ones present in `model_fields_set`, matching
    schemas/agent.py's AgentUpdate convention, then revalidates the
    complete *resulting* case's ground-truth requirement (§7 of this
    phase's spec) before committing."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    input: dict[str, Any] | None = None
    history: list[dict[str, Any]] | None = None

    reference_context: str | None = None
    expected_output: str | None = None
    assertions: list[dict[str, Any]] | None = None
    expected_tool_calls: list[dict[str, Any]] | None = None
    rubric: str | None = None

    expected_behavior: list[str] | None = None
    forbidden_behavior: list[str] | None = None
    allowed_tools: list[str] | None = None
    output_schema: dict[str, Any] | None = None
    latency_threshold_ms: int | None = Field(default=None, gt=0)

    rubric_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    trial_count: int | None = Field(default=None, ge=1)

    tags: list[str] | None = None
    metadata: dict[str, Any] | None = None


class TestCaseRead(BaseModel):
    # from_attributes=True so the router can return the raw TestCase ORM
    # object directly (matching every other router's response_model
    # convention in this codebase — see api/v1/agents.py).
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    suite_id: uuid.UUID
    name: str
    input: dict[str, Any]
    history: list[dict[str, Any]] | None

    reference_context: str | None
    expected_output: str | None
    assertions: list[dict[str, Any]] | None
    expected_tool_calls: list[dict[str, Any]] | None
    rubric: str | None

    expected_behavior: list[str] | None
    forbidden_behavior: list[str] | None
    allowed_tools: list[str] | None
    output_schema: dict[str, Any] | None
    latency_threshold_ms: int | None

    rubric_threshold: float
    trial_count: int

    tags: list[str]
    # The ORM attribute is named `case_metadata` (models/test_case.py) —
    # `metadata` is reserved on a SQLAlchemy declarative model (it's
    # `Base.metadata`, the schema-reflection object). `validation_alias`
    # only affects how this field is read *in* (from the ORM object's
    # `case_metadata` attribute); with no separate `serialization_alias`,
    # it still serializes out under its own name, "metadata", matching
    # the locked audit's field name exactly.
    metadata: dict[str, Any] = Field(validation_alias="case_metadata")

    # Phase 20: "active" for every ordinary TestCase; "candidate" for one
    # proposed from a real production failure and not yet accepted
    # (models/test_case.py's own docstring). source_execution_id is set
    # only for a (formerly-or-currently) candidate TestCase.
    status: str
    source_execution_id: uuid.UUID | None

    created_at: datetime
    updated_at: datetime
