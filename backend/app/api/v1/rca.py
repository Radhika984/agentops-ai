"""Phase 18 — Root Cause Analysis API.

    GET /suite-runs/{suite_run_id}/results/{result_id}/rca

Computed entirely on read — nothing here is persisted. Ownership follows
the same SuiteRun ownership chain every other suite-run-scoped route
already uses (see app/api/v1/suite_runs.py). Deliberately its own
endpoint, separate from the release-gate endpoint (app/api/v1/release.py):
the release decision must never depend on an LLM call, so it only ever
consumes the deterministic RCA tier (app/rca/evidence.py) directly — the
LLM hypothesis tier is reached only when this endpoint is explicitly
requested for a specific case, keeping "avoid unnecessary LLM calls"
(§13 of the locked Phase 18 brief) true by construction.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user
from app.core.exceptions import NotFoundError, PermissionDeniedError
from app.db.session import get_db
from app.models.user import User
from app.schemas.rca import RCAResponse
from app.services.rca_service import RCAService

router = APIRouter(tags=["rca"])


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


@router.get("/suite-runs/{suite_run_id}/results/{result_id}/rca", response_model=RCAResponse)
async def get_rca(
    suite_run_id: uuid.UUID,
    result_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> RCAResponse:
    service = RCAService(session)
    try:
        return await service.analyze(
            suite_run_id=suite_run_id, result_id=result_id, owner_id=current_user.id
        )
    except (NotFoundError, PermissionDeniedError) as exc:
        raise _map_domain_error(exc) from exc
