"""create interactions

Revision ID: 202608160001
Revises: 202608150001
Create Date: 2026-08-16 00:00:00.000000

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "202608160001"
down_revision = "202608150001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "interactions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("response", sa.Text(), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_interactions")),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_interactions_project_id_projects"),
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        op.f("ix_interactions_project_id"), "interactions", ["project_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_interactions_project_id"), table_name="interactions")
    op.drop_table("interactions")