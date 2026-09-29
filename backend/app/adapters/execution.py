"""The normalized execution envelope every AgentAdapter returns.

Per the locked audit (Final Architecture Spec §15): this is the one seam
every later phase's evaluation code reads from — no evaluator ever calls
an adapter directly, and no evaluator ever synthesizes a field this
envelope doesn't actually contain. A field the connected agent did not
expose is `None` / `[]`, never inferred, fabricated, or guessed at
("never fabricate tool calls, traces, hidden reasoning, or internal agent
behavior" — locked product rule 10).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ToolCallRecord(BaseModel):
    """One tool call the connected agent reported making. Only ever
    populated from data the agent itself returned — AgentOps never
    observes a SUT's tool calls any other way (no hidden instrumentation,
    no memory/vector-store introspection)."""

    tool_name: str
    input: dict[str, Any] = Field(default_factory=dict)
    output: str = ""
    duration_ms: int | None = None
    ok: bool = True


class TraceSpanRecord(BaseModel):
    """One execution span the connected agent reported (Level 3 —
    Trace-Aware only). Shape intentionally mirrors app/agents/state.py's
    existing TraceSpanRecord so a later phase's UI/evaluation code can
    treat both the legacy Run's internal trace and a real agent's
    self-reported trace the same way, without the two packages importing
    from each other."""

    name: str
    start_time_ns: int | None = None
    duration_ms: int | None = None


class AgentExecution(BaseModel):
    """One normalized invocation of a System Under Test, regardless of
    which concrete AgentAdapter produced it.

    Always available: request_id, input, status, latency_ms,
    started_at/finished_at, raw_response.
    Adapter-dependent: the shape of `output` (structured JSON vs. plain
    text, per the adapter's configuration).
    Optional, capability-gated: tool_calls, trace, token_usage,
    model_info — populated only when the connected agent's response
    actually contained that information (see http_adapter.py's/
    local_adapter.py's "response envelope convention" docstrings for
    exactly how each field is recognized).
    """

    model_config = ConfigDict(frozen=True)

    request_id: uuid.UUID
    input: dict[str, Any]
    output: dict[str, Any] | str | None
    status: Literal["ok", "error", "timeout"]
    error: str | None = None
    latency_ms: int
    started_at: datetime
    finished_at: datetime
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    trace: list[TraceSpanRecord] | None = None
    token_usage: dict[str, Any] | None = None
    model_info: dict[str, Any] | None = None
    raw_response: dict[str, Any] | None = None
