from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import InvalidTokenError, decode_access_token
from app.db.session import get_db
from app.models.user import User
from app.repositories.user_repository import UserRepository

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    session: AsyncSession = Depends(get_db),
) -> User:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        user_id = decode_access_token(token)
    except InvalidTokenError as exc:
        raise credentials_error from exc

    repo = UserRepository(session)
    user = await repo.get_by_id(user_id)

    if user is None or not user.is_active:
        raise credentials_error

    return user


async def get_current_user_or_api_key(
    token: str = Depends(oauth2_scheme),
    session: AsyncSession = Depends(get_db),
) -> User:
    """The frontend's own requests never change: they always send a real
    JWT, and that JWT path is tried first, unmodified. This dependency
    exists purely to let a request also authenticate with an issued API
    key (Settings > API Keys, app/services/api_key_service.py) — the one
    genuinely new capability those keys are for (programmatic access, not
    this app's own browser session). Not swapped in for get_current_user
    anywhere the frontend calls today; a route only needs this if it must
    also accept API-key auth."""
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        user_id = decode_access_token(token)
    except InvalidTokenError:
        # Not a valid JWT — try it as an API key before giving up. Import
        # deferred to avoid a module-level cycle (api_key_service imports
        # from app.repositories, which do not import app.api.v1.deps).
        from app.services.api_key_service import ApiKeyService

        user = await ApiKeyService(session).verify(token)
        if user is None or not user.is_active:
            raise credentials_error from None
        return user

    repo = UserRepository(session)
    user = await repo.get_by_id(user_id)
    if user is None or not user.is_active:
        raise credentials_error

    return user
