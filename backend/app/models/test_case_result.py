from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.suite_run import SuiteRun
    from app.models.test_case import TestCase


class TestCaseResult(UUIDMixin, TimestampMixin, Base):
    """Phase 14: the persisted outcome of executing one TestCase's input
    through a SuiteRun's AgentVersion and passing the resulting
    AgentExecution through the Phase 13 Assertion Engine. This table
    stores the Assertion Engine's output — it never re-implements or
    duplicates any check logic itself.

    `(suite_run_id, test_case_id)` is unique — the locked idempotency
    requirement: a retried/duplicate execution of the same case within
    the same run must never produce a second row (app/services/
    suite_runner.py checks for an existing row before writing, and this
    constraint is the database-level backstop for that).

    `trials` always holds exactly one entry in this phase (Phase 14 is
    single-execution-per-case) but is shaped as a JSON array so Phase
    16's multi-trial voting can append to the same column without a
    schema change.
    """

    __tablename__ = "test_case_results"
    __table_args__ = (
        UniqueConstraint(
            "suite_run_id", "test_case_id", name="uq_test_case_results_suite_run_id_test_case_id"
        ),
        CheckConstraint(
            "verdict IN ('PASS', 'FAIL', 'INCONCLUSIVE')", name="ck_test_case_results_verdict"
        ),
    )

    suite_run_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("suite_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    test_case_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("test_cases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    verdict: Mapped[str] = mapped_column(String(20), nullable=False)
    verdict_method: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="majority"
    )
    checks: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    trials: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    actual_output: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    suggested_fix: Mapped[str | None] = mapped_column(Text, nullable=True)

    suite_run: Mapped[SuiteRun] = relationship("SuiteRun", back_populates="results")
    test_case: Mapped[TestCase] = relationship("TestCase")
