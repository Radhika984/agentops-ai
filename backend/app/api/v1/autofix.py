"""Phase 19 — AutoFix proposal API.

    POST /suite-runs/{suite_run_id}/results/{result_id}/autofix

Generates a whitelist-only remediation proposal from Phase 18 RCA
evidence for one TestCaseResult. Options 1-3 create a real, pending
`Approval` row (through the existing Approval system — see
app/services/autofix_service.py) that must be approved/rejected via the
EXISTING `POST /approvals/{id}/decide` endpoint; Option 4 writes
`TestCaseResult.suggested_fix` directly and requires no approval. No new
endpoint exists for approving/applying — that is exactly the existing
approval workflow, unmodified in shape.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user
from app.core.exceptions import NotFoundError, PermissionDeniedError
from app.db.session import get_db
from app.models.user import User
from app.schemas.autofix import AutoFixProposalRead
from app.services.autofix_service import AutoFixService

router = APIRouter(tags=["autofix"])


def _map_domain_error(exc: Exception) -> HTTPException:
    if isinstance(exc, NotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc) or "Not found")
    if isinstance(exc, PermissionDeniedError):
        return HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized for this resource"
        )
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Unexpected error"
    )


@router.post(
    "/suite-runs/{suite_run_id}/results/{result_id}/autofix",
    response_model=AutoFixProposalRead,
    status_code=status.HTTP_201_CREATED,
)
async def propose_autofix(
    suite_run_id: uuid.UUID,
    result_id: uuid.UUID,
    # Only meaningful for the one RCA category the locked brief itself
    # says is reachable via either Option 1 or Option 2 (schema_field_missing)
    # — every other category always proposes its own fixed option
    # regardless of this flag.
    prefer_agent_default: bool = Query(False),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> AutoFixProposalRead:
    service = AutoFixService(session)
    try:
        return await service.propose(
            suite_run_id=suite_run_id,
            result_id=result_id,
            owner_id=current_user.id,
            prefer_agent_default=prefer_agent_default,
        )
    except (NotFoundError, PermissionDeniedError) as exc:
        raise _map_domain_error(exc) from exc
