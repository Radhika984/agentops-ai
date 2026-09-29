from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.project import Project


class User(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    # Notification preferences: this app has no email/push delivery
    # system, so these deliberately do NOT pretend to control one. Their
    # one real, verifiable effect (see app/services/activity_service.py's
    # record()) is whether that event type is written to this user's own
    # Recent Activity feed at all — a genuine behavioral toggle, not a
    # setting that silently does nothing.
    notify_on_suite_run_complete: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    notify_on_release_gate: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    notify_on_autofix_proposed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    notify_on_approval_decided: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    projects: Mapped[list[Project]] = relationship(
        "Project",
        back_populates="owner",
        passive_deletes=True,  # let PostgreSQL enforce ON DELETE RESTRICT
    )
