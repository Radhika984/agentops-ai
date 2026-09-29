from __future__ import annotations

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDMixin

# Must match memory/embeddings.py's EMBEDDING_DIMENSIONS exactly — pgvector
# columns are fixed-width.
EMBEDDING_DIMENSIONS = 768


class Embedding(UUIDMixin, Base):
    """Phase 6 long-term memory: one embedded chunk of text plus a pointer
    back to where it came from.

    Deliberately just UUIDMixin + created_at (not the usual TimestampMixin)
    — matching the blueprint's literal schema (id, content, vector,
    source_type, source_id, created_at). Embeddings are write-once: a
    changed source gets a new row via memory/manager.py, not an update, so
    there's no updated_at to track.

    `source_id` has no foreign key: source_type is polymorphic ("run" is
    the only value Phase 6 writes, via run completion — see
    services/run_service.py), so there's no single table it could
    consistently reference.
    """

    __tablename__ = "embeddings"

    content: Mapped[str] = mapped_column(Text, nullable=False)
    vector: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSIONS), nullable=False)
    source_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    source_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
