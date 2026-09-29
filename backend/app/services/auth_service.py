from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    EmailAlreadyExistsError,
    InactiveUserError,
    InvalidCredentialsError,
)
from app.core.security import create_access_token, hash_password, verify_password
from app.models.user import User
from app.repositories.user_repository import UserRepository

_NOTIFICATION_FIELDS = (
    "notify_on_suite_run_complete",
    "notify_on_release_gate",
    "notify_on_autofix_proposed",
    "notify_on_approval_decided",
)


class AuthService:
    """Business rules for registration and login. Raises framework-independent
    domain exceptions only — never FastAPI's HTTPException."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._users = UserRepository(session)

    async def register(self, *, email: str, password: str, full_name: str | None = None) -> User:
        existing = await self._users.get_by_email(email)
        if existing is not None:
            raise EmailAlreadyExistsError(f"Email already registered: {email}")

        hashed = hash_password(password)
        user = await self._users.create(email=email, hashed_password=hashed, full_name=full_name)
        await self._session.commit()
        return user

    async def authenticate(self, *, email: str, password: str) -> str:
        user = await self._users.get_by_email(email)

        # Unknown email and wrong password raise the identical exception,
        # so the API layer can return one generic 401 either way.
        if user is None or not verify_password(password, user.hashed_password):
            raise InvalidCredentialsError("Incorrect email or password")

        if not user.is_active:
            raise InactiveUserError("User account is inactive")

        return create_access_token(user.id)

    async def update_profile(self, *, user: User, full_name: str | None) -> User:
        """Settings > Profile. `full_name` is the only editable profile
        field User actually has — email is immutable post-registration
        in this app's model (no change-email flow exists), so this is
        deliberately narrow rather than a generic patch-everything
        endpoint."""
        user.full_name = full_name
        await self._session.commit()
        await self._session.refresh(user)
        return user

    async def change_password(
        self, *, user: User, current_password: str, new_password: str
    ) -> None:
        """Settings > Security. Re-verifies the current password before
        accepting a new one — the same discipline app/core/security.py's
        login path already applies, reused, not reimplemented."""
        if not verify_password(current_password, user.hashed_password):
            raise InvalidCredentialsError("Current password is incorrect")
        user.hashed_password = hash_password(new_password)
        await self._session.commit()

    async def update_notification_preferences(
        self, *, user: User, preferences: dict[str, bool]
    ) -> User:
        for field in _NOTIFICATION_FIELDS:
            setattr(user, field, preferences[field])
        await self._session.commit()
        await self._session.refresh(user)
        return user
