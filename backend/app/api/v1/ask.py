from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.client import AIClientError
from app.api.v1.deps import get_current_user
from app.core.exceptions import NotFoundError, PermissionDeniedError
from app.db.session import get_db
from app.models.user import User
from app.schemas.ask import AskRequest, AskResponse, InteractionRead
from app.services.ask_service import AskService

router = APIRouter(prefix="/projects", tags=["ask"])


def _map_domain_error(exc: Exception) -> HTTPException:
    if isinstance(exc, NotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    if isinstance(exc, PermissionDeniedError):
        return HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized for this project"
        )
    if isinstance(exc, AIClientError):
        return HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The model provider request failed",
        )
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Unexpected error"
    )


@router.post("/{project_id}/ask", response_model=AskResponse, status_code=status.HTTP_201_CREATED)
async def ask(
    project_id: uuid.UUID,
    payload: AskRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> AskResponse:
    service = AskService(session)
    try:
        interaction, answer = await service.ask(
            project_id=project_id, owner_id=current_user.id, question=payload.question
        )
    except (NotFoundError, PermissionDeniedError, AIClientError) as exc:
        raise _map_domain_error(exc) from exc

    return AskResponse(
        id=interaction.id,
        project_id=interaction.project_id,
        question=interaction.prompt,
        answer=answer.answer,
        confidence=answer.confidence,
        created_at=interaction.created_at,
    )


@router.get("/{project_id}/ask", response_model=list[InteractionRead])
async def list_interactions(
    project_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> list[InteractionRead]:
    service = AskService(session)
    try:
        interactions = await service.get_history(project_id=project_id, owner_id=current_user.id)
    except (NotFoundError, PermissionDeniedError) as exc:
        raise _map_domain_error(exc) from exc

    return [
        InteractionRead(
            id=i.id,
            project_id=i.project_id,
            question=i.prompt,
            answer=i.response,
            created_at=i.created_at,
        )
        for i in interactions
    ]
