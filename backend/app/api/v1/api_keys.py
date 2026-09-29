from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user
from app.core.exceptions import NotFoundError, PermissionDeniedError
from app.db.session import get_db
from app.models.api_key import ApiKey
from app.models.user import User
from app.schemas.api_key import ApiKeyCreate, ApiKeyCreateResponse, ApiKeyRead
from app.services.api_key_service import ApiKeyService

router = APIRouter(prefix="/api-keys", tags=["api-keys"])


def _map_domain_error(exc: Exception) -> HTTPException:
    if isinstance(exc, NotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    if isinstance(exc, PermissionDeniedError):
        return HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized for this resource"
        )
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Unexpected error"
    )


@router.post("", response_model=ApiKeyCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    payload: ApiKeyCreate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> ApiKeyCreateResponse:
    api_key, raw_key = await ApiKeyService(session).create(
        owner_id=current_user.id, name=payload.name
    )
    # The only response, of any endpoint, that ever includes the raw
    # secret — see app/schemas/api_key.py's own docstring.
    return ApiKeyCreateResponse(
        id=api_key.id,
        name=api_key.name,
        key_prefix=api_key.key_prefix,
        api_key=raw_key,
        created_at=api_key.created_at,
    )


@router.get("", response_model=list[ApiKeyRead])
async def list_api_keys(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> list[ApiKey]:
    return await ApiKeyService(session).list_for_owner(current_user.id)


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def revoke_api_key(
    key_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> None:
    try:
        await ApiKeyService(session).revoke(key_id=key_id, owner_id=current_user.id)
    except (NotFoundError, PermissionDeniedError) as exc:
        raise _map_domain_error(exc) from exc
