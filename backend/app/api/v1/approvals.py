from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user
from app.approvals.service import ReleaseSnapshot
from app.core.exceptions import (
    InvalidStateError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from app.db.session import get_db
from app.models.approval import Approval
from app.models.user import User
from app.schemas.approval import ApprovalDecide, ApprovalRead, ReleaseSnapshotRead
from app.services.approval_service import ApprovalService

DecideApprovalResponse = ReleaseSnapshotRead | ApprovalRead

router = APIRouter(tags=["approvals"])


def _map_domain_error(exc: Exception) -> HTTPException:
    if isinstance(exc, NotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    if isinstance(exc, PermissionDeniedError):
        return HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized for this resource"
        )
    if isinstance(exc, InvalidStateError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, ValidationError):
        # Phase 19: an AutoFix proposal payload that fails
        # app/autofix/apply.py's whitelist re-validation at apply time
        # (e.g. an unknown or disallowed field) — matches
        # api/v1/test_suites.py's own ValidationError -> 422 convention.
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Unexpected error"
    )


@router.post(
    "/projects/{project_id}/runs/{run_id}/release", response_model=ReleaseSnapshotRead
)
async def request_release(
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> ReleaseSnapshot:
    service = ApprovalService(session)
    try:
        return await service.request_release(
            project_id=project_id, run_id=run_id, owner_id=current_user.id
        )
    except (NotFoundError, PermissionDeniedError, InvalidStateError) as exc:
        raise _map_domain_error(exc) from exc


@router.get("/approvals", response_model=list[ApprovalRead])
async def list_approvals(
    status_filter: str | None = None,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> list[Approval]:
    service = ApprovalService(session)
    return await service.list_approvals(owner_id=current_user.id, status=status_filter)


@router.post("/approvals/{approval_id}/decide", response_model=DecideApprovalResponse)
async def decide_approval(
    approval_id: uuid.UUID,
    payload: ApprovalDecide,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> DecideApprovalResponse:
    service = ApprovalService(session)
    try:
        result = await service.decide_approval(
            approval_id=approval_id,
            owner_id=current_user.id,
            approved=payload.approved,
            reason=payload.reason,
        )
    except (NotFoundError, PermissionDeniedError, InvalidStateError, ValidationError) as exc:
        raise _map_domain_error(exc) from exc

    # Phase 18 correction: a SuiteRun-scoped approval has no legacy
    # ReleaseSnapshot to report (Phase 18's Release Gate is computed
    # fresh on every request, not a persisted multi-stage workflow) — it
    # is represented by the decided Approval row itself, the same shape
    # GET /approvals already returns. The Run path's response is built
    # exactly as before (byte-for-byte unchanged).
    if isinstance(result, Approval):
        return ApprovalRead.model_validate(result)
    return ReleaseSnapshotRead(**result)
