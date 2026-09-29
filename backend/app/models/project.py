from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.interaction import Interaction
    from app.models.run import Run
    from app.models.user import User


class Project(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "projects"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    owner: Mapped[User] = relationship(
        "User",
        back_populates="projects",
    )
    interactions: Mapped[list[Interaction]] = relationship(
        "Interaction",
        back_populates="project",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    runs: Mapped[list[Run]] = relationship(
        "Run",
        back_populates="project",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
