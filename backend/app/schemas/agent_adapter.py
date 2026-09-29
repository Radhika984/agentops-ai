"""Request schema for the Phase 10 test-invoke endpoint.

See app/api/v1/agent_adapter.py's module docstring for why this endpoint
is stateless (takes adapter config directly) rather than the audit's
final `/agents/{id}/versions/{vid}/test-invoke` shape, which requires the
Agent Registry (Phase 11).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel


class TestInvokeRequest(BaseModel):
    adapter_type: Literal["http", "local"]
    adapter_config: dict[str, Any]
    input: dict[str, Any]
