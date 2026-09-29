from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class AgentCreate(BaseModel):
    # project_id is required here, not part of the URL path: per the
    # locked audit's own API sketch (`POST /agents {name, description?}`)
    # and this phase's exact required route list (`POST /agents`, not
    # `/projects/{project_id}/agents`), an Agent's owning Project has to
    # be identified somewhere — the request body is the only place left.
    # Flagged in the Phase 11 report as a resolved ambiguity, not a
    # silent assumption.
    project_id: uuid.UUID
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None


class AgentUpdate(BaseModel):
    """All fields optional — app/services/agent_service.py applies only
    the ones present in `model_fields_set`, matching
    schemas/project.py's ProjectUpdate convention exactly."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    is_enabled: bool | None = None
    default_expected_behavior: list[str] | None = None
    default_forbidden_behavior: list[str] | None = None
    default_output_schema: dict[str, Any] | None = None
    default_latency_threshold_ms: int | None = None
    default_allowed_tools: list[str] | None = None
    default_required_tools: list[str] | None = None
    min_call_interval_ms: int | None = None
    default_timeout_ms: int | None = None


class AgentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    description: str | None
    is_enabled: bool
    default_expected_behavior: list[str] | None
    default_forbidden_behavior: list[str] | None
    default_output_schema: dict[str, Any] | None
    default_latency_threshold_ms: int | None
    default_allowed_tools: list[str] | None
    default_required_tools: list[str] | None
    min_call_interval_ms: int
    default_timeout_ms: int
    created_at: datetime
    updated_at: datetime


class AgentVersionCreate(BaseModel):
    label: str = Field(min_length=1, max_length=100)
    adapter_type: Literal["http", "local"]
    # Deliberately a loose dict here, not a duplicated discriminated-union
    # schema: app/services/agent_service.py validates its actual shape by
    # reusing the existing Phase 10 HTTPAdapterConfig/LocalAdapterConfig
    # Pydantic models directly (app/adapters/http_adapter.py,
    # app/adapters/local_adapter.py) — the one place that shape is
    # defined, per the locked audit's "reuse app/adapters/ unchanged"
    # rule.
    adapter_config: dict[str, Any]
    observability_level: int = Field(ge=1, le=4)


class AgentVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    agent_id: uuid.UUID
    label: str
    adapter_type: str
    adapter_config: dict[str, Any]
    observability_level: int
    is_baseline: bool
    created_at: datetime


class TestInvokeInput(BaseModel):
    """Body for POST /agents/{id}/versions/{vid}/test-invoke — only the
    input payload is needed; adapter type/config come from the persisted
    AgentVersion, never from the request (unlike Phase 10's stateless
    /agent-adapter/test-invoke, which had no persisted version to read
    them from)."""

    input: dict[str, Any]
