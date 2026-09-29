"""Phase 18 — Release Gate API.

    POST /suite-runs/{suite_run_id}/release

Computed entirely on read/write-of-an-approval-row-only — no
ReleaseDecision is persisted (see app/services/release_gate_service.py).
Ownership follows the same SuiteRun ownership chain every other
suite-run-scoped route already uses.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user
from app.core.exceptions import InvalidStateError, NotFoundError, PermissionDeniedError
from app.db.session import get_db
from app.models.user import User
from app.schemas.release import ReleaseDecisionResponse
from app.services.release_gate_service import ReleaseGateService

router = APIRouter(tags=["release"])


def _map_domain_error(exc: Exception) -> HTTPException:
    if isinstance(exc, NotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc) or "Not found")
    if isinstance(exc, PermissionDeniedError):
        return HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized for this resource"
        )
    if isinstance(exc, InvalidStateError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Unexpected error"
    )


@router.post("/suite-runs/{suite_run_id}/release", response_model=ReleaseDecisionResponse)
async def evaluate_release(
    suite_run_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> ReleaseDecisionResponse:
    service = ReleaseGateService(session)
    try:
        return await service.evaluate(suite_run_id=suite_run_id, owner_id=current_user.id)
    except (NotFoundError, PermissionDeniedError, InvalidStateError) as exc:
        raise _map_domain_error(exc) from exc
