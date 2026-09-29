"""Phase 14 — Suite Run creation + polling API.

POST /test-suites/{suite_id}/runs persists a `pending` SuiteRun and
schedules app.services.suite_runner.execute_suite_run as a
BackgroundTasks callback — exactly the existing legacy Run pattern
(app/api/v1/runs.py's create_run + app/services/run_service.py's
run_graph_and_persist). The HTTP response returns immediately; the
client discovers the outcome by polling GET /suite-runs/{id}, same as
GET /runs/{id} already works today.

Every route here accepts get_current_user_or_api_key (Settings > API
Keys) rather than the plain JWT-only get_current_user — the realistic
"trigger a run from CI, poll it, fetch results" surface a programmatic
API key is actually for. The frontend's own requests are unaffected: it
never sends anything but a real JWT, and that path is tried first,
unchanged.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user, get_current_user_or_api_key
from app.core.exceptions import NotFoundError, PermissionDeniedError
from app.db.session import get_db
from app.models.suite_run import SuiteRun
from app.models.test_case_result import TestCaseResult
from app.models.user import User
from app.schemas.dashboard import SuiteRunListResponse
from app.schemas.suite_run import SuiteRunCreate, SuiteRunRead, TestCaseResultRead
from app.services.dashboard_service import DashboardService
from app.services.suite_run_service import SuiteRunService
from app.services.suite_runner import execute_suite_run

router = APIRouter(tags=["suite-runs"])


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
    "/test-suites/{suite_id}/runs", response_model=SuiteRunRead, status_code=status.HTTP_201_CREATED
)
async def create_suite_run(
    suite_id: uuid.UUID,
    payload: SuiteRunCreate,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user_or_api_key),
    session: AsyncSession = Depends(get_db),
) -> SuiteRun:
    service = SuiteRunService(session)
    try:
        suite_run = await service.create_suite_run(
            suite_id=suite_id,
            owner_id=current_user.id,
            agent_version_id=payload.agent_version_id,
            max_concurrency=payload.max_concurrency,
        )
    except (NotFoundError, PermissionDeniedError) as exc:
        raise _map_domain_error(exc) from exc

    # Scheduled to run after this response is sent — see
    # execute_suite_run()'s own docstring for why it opens its own DB
    # session, matching run_graph_and_persist()'s established reasoning.
    background_tasks.add_task(execute_suite_run, suite_run.id)

    return suite_run


@router.get("/suite-runs", response_model=SuiteRunListResponse)
async def list_all_suite_runs(
    limit: int = 20,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> SuiteRunListResponse:
    """The account-wide "Runs" nav page — every SuiteRun across every
    TestSuite/Agent/Project this user owns. JWT-only (get_current_user,
    not get_current_user_or_api_key): this is a human-facing browse
    page, not the create/poll/results surface a CI integration actually
    needs, so it doesn't need the broader auth acceptance those three do."""
    return await DashboardService(session).get_recent_suite_runs(
        current_user.id, limit=min(limit, 100), offset=max(offset, 0)
    )


@router.get("/suite-runs/{suite_run_id}", response_model=SuiteRunRead)
async def get_suite_run(
    suite_run_id: uuid.UUID,
    current_user: User = Depends(get_current_user_or_api_key),
    session: AsyncSession = Depends(get_db),
) -> SuiteRun:
    service = SuiteRunService(session)
    try:
        return await service.get_suite_run(suite_run_id=suite_run_id, owner_id=current_user.id)
    except (NotFoundError, PermissionDeniedError) as exc:
        raise _map_domain_error(exc) from exc


@router.get("/suite-runs/{suite_run_id}/results", response_model=list[TestCaseResultRead])
async def list_suite_run_results(
    suite_run_id: uuid.UUID,
    current_user: User = Depends(get_current_user_or_api_key),
    session: AsyncSession = Depends(get_db),
) -> list[TestCaseResult]:
    service = SuiteRunService(session)
    try:
        return await service.list_results(suite_run_id=suite_run_id, owner_id=current_user.id)
    except (NotFoundError, PermissionDeniedError) as exc:
        raise _map_domain_error(exc) from exc


@router.get(
    "/suite-runs/{suite_run_id}/results/{result_id}", response_model=TestCaseResultRead
)
async def get_suite_run_result(
    suite_run_id: uuid.UUID,
    result_id: uuid.UUID,
    current_user: User = Depends(get_current_user_or_api_key),
    session: AsyncSession = Depends(get_db),
) -> TestCaseResult:
    service = SuiteRunService(session)
    try:
        return await service.get_result(
            suite_run_id=suite_run_id, result_id=result_id, owner_id=current_user.id
        )
    except (NotFoundError, PermissionDeniedError) as exc:
        raise _map_domain_error(exc) from exc
