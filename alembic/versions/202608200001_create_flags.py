"""create flags

Revision ID: 202608200001
Revises: 202608190001
Create Date: 2026-08-20 00:00:00.000000

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "202608200001"
down_revision = "202608190001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "flags",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent", sa.String(length=50), nullable=False),
        sa.Column("type", sa.String(length=100), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("details", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_flags")),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["runs.id"],
            name=op.f("fk_flags_run_id_runs"),
            ondelete="CASCADE",
        ),
    )
    op.create_index(op.f("ix_flags_run_id"), "flags", ["run_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_flags_run_id"), table_name="flags")
    op.drop_table("flags")
