"""Phase 20 — Post-release execution ingestion/monitoring schemas.

The ingestion request has no field for adapter_config, credentials,
headers, or any executable content — nothing it accepts can reach those
concepts even in principle (§9/§13). `metadata` is the one open-ended
bag, and is explicitly checked for a small set of obviously
credential-shaped keys and rejected if present, as a defensive
(not the only) guard.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.adapters.execution import ToolCallRecord, TraceSpanRecord

_FORBIDDEN_METADATA_KEYS = frozenset(
    {
        "authorization",
        "api_key",
        "apikey",
        "password",
        "credential",
        "credentials",
        "secret",
        "adapter_config",
    }
)


class ProductionExecutionCreate(BaseModel):
    external_execution_id: str = Field(min_length=1, max_length=255)
    input: dict[str, Any]
    actual_output: Any | None = None
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    # Required, not optional: reused directly as app.adapters.execution.
    # AgentExecution.latency_ms, which Phase 10 already declares as a
    # required `int` (never None) — every real execution has a
    # measurable latency, so ingestion simply requires the caller to
    # report it rather than this module inventing a placeholder value
    # that could wrongly pass a configured latency threshold.
    latency_ms: int = Field(ge=0)
    error: str | None = Field(default=None, max_length=4000)
    reference_context: str | None = None
    trace: list[TraceSpanRecord] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("metadata")
    @classmethod
    def _reject_credential_shaped_keys(cls, value: dict[str, Any]) -> dict[str, Any]:
        lowered_keys = {str(key).lower() for key in value}
        offending = lowered_keys & _FORBIDDEN_METADATA_KEYS
        if offending:
            raise ValueError(
                f"metadata must not contain credential-shaped keys: {sorted(offending)}"
            )
        return value


class ProductionExecutionRead(BaseModel):
    # populate_by_name=True: app/api/v1/production_executions.py's detail
    # route builds ProductionExecutionDetailRead by spreading this
    # model's own model_dump() (keyed by field name, "metadata") back
    # into a constructor call — without this, only the validation_alias
    # ("execution_metadata") would be accepted as a constructor kwarg.
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: uuid.UUID
    agent_version_id: uuid.UUID
    external_execution_id: str
    input: dict[str, Any]
    actual_output: Any | None
    tool_calls: list[dict[str, Any]]
    latency_ms: int | None
    error: str | None
    reference_context: str | None
    trace: list[dict[str, Any]] | None
    metadata: dict[str, Any] = Field(validation_alias="execution_metadata")
    verdict: str
    checks: list[dict[str, Any]]
    created_at: datetime


class RCAFindingRead(BaseModel):
    category: str
    check_type: str
    detail: str


class ProductionExecutionDetailRead(ProductionExecutionRead):
    """The detail-view response — adds the deterministic RCA whitelist
    (app/rca/evidence.py, Phase 18, reused verbatim) computed on read
    from this execution's own persisted checks. Never included on the
    list endpoint (would mean recomputing it once per row for no
    per-row benefit there)."""

    rca_categories: list[RCAFindingRead]


class ProductionMonitoringSummary(BaseModel):
    agent_version_id: uuid.UUID
    total_executions: int
    pass_count: int
    fail_count: int
    inconclusive_count: int
    failure_rate: float | None
    average_latency_ms: float | None
    latency_threshold_violations: int
    safety_failure_count: int
    forbidden_tool_count: int
    missing_required_tool_count: int
    schema_failure_count: int
    grounding_evaluated_count: int
    grounding_failure_count: int


class RegressionCandidateCreate(BaseModel):
    """Body for POST /executions/{execution_id}/regression-candidate.

    `input`/`name` default from the execution itself when omitted; every
    other field is the same ground-truth/behavioral vocabulary
    TestCaseCreate already uses (app/schemas/test_suite.py) — reused
    field-for-field, not a parallel schema, so the created candidate is
    validated by the exact same Phase 12 ground-truth rule as any other
    TestCase (TestSuiteService._has_ground_truth(), unmodified).
    """

    suite_id: uuid.UUID
    name: str | None = Field(default=None, max_length=255)
    input: dict[str, Any] | None = None

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
