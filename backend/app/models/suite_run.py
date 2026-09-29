from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDMixin

if TYPE_CHECKING:
    from app.models.agent_version import AgentVersion
    from app.models.test_case_result import TestCaseResult
    from app.models.test_suite import TestSuite


class SuiteRun(UUIDMixin, Base):
    """Phase 14: one execution of a TestSuite against a specific,
    immutable AgentVersion snapshot.

    No `updated_at` (unlike most models — see TimestampMixin elsewhere):
    the locked field list for this table is exactly id/suite_id/
    agent_version_id/status/started_at/completed_at/the four aggregate
    counters/max_concurrency/created_at — the same "narrower than the
    usual TimestampMixin" choice AgentVersion already made for the same
    reason (this row's own lifecycle is tracked by started_at/
    completed_at, not a generic updated_at).

    agent_version_id -> RESTRICT, not CASCADE: deleting an AgentVersion
    that a SuiteRun already ran against would silently orphan that run's
    historical results' "what was actually tested" record — the locked
    audit's reproducibility requirement (see models/agent_version.py).
    """

    __tablename__ = "suite_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'cancelling', 'completed', 'failed')",
            name="ck_suite_runs_status",
        ),
        CheckConstraint("max_concurrency >= 1", name="ck_suite_runs_max_concurrency"),
    )

    suite_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("test_suites.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    agent_version_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("agent_versions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="pending")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    pass_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    fail_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    inconclusive_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    skipped_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    llm_judge_invocation_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    max_concurrency: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    suite: Mapped[TestSuite] = relationship("TestSuite")
    agent_version: Mapped[AgentVersion] = relationship("AgentVersion")
    results: Mapped[list[TestCaseResult]] = relationship(
        "TestCaseResult",
        back_populates="suite_run",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
