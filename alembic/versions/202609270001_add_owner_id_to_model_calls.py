"""add owner_id to model_calls

Revision ID: 202609270001
Revises: 202609260001
Create Date: 2026-09-27 00:00:00.000000

Fixes a real cross-account data leak: GET /api/v1/cost had no way to
scope model_calls to the requesting user. model_calls.run_id (nullable,
FK -> runs.id) only ever links the legacy Planner/Evaluation/Verification
"Run" graph's calls (agent="planner"/"ask"/legacy "hallucination"/"rca"/
"auto_fix" nodes) back to a Project's owner. Every modern call site —
the Suite Runner's rubric-judge and grounding checks, the on-demand RCA
hypothesis tier, safety's LLM fallback — runs outside that legacy Run
model entirely and never populates run_id, so those rows (the majority
of real usage) have no existing path to an owner at all. Scoping the
query by the existing run_id join alone would therefore also hide a
genuine owner's own real usage, not just block the leak. A direct
owner_id captured at write time (see app/ai/client.py's new
current_owner_id contextvar) is the smallest change that both closes
the leak and preserves every existing call site's data for its real
owner.

Nullable, ON DELETE SET NULL: mirrors run_id's own precedent exactly
(a cost/audit record should outlive the run — and now the user — it
happened to belong to, per model_call.py's existing docstring). Rows
written before this migration keep owner_id=NULL; they are excluded
from every user's scoped view (never misattributed to a guess) until
naturally aged out by normal audit-log retention.
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "202609270001"
down_revision = "202609260001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "model_calls",
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        op.f("ix_model_calls_owner_id"), "model_calls", ["owner_id"], unique=False
    )
    op.create_foreign_key(
        op.f("fk_model_calls_owner_id_users"),
        "model_calls",
        "users",
        ["owner_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_model_calls_owner_id_users"), "model_calls", type_="foreignkey"
    )
    op.drop_index(op.f("ix_model_calls_owner_id"), table_name="model_calls")
    op.drop_column("model_calls", "owner_id")
