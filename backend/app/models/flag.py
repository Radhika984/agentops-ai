from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.run import Run


class Flag(UUIDMixin, TimestampMixin, Base):
    """Phase 7: an audit-log row for one Safety block or Hallucination
    finding raised during a run.

    Populated by run_service.py after the graph finishes, same pattern as
    ToolCall — nodes accumulate flags in AgentState.flags as they happen
    (app/agents/planner.py and verification.py for Safety blocks,
    app/agents/hallucination.py for hallucination findings), and
    run_service bulk-writes them once, per the blueprint's schema
    (run_id, agent, type, severity, details).
    """

    __tablename__ = "flags"

    run_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    agent: Mapped[str] = mapped_column(String(50), nullable=False)
    type: Mapped[str] = mapped_column(String(100), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    details: Mapped[str] = mapped_column(Text, nullable=False)

    run: Mapped[Run] = relationship("Run", back_populates="flags")
