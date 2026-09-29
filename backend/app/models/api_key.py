from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class ApiKey(UUIDMixin, TimestampMixin, Base):
    """A user-issued API key for programmatic access, authenticated
    alongside (not instead of) the existing JWT bearer flow (see
    app/api/v1/deps.py's get_current_user_or_api_key()).

    The raw key is NEVER stored — only `hashed_key`, hashed with the exact
    same argon2 hasher app/core/security.py already uses for passwords
    (a generic secret hasher, not password-specific). The raw value is
    returned to the caller exactly once, at creation (see
    app/services/api_key_service.py's create()); this row can never answer
    "what is this key's value" again, only "does this candidate string
    hash to this row" (verify_password() from core/security.py, reused).

    `key_prefix` (the first 8 characters of the raw key, plain text) lets a
    user recognize which key is which in a list without ever exposing the
    full secret again — the same UX pattern GitHub/Stripe personal-access
    tokens use.

    `revoked_at` rather than a hard delete: a revoked key's row is kept so
    "this key existed and was used until it was revoked" remains a real,
    inspectable fact — mirrors ActivityEvent's own "history must survive"
    reasoning.
    """

    __tablename__ = "api_keys"

    owner_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    key_prefix: Mapped[str] = mapped_column(String(12), nullable=False)
    hashed_key: Mapped[str] = mapped_column(String(255), nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
