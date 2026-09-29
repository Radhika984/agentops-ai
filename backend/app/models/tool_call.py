from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.run import Run


class ToolCall(UUIDMixin, TimestampMixin, Base):
    """Phase 5: an audit-log row for one MCP tool call made during a run.

    Populated by run_service.py after the graph finishes (mirroring how
    Run.state is persisted) — nodes accumulate tool calls in
    AgentState.tool_calls as they happen (no DB access from nodes, same
    separation as everywhere else in the graph), and run_service bulk
    -writes them to this table once, per the blueprint's schema
    (run_id, tool_name, input, output, duration_ms).
    """

    __tablename__ = "tool_calls"

    run_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tool_name: Mapped[str] = mapped_column(String(100), nullable=False)
    input: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    output: Mapped[str] = mapped_column(Text, nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)

    run: Mapped[Run] = relationship("Run", back_populates="tool_calls")
