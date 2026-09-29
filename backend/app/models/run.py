from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.flag import Flag
    from app.models.project import Project
    from app.models.tool_call import ToolCall


class Run(UUIDMixin, TimestampMixin, Base):
    """Phase 4: one execution of the Planner -> Evaluation -> Verification
    agent graph. `state` is the full AgentState (see app/agents/state.py)
    as of the last time this row was persisted, so a poll after a server
    restart mid-run still returns the last known state instead of losing it.
    """

    __tablename__ = "runs"

    project_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    goal: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="pending")
    state: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")

    project: Mapped[Project] = relationship(
        "Project",
        back_populates="runs",
    )
    tool_calls: Mapped[list[ToolCall]] = relationship(
        "ToolCall",
        back_populates="run",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    flags: Mapped[list[Flag]] = relationship(
        "Flag",
        back_populates="run",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
