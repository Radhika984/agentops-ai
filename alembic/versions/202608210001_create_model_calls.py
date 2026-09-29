"""create model_calls

Revision ID: 202608210001
Revises: 202608200001
Create Date: 2026-08-21 00:00:00.000000

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "202608210001"
down_revision = "202608200001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "model_calls",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("agent", sa.String(length=50), nullable=False),
        sa.Column("model_group", sa.String(length=50), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("tokens_in", sa.Integer(), nullable=False),
        sa.Column("tokens_out", sa.Integer(), nullable=False),
        sa.Column("cost", sa.Numeric(precision=10, scale=6), nullable=False),
        sa.Column("cache_hit", sa.Boolean(), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_model_calls")),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["runs.id"],
            name=op.f("fk_model_calls_run_id_runs"),
            ondelete="SET NULL",
        ),
    )
    op.create_index(op.f("ix_model_calls_run_id"), "model_calls", ["run_id"], unique=False)
    op.create_index(op.f("ix_model_calls_agent"), "model_calls", ["agent"], unique=False)
    op.create_index(op.f("ix_model_calls_model"), "model_calls", ["model"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_model_calls_model"), table_name="model_calls")
    op.drop_index(op.f("ix_model_calls_agent"), table_name="model_calls")
    op.drop_index(op.f("ix_model_calls_run_id"), table_name="model_calls")
    op.drop_table("model_calls")
