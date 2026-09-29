"""Phase 10 — a single endpoint proving the Agent Adapter layer works
end-to-end over HTTP: given an adapter type/config and an input payload,
invoke it and return the normalized AgentExecution.

Deliberately stateless for this phase: the locked audit's final shape is
`POST /agents/{id}/versions/{vid}/test-invoke`, addressed by persisted
Agent/AgentVersion IDs — but those tables belong to the Agent Registry
(Phase 11), which is explicitly out of scope here ("Do NOT implement
TestSuite, TestCase... unless a tiny shared type is strictly required by
Phase 10"). This endpoint takes the adapter type/config directly in the
request body instead, so Phase 10's own acceptance criterion — "AgentOps
must be able to connect to a real local/external agent... Add the
test-invoke API required by the audit" — is met without inventing the
Agent Registry early. Phase 11 is expected to add the persisted-ID
version of this endpoint, reusing build_adapter() unchanged.

No project/resource ownership check applies here (nothing is persisted
or owned yet) — only authentication is required, the same floor every
other endpoint in this API enforces.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.adapters.exceptions import AdapterConfigError
from app.adapters.execution import AgentExecution
from app.adapters.factory import build_adapter
from app.api.v1.deps import get_current_user
from app.models.user import User
from app.schemas.agent_adapter import TestInvokeRequest

router = APIRouter(prefix="/agent-adapter", tags=["agent-adapter"])


@router.post("/test-invoke", response_model=AgentExecution, status_code=status.HTTP_200_OK)
async def test_invoke(
    payload: TestInvokeRequest,
    current_user: User = Depends(get_current_user),
) -> AgentExecution:
    try:
        adapter = build_adapter(payload.adapter_type, payload.adapter_config)
    except AdapterConfigError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    try:
        return await adapter.invoke(payload.input)
    except AdapterConfigError as exc:
        # Raised by HTTPAdapter.invoke() itself (URL/SSRF validation runs
        # per-invocation, not only at construction) — still a config
        # problem, still 422, never a fabricated AgentExecution.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
