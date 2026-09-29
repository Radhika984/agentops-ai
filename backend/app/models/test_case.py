from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import CheckConstraint, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.test_suite import TestSuite


class TestCase(UUIDMixin, TimestampMixin, Base):
    """Phase 12: the evaluation contract for one concrete input against
    one TestSuite's Agent — the ground-truth layer the locked audit's
    Evaluation Engine (Phase 13+) will read from. This table only stores
    and validates the contract; nothing here executes it (no PASS/FAIL,
    no assertion execution, no tool-trajectory comparison — see
    app/services/test_suite_service.py's module docstring).

    Per the locked audit (§9): a case is valid only if at least one of
    expected_output / assertions / reference_context / expected_tool_calls
    / rubric is present — enforced at the application layer (see
    _has_ground_truth() in the service), not as a DB CHECK constraint,
    because "presence" means non-empty for the array/JSONB fields
    (an empty list must not count), which a portable CHECK expression
    can't cleanly express across all five column types at once.

    Phase 20: `status` distinguishes a normal, active TestCase from a
    `candidate` proposed from a real post-release failure
    (app/services/production_execution_service.py) — a candidate is
    persisted so it is visible and reviewable, but is deliberately
    excluded from Suite Runner execution
    (TestCaseRepository.list_active_by_suite(), used by
    app/services/suite_runner.py instead of list_by_suite()) until a
    human explicitly accepts it (TestSuiteService.accept_candidate()).
    `source_execution_id` traces an accepted-or-not candidate back to the
    real ProductionExecution evidence it was proposed from; NULL for
    every ordinary TestCase.
    """

    __tablename__ = "test_cases"
    __table_args__ = (
        CheckConstraint("trial_count >= 1", name="ck_test_cases_trial_count"),
        CheckConstraint(
            "rubric_threshold >= 0 AND rubric_threshold <= 1",
            name="ck_test_cases_rubric_threshold",
        ),
        CheckConstraint(
            "latency_threshold_ms IS NULL OR latency_threshold_ms > 0",
            name="ck_test_cases_latency_threshold_ms",
        ),
        CheckConstraint("status IN ('active', 'candidate')", name="ck_test_cases_status"),
    )

    suite_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("test_suites.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    input: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    history: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)

    # ---- Ground truth (at least one required — see module docstring) ----
    reference_context: Mapped[str | None] = mapped_column(Text, nullable=True)
    expected_output: Mapped[str | None] = mapped_column(Text, nullable=True)
    assertions: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    expected_tool_calls: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    rubric: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ---- Behavioral / structural / performance requirements (optional,
    # override the owning Agent's default_* columns — Phase 11, never
    # duplicated into a second contract table) ----
    expected_behavior: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    forbidden_behavior: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    allowed_tools: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    output_schema: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    latency_threshold_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    rubric_threshold: Mapped[float] = mapped_column(Float, nullable=False, server_default="0.7")
    trial_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")

    tags: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default="{}")
    case_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default="{}"
    )

    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="active")
    source_execution_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("production_executions.id", ondelete="SET NULL"),
        nullable=True,
    )

    suite: Mapped[TestSuite] = relationship("TestSuite", back_populates="cases")
