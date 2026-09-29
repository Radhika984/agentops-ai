"""Phase 17 — Regression Comparison API.

    GET /test-suites/{suite_id}/regression?candidate_run_id=<uuid>

Computed entirely on read (app/services/regression_service.py) — nothing
here is persisted. Ownership follows the same TestSuite ownership chain
every other test-suite-scoped route already uses (see
app/api/v1/test_suites.py, app/api/v1/suite_runs.py); the baseline side
of the comparison is never taken from the request, only the candidate
SuiteRun id is (§21 — "prefer an explicit candidate SuiteRun identifier").
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user
from app.core.exceptions import InvalidStateError, NotFoundError, PermissionDeniedError
from app.db.session import get_db
from app.models.user import User
from app.schemas.regression import RegressionResponse
from app.services.regression_service import RegressionService

router = APIRouter(tags=["regression"])


def _map_domain_error(exc: Exception) -> HTTPException:
    if isinstance(exc, NotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc) or "Not found")
    if isinstance(exc, PermissionDeniedError):
        return HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized for this resource"
        )
    if isinstance(exc, InvalidStateError):
        # Matches app/api/v1/approvals.py's exact convention for "the
        # resource exists and is owned, but isn't in a state that allows
        # this action yet" — reused, not a new error framework (§6).
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Unexpected error"
    )


@router.get("/test-suites/{suite_id}/regression", response_model=RegressionResponse)
async def get_regression(
    suite_id: uuid.UUID,
    candidate_run_id: uuid.UUID = Query(...),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> RegressionResponse:
    service = RegressionService(session)
    try:
        return await service.compare(
            suite_id=suite_id, owner_id=current_user.id, candidate_run_id=candidate_run_id
        )
    except (NotFoundError, PermissionDeniedError, InvalidStateError) as exc:
        raise _map_domain_error(exc) from exc
