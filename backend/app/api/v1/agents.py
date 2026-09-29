"""Phase 11 — Agent Registry API.

Routes are flat (`/agents`, not `/projects/{project_id}/agents`), per
this phase's exact required route list; project ownership is still
enforced on every request — see app/services/agent_service.py's
docstring — via `project_id` in the request body (create) or a required
query parameter (list), since a flat route has nowhere else to carry it.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.exceptions import AdapterConfigError
from app.adapters.execution import AgentExecution
from app.api.v1.deps import get_current_user
from app.core.exceptions import ConflictError, NotFoundError, PermissionDeniedError, ValidationError
from app.db.session import get_db
from app.models.agent import Agent
from app.models.agent_version import AgentVersion
from app.models.user import User
from app.schemas.agent import (
    AgentCreate,
    AgentRead,
    AgentUpdate,
    AgentVersionCreate,
    AgentVersionRead,
    TestInvokeInput,
)
from app.services.agent_service import AgentService

router = APIRouter(prefix="/agents", tags=["agents"])


def _map_domain_error(exc: Exception) -> HTTPException:
    if isinstance(exc, NotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc) or "Not found")
    if isinstance(exc, PermissionDeniedError):
        return HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized for this resource"
        )
    if isinstance(exc, ConflictError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, ValidationError):
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    if isinstance(exc, AdapterConfigError):
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Unexpected error"
    )


@router.post("", response_model=AgentRead, status_code=status.HTTP_201_CREATED)
async def create_agent(
    payload: AgentCreate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> Agent:
    service = AgentService(session)
    try:
        return await service.create_agent(
            project_id=payload.project_id,
            owner_id=current_user.id,
            name=payload.name,
            description=payload.description,
        )
    except (NotFoundError, PermissionDeniedError) as exc:
        raise _map_domain_error(exc) from exc


@router.get("", response_model=list[AgentRead])
async def list_agents(
    project_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> list[Agent]:
    service = AgentService(session)
    try:
        return await service.list_agents(project_id=project_id, owner_id=current_user.id)
    except (NotFoundError, PermissionDeniedError) as exc:
        raise _map_domain_error(exc) from exc


@router.get("/{agent_id}", response_model=AgentRead)
async def get_agent(
    agent_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> Agent:
    service = AgentService(session)
    try:
        return await service.get_agent(agent_id=agent_id, owner_id=current_user.id)
    except (NotFoundError, PermissionDeniedError) as exc:
        raise _map_domain_error(exc) from exc


@router.patch("/{agent_id}", response_model=AgentRead)
async def update_agent(
    agent_id: uuid.UUID,
    payload: AgentUpdate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> Agent:
    service = AgentService(session)
    try:
        return await service.update_agent(
            agent_id=agent_id,
            owner_id=current_user.id,
            payload=payload.model_dump(),
            fields_set=payload.model_fields_set,
        )
    except (NotFoundError, PermissionDeniedError) as exc:
        raise _map_domain_error(exc) from exc


@router.post(
    "/{agent_id}/versions", response_model=AgentVersionRead, status_code=status.HTTP_201_CREATED
)
async def create_version(
    agent_id: uuid.UUID,
    payload: AgentVersionCreate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> AgentVersion:
    service = AgentService(session)
    try:
        return await service.create_version(
            agent_id=agent_id,
            owner_id=current_user.id,
            label=payload.label,
            adapter_type=payload.adapter_type,
            adapter_config=payload.adapter_config,
            observability_level=payload.observability_level,
        )
    except (NotFoundError, PermissionDeniedError, ConflictError, ValidationError) as exc:
        raise _map_domain_error(exc) from exc


@router.get("/{agent_id}/versions", response_model=list[AgentVersionRead])
async def list_versions(
    agent_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> list[AgentVersion]:
    service = AgentService(session)
    try:
        return await service.list_versions(agent_id=agent_id, owner_id=current_user.id)
    except (NotFoundError, PermissionDeniedError) as exc:
        raise _map_domain_error(exc) from exc


@router.post("/{agent_id}/versions/{version_id}/baseline", response_model=AgentVersionRead)
async def promote_baseline(
    agent_id: uuid.UUID,
    version_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> AgentVersion:
    service = AgentService(session)
    try:
        return await service.promote_baseline(
            agent_id=agent_id, version_id=version_id, owner_id=current_user.id
        )
    except (NotFoundError, PermissionDeniedError) as exc:
        raise _map_domain_error(exc) from exc


@router.post("/{agent_id}/versions/{version_id}/test-invoke", response_model=AgentExecution)
async def test_invoke(
    agent_id: uuid.UUID,
    version_id: uuid.UUID,
    payload: TestInvokeInput,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> AgentExecution:
    service = AgentService(session)
    try:
        return await service.test_invoke(
            agent_id=agent_id,
            version_id=version_id,
            owner_id=current_user.id,
            input=payload.input,
        )
    except (NotFoundError, PermissionDeniedError) as exc:
        raise _map_domain_error(exc) from exc
    except AdapterConfigError as exc:
        raise _map_domain_error(exc) from exc
