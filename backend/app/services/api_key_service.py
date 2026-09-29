"""Settings > API Keys.

A real, working credential: `create()` generates a cryptographically
random secret (`secrets.token_urlsafe`, never anything guessable or
derived from user data), returns it to the caller exactly once, and
persists only its argon2 hash (app/core/security.py's existing
password_hash/hash_password/verify_password — a generic secret hasher,
reused rather than reimplemented). Verifying a candidate key against
every active row's hash (verify()) is what app/api/v1/deps.py's
get_current_user_or_api_key() calls to authenticate an API-key-bearing
request alongside the existing JWT flow — this module never authenticates
a request itself, it only issues/lists/revokes/verifies keys.
"""

from __future__ import annotations

import secrets
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, PermissionDeniedError
from app.core.security import hash_password, verify_password
from app.models.api_key import ApiKey
from app.models.user import User
from app.repositories.api_key_repository import ApiKeyRepository
from app.repositories.user_repository import UserRepository

_KEY_PREFIX = "aops_"
_KEY_DISPLAY_PREFIX_LEN = 12


class ApiKeyService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._keys = ApiKeyRepository(session)

    async def create(self, *, owner_id: uuid.UUID, name: str) -> tuple[ApiKey, str]:
        raw_key = _KEY_PREFIX + secrets.token_urlsafe(32)
        hashed = hash_password(raw_key)
        api_key = await self._keys.create(
            owner_id=owner_id,
            name=name,
            key_prefix=raw_key[:_KEY_DISPLAY_PREFIX_LEN],
            hashed_key=hashed,
        )
        await self._session.commit()
        return api_key, raw_key

    async def list_for_owner(self, owner_id: uuid.UUID) -> list[ApiKey]:
        return await self._keys.list_for_owner(owner_id)

    async def revoke(self, *, key_id: uuid.UUID, owner_id: uuid.UUID) -> ApiKey:
        api_key = await self._keys.get_by_id(key_id)
        if api_key is None:
            raise NotFoundError(f"API key not found: {key_id}")
        if api_key.owner_id != owner_id:
            raise PermissionDeniedError("You do not have access to this API key")
        revoked = await self._keys.revoke(api_key)
        await self._session.commit()
        return revoked

    async def verify(self, raw_key: str) -> User | None:
        """Checked against every active key's hash (there is no way to
        look a key up by its hash directly — see
        app/repositories/api_key_repository.py's list_active() docstring)
        and, on a match, records last_used_at and returns the owning
        User. Never raises — an invalid/revoked/unknown key is simply
        "no match", exactly like a wrong password."""
        if not raw_key.startswith(_KEY_PREFIX):
            return None
        for api_key in await self._keys.list_active():
            if verify_password(raw_key, api_key.hashed_key):
                await self._keys.mark_used(api_key)
                await self._session.commit()
                return await UserRepository(self._session).get_by_id(api_key.owner_id)
        return None
