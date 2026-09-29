from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.agent import Agent
    from app.models.test_case import TestCase


class TestSuite(UUIDMixin, TimestampMixin, Base):
    """Phase 12: a named grouping of TestCases run against one Agent's
    versions (Suite execution — comparing a candidate AgentVersion
    against a baseline one — is Phase 14+; this table only groups and
    persists the cases themselves)."""

    __tablename__ = "test_suites"

    agent_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    agent: Mapped[Agent] = relationship("Agent")
    cases: Mapped[list[TestCase]] = relationship(
        "TestCase",
        back_populates="suite",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="TestCase.created_at",
    )
