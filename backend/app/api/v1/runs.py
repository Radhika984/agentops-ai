from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user
from app.core.exceptions import NotFoundError, PermissionDeniedError
from app.db.session import get_db
from app.models.user import User
from app.schemas.run import RunCreate, RunRead
from app.services.run_service import RunService, run_graph_and_persist

router = APIRouter(prefix="/projects", tags=["runs"])


def _map_domain_error(exc: Exception) -> HTTPException:
    if isinstance(exc, NotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    if isinstance(exc, PermissionDeniedError):
        return HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized for this project"
        )
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Unexpected error"
    )


@router.post(
    "/{project_id}/runs", response_model=RunRead, status_code=status.HTTP_201_CREATED
)
async def create_run(
    project_id: uuid.UUID,
    payload: RunCreate,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> RunRead:
    service = RunService(session)
    try:
        run = await service.create_run(
            project_id=project_id, owner_id=current_user.id, goal=payload.goal
        )
    except (NotFoundError, PermissionDeniedError) as exc:
        raise _map_domain_error(exc) from exc

    # Scheduled to run after this response is sent (see run_graph_and_persist's
    # docstring for why it opens its own DB session). The client discovers
    # the outcome by polling GET /runs/{id}, not from this response.
    background_tasks.add_task(run_graph_and_persist, run.id)

    return RunRead.model_validate(run)


@router.get("/{project_id}/runs/{run_id}", response_model=RunRead)
async def get_run(
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> RunRead:
    service = RunService(session)
    try:
        run = await service.get_run(
            project_id=project_id, run_id=run_id, owner_id=current_user.id
        )
    except (NotFoundError, PermissionDeniedError) as exc:
        raise _map_domain_error(exc) from exc

    return RunRead.model_validate(run)
