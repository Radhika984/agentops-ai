"""create agent registry

Revision ID: 202609160001
Revises: 202608220001
Create Date: 2026-09-16 00:00:00.000000

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "202609160001"
down_revision = "202608220001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agents",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "default_expected_behavior", postgresql.ARRAY(sa.Text()), nullable=True
        ),
        sa.Column(
            "default_forbidden_behavior", postgresql.ARRAY(sa.Text()), nullable=True
        ),
        sa.Column(
            "default_output_schema", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("default_latency_threshold_ms", sa.Integer(), nullable=True),
        sa.Column("default_allowed_tools", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("default_required_tools", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column(
            "min_call_interval_ms", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "default_timeout_ms", sa.Integer(), server_default=sa.text("30000"), nullable=False
        ),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agents")),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_agents_project_id_projects"),
            ondelete="CASCADE",
        ),
    )
    op.create_index(op.f("ix_agents_project_id"), "agents", ["project_id"], unique=False)

    op.create_table(
        "agent_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("label", sa.String(length=100), nullable=False),
        sa.Column("adapter_type", sa.String(length=20), nullable=False),
        sa.Column(
            "adapter_config", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("observability_level", sa.SmallInteger(), nullable=False),
        sa.Column(
            "is_baseline", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_versions")),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            name=op.f("fk_agent_versions_agent_id_agents"),
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "agent_id", "label", name="uq_agent_versions_agent_id_label"
        ),
        sa.CheckConstraint(
            "adapter_type IN ('http', 'local')", name="ck_agent_versions_adapter_type"
        ),
        sa.CheckConstraint(
            "observability_level BETWEEN 1 AND 4",
            name="ck_agent_versions_observability_level",
        ),
    )
    op.create_index(
        op.f("ix_agent_versions_agent_id"), "agent_versions", ["agent_id"], unique=False
    )
    # Exactly one baseline version per agent — enforced by the database
    # itself, not only by application code (see the locked audit §7/§23
    # and app/models/agent_version.py's docstring).
    op.create_index(
        "ix_agent_versions_one_baseline_per_agent",
        "agent_versions",
        ["agent_id"],
        unique=True,
        postgresql_where=sa.text("is_baseline"),
    )


def downgrade() -> None:
    op.drop_index("ix_agent_versions_one_baseline_per_agent", table_name="agent_versions")
    op.drop_index(op.f("ix_agent_versions_agent_id"), table_name="agent_versions")
    op.drop_table("agent_versions")
    op.drop_index(op.f("ix_agents_project_id"), table_name="agents")
    op.drop_table("agents")
