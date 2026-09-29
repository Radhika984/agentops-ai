"""Phase 20 — Post-release execution ingestion + monitoring API.

    POST /agent-versions/{version_id}/executions        ingest one execution
    GET  /agent-versions/{version_id}/executions         list executions
    GET  /agent-versions/{version_id}/executions/{id}    execution detail (+ RCA)
    GET  /agent-versions/{version_id}/monitoring         aggregate metrics
    POST /executions/{execution_id}/regression-candidate propose a candidate TestCase

Ownership follows the same Agent/AgentVersion chain every other
agent-scoped route already uses (see app/api/v1/agents.py). Nothing here
executes an adapter, modifies AgentVersion.adapter_config, or touches an
external agent — see app/services/production_execution_service.py's own
docstring.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user
from app.core.exceptions import NotFoundError, PermissionDeniedError, ValidationError
from app.db.session import get_db
from app.models.test_case import TestCase
from app.models.user import User
from app.schemas.production_execution import (
    ProductionExecutionCreate,
    ProductionExecutionDetailRead,
    ProductionExecutionRead,
    ProductionMonitoringSummary,
    RegressionCandidateCreate,
)
from app.schemas.test_suite import TestCaseRead
from app.services.production_execution_service import ProductionExecutionService

router = APIRouter(tags=["production-executions"])


def _map_domain_error(exc: Exception) -> HTTPException:
    if isinstance(exc, NotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc) or "Not found")
    if isinstance(exc, PermissionDeniedError):
        return HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized for this resource"
        )
    if isinstance(exc, ValidationError):
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Unexpected error"
    )


@router.post(
    "/agent-versions/{version_id}/executions",
    response_model=ProductionExecutionRead,
    status_code=status.HTTP_201_CREATED,
)
async def ingest_execution(
    version_id: uuid.UUID,
    payload: ProductionExecutionCreate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> ProductionExecutionRead:
    service = ProductionExecutionService(session)
    try:
        execution = await service.ingest(
            version_id=version_id, owner_id=current_user.id, payload=payload
        )
    except (NotFoundError, PermissionDeniedError) as exc:
        raise _map_domain_error(exc) from exc
    return ProductionExecutionRead.model_validate(execution)


@router.get("/agent-versions/{version_id}/executions", response_model=list[ProductionExecutionRead])
async def list_executions(
    version_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> list[ProductionExecutionRead]:
    service = ProductionExecutionService(session)
    try:
        executions = await service.list_executions(version_id=version_id, owner_id=current_user.id)
    except (NotFoundError, PermissionDeniedError) as exc:
        raise _map_domain_error(exc) from exc
    return [ProductionExecutionRead.model_validate(e) for e in executions]


@router.get(
    "/agent-versions/{version_id}/executions/{execution_id}",
    response_model=ProductionExecutionDetailRead,
)
async def get_execution(
    version_id: uuid.UUID,
    execution_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> ProductionExecutionDetailRead:
    service = ProductionExecutionService(session)
    try:
        execution = await service.get_execution(
            version_id=version_id, execution_id=execution_id, owner_id=current_user.id
        )
        rca_categories = await service.get_rca_categories(
            version_id=version_id, execution_id=execution_id, owner_id=current_user.id
        )
    except (NotFoundError, PermissionDeniedError) as exc:
        raise _map_domain_error(exc) from exc
    return ProductionExecutionDetailRead(
        **ProductionExecutionRead.model_validate(execution).model_dump(),
        rca_categories=rca_categories,
    )


@router.get("/agent-versions/{version_id}/monitoring", response_model=ProductionMonitoringSummary)
async def get_monitoring_summary(
    version_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> ProductionMonitoringSummary:
    service = ProductionExecutionService(session)
    try:
        return await service.get_monitoring_summary(version_id=version_id, owner_id=current_user.id)
    except (NotFoundError, PermissionDeniedError) as exc:
        raise _map_domain_error(exc) from exc


@router.post(
    "/executions/{execution_id}/regression-candidate",
    response_model=TestCaseRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_regression_candidate(
    execution_id: uuid.UUID,
    payload: RegressionCandidateCreate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> TestCase:
    service = ProductionExecutionService(session)
    try:
        return await service.create_regression_candidate(
            execution_id=execution_id, owner_id=current_user.id, payload=payload
        )
    except (NotFoundError, PermissionDeniedError, ValidationError) as exc:
        raise _map_domain_error(exc) from exc
