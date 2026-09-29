from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.api_key import ApiKey


class ApiKeyRepository:
    """Database access for API keys. No hashing, no HTTP concerns — see
    app/services/api_key_service.py for the actual create/verify/revoke
    business logic and app/core/security.py for the argon2 hasher this
    reuses."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self, *, owner_id: uuid.UUID, name: str, key_prefix: str, hashed_key: str
    ) -> ApiKey:
        api_key = ApiKey(
            owner_id=owner_id, name=name, key_prefix=key_prefix, hashed_key=hashed_key
        )
        self._session.add(api_key)
        await self._session.flush()
        await self._session.refresh(api_key)
        return api_key

    async def list_for_owner(self, owner_id: uuid.UUID) -> list[ApiKey]:
        result = await self._session.execute(
            select(ApiKey)
            .where(ApiKey.owner_id == owner_id)
            .order_by(ApiKey.created_at.desc())
        )
        return list(result.scalars().all())

    async def list_active(self) -> list[ApiKey]:
        """Every non-revoked key, for app/api/v1/deps.py's
        get_current_user_or_api_key() to check a candidate raw key
        against. There is no way to look a key up by its hash directly
        (verify_password() must be run against each candidate's own salt
        — see core/security.py's argon2 hasher), so this is a real,
        deliberate full scan of active keys, not an oversight; it is
        expected to stay small (a personal-access-token-style feature,
        not a high-volume API-gateway one)."""
        result = await self._session.execute(select(ApiKey).where(ApiKey.revoked_at.is_(None)))
        return list(result.scalars().all())

    async def get_by_id(self, key_id: uuid.UUID) -> ApiKey | None:
        result = await self._session.execute(select(ApiKey).where(ApiKey.id == key_id))
        return result.scalar_one_or_none()

    async def mark_used(self, api_key: ApiKey) -> None:
        api_key.last_used_at = datetime.now(UTC)
        await self._session.flush()

    async def revoke(self, api_key: ApiKey) -> ApiKey:
        api_key.revoked_at = datetime.now(UTC)
        await self._session.flush()
        return api_key
