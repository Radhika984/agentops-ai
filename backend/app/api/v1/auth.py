from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user
from app.core.exceptions import (
    EmailAlreadyExistsError,
    InactiveUserError,
    InvalidCredentialsError,
)
from app.db.session import get_db
from app.models.user import User
from app.schemas.token import Token
from app.schemas.user import (
    NotificationPreferences,
    PasswordChange,
    UserCreate,
    UserRead,
    UserUpdate,
)
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def register(payload: UserCreate, session: AsyncSession = Depends(get_db)) -> User:
    service = AuthService(session)
    try:
        return await service.register(
            email=payload.email,
            password=payload.password,
            full_name=payload.full_name,
        )
    except EmailAlreadyExistsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        ) from exc


@router.post("/login", response_model=Token)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    session: AsyncSession = Depends(get_db),
) -> Token:
    service = AuthService(session)
    try:
        access_token = await service.authenticate(
            email=form_data.username, password=form_data.password
        )
    except (InvalidCredentialsError, InactiveUserError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    return Token(access_token=access_token, token_type="bearer")


@router.get("/me", response_model=UserRead)
async def read_current_user(current_user: User = Depends(get_current_user)) -> User:
    return current_user


@router.patch("/me", response_model=UserRead)
async def update_current_user(
    payload: UserUpdate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> User:
    return await AuthService(session).update_profile(
        user=current_user, full_name=payload.full_name
    )


@router.patch("/me/password", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def change_password(
    payload: PasswordChange,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> None:
    try:
        await AuthService(session).change_password(
            user=current_user,
            current_password=payload.current_password,
            new_password=payload.new_password,
        )
    except InvalidCredentialsError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Current password is incorrect"
        ) from exc


@router.get("/me/notifications", response_model=NotificationPreferences)
async def read_notification_preferences(
    current_user: User = Depends(get_current_user),
) -> User:
    return current_user


@router.patch("/me/notifications", response_model=NotificationPreferences)
async def update_notification_preferences(
    payload: NotificationPreferences,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> User:
    return await AuthService(session).update_notification_preferences(
        user=current_user, preferences=payload.model_dump()
    )
