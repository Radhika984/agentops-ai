"""add suite_run_id to approvals

Revision ID: 202609190001
Revises: 202609180001
Create Date: 2026-09-19 00:00:00.000000

Phase 18: the existing Approval queue (Phase 9) can only reference a
legacy Run (`run_id`, NOT NULL). Release Gate needs to raise the exact
same kind of "Ship is a proposal, pending human approval" request for a
SuiteRun instead — reusing the same table/model/repository rather than
inventing a second approval system, per the locked Phase 18 brief's
explicit "Do NOT create a second approval system" instruction. This is a
purely additive change: `run_id` becomes nullable (every existing row
already has one, so no data is affected), a new nullable `suite_run_id`
FK is added, and a CHECK constraint requires exactly one of the two to
be set. No existing Approval-repository method that only ever handles
`run_id` (`get_owner_id()`, `list_for_owner()`, `mark_decided()`) is
touched by this migration or by Phase 18's own code — they remain
Run-only, unchanged.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "202609190001"
down_revision = "202609180001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("approvals", "run_id", existing_type=postgresql.UUID(as_uuid=True), nullable=True)
    op.add_column(
        "approvals", sa.Column("suite_run_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.create_foreign_key(
        op.f("fk_approvals_suite_run_id_suite_runs"),
        "approvals",
        "suite_runs",
        ["suite_run_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        op.f("ix_approvals_suite_run_id"), "approvals", ["suite_run_id"], unique=False
    )
    op.create_check_constraint(
        "ck_approvals_exactly_one_run_reference",
        "approvals",
        "(run_id IS NOT NULL) <> (suite_run_id IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_approvals_exactly_one_run_reference", "approvals", type_="check")
    op.drop_index(op.f("ix_approvals_suite_run_id"), table_name="approvals")
    op.drop_constraint(
        op.f("fk_approvals_suite_run_id_suite_runs"), "approvals", type_="foreignkey"
    )
    op.drop_column("approvals", "suite_run_id")
    op.alter_column("approvals", "run_id", existing_type=postgresql.UUID(as_uuid=True), nullable=False)
