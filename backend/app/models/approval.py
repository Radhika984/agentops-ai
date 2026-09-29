from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.run import Run
    from app.models.suite_run import SuiteRun
    from app.models.user import User


class Approval(UUIDMixin, TimestampMixin, Base):
    """Phase 9: a human-approval request raised by the release-review
    workflow (see app/approvals/service.py), per the blueprint's exact
    schema (run_id, node, status, requested_at, decided_by, decided_at,
    reason).

    Not a LangGraph checkpoint: this project's "pause"/"resume" is a plain
    Postgres row, not a suspended graph invocation — see
    app/approvals/service.py's module docstring for why (a real,
    Windows-specific incompatibility between LangGraph's Postgres
    checkpointer and this project's existing asyncio subprocess-based MCP
    tooling, found via direct testing, not assumed).

    `node` names which step raised the request: "auto_fix" (before a
    whitelisted patch is applied beyond its sandboxed re-verify) or
    "release_decision" (before Ship/Rollback) — the same two points the
    blueprint requires human sign-off for.

    Phase 18: `run_id` and `suite_run_id` are mutually exclusive —
    exactly one is set (DB CHECK constraint) — so the SAME approval
    queue serves both the legacy Run release-review workflow (Phase 9,
    `run_id`) and the new Suite-Run Release Gate (`suite_run_id`)
    without a second approval system. Every pre-existing Run-only
    repository method (get_owner_id(), list_for_owner(), mark_decided())
    is untouched and remains Run-only; `suite_run_id`-scoped approvals
    are created via a separate, additive path (see
    app/services/release_gate_service.py) and are not yet wired into the
    legacy decide() workflow — a deliberate, documented Phase 18 scope
    boundary (see the Phase 18 verification report).
    """

    __tablename__ = "approvals"
    __table_args__ = (
        CheckConstraint(
            "(run_id IS NOT NULL) <> (suite_run_id IS NOT NULL)",
            name="ck_approvals_exactly_one_run_reference",
        ),
    )

    run_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("runs.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    suite_run_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("suite_runs.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    node: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    run: Mapped[Run | None] = relationship("Run")
    suite_run: Mapped[SuiteRun | None] = relationship("SuiteRun")
    decider: Mapped[User | None] = relationship("User")
