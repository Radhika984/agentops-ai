from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user
from app.core.exceptions import NotFoundError, PermissionDeniedError
from app.db.session import get_db
from app.models.project import Project
from app.models.user import User
from app.schemas.project import ProjectCreate, ProjectRead, ProjectUpdate
from app.services.project_service import ProjectService

router = APIRouter(prefix="/projects", tags=["projects"])


def _map_domain_error(exc: Exception) -> HTTPException:
    if isinstance(exc, NotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    if isinstance(exc, PermissionDeniedError):
        return HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized for this project"
        )
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Unexpected error"
    )


@router.post("", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
async def create_project(
    payload: ProjectCreate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> Project:
    service = ProjectService(session)
    return await service.create_project(
        owner_id=current_user.id, name=payload.name, description=payload.description
    )


@router.get("", response_model=list[ProjectRead])
async def list_projects(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> list[Project]:
    service = ProjectService(session)
    return await service.list_projects(owner_id=current_user.id)


@router.get("/{project_id}", response_model=ProjectRead)
async def get_project(
    project_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> Project:
    service = ProjectService(session)
    try:
        return await service.get_project(project_id=project_id, owner_id=current_user.id)
    except (NotFoundError, PermissionDeniedError) as exc:
        raise _map_domain_error(exc) from exc


@router.patch("/{project_id}", response_model=ProjectRead)
async def update_project(
    project_id: uuid.UUID,
    payload: ProjectUpdate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> Project:
    service = ProjectService(session)
    try:
        return await service.update_project(
            project_id=project_id,
            owner_id=current_user.id,
            name=payload.name,
            description=payload.description,
            fields_set=payload.model_fields_set,
        )
    except (NotFoundError, PermissionDeniedError) as exc:
        raise _map_domain_error(exc) from exc


@router.delete(
    "/{project_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def delete_project(
    project_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> None:
    service = ProjectService(session)
    try:
        await service.delete_project(
            project_id=project_id,
            owner_id=current_user.id,
        )
    except (NotFoundError, PermissionDeniedError) as exc:
        raise _map_domain_error(exc) from exc
