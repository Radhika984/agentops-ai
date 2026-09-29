"""create test_suites and test_cases

Revision ID: 202609170001
Revises: 202609160001
Create Date: 2026-09-17 00:00:00.000000

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "202609170001"
down_revision = "202609160001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "test_suites",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_test_suites")),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            name=op.f("fk_test_suites_agent_id_agents"),
            ondelete="CASCADE",
        ),
    )
    op.create_index(op.f("ix_test_suites_agent_id"), "test_suites", ["agent_id"], unique=False)

    op.create_table(
        "test_cases",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("suite_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("input", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("history", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("reference_context", sa.Text(), nullable=True),
        sa.Column("expected_output", sa.Text(), nullable=True),
        sa.Column("assertions", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "expected_tool_calls", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("rubric", sa.Text(), nullable=True),
        sa.Column("expected_behavior", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("forbidden_behavior", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("allowed_tools", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column(
            "output_schema", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("latency_threshold_ms", sa.Integer(), nullable=True),
        sa.Column(
            "rubric_threshold", sa.Float(), server_default=sa.text("0.7"), nullable=False
        ),
        sa.Column("trial_count", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "tags", postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'"), nullable=False
        ),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_test_cases")),
        sa.ForeignKeyConstraint(
            ["suite_id"],
            ["test_suites.id"],
            name=op.f("fk_test_cases_suite_id_test_suites"),
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("trial_count >= 1", name="ck_test_cases_trial_count"),
        sa.CheckConstraint(
            "rubric_threshold >= 0 AND rubric_threshold <= 1",
            name="ck_test_cases_rubric_threshold",
        ),
        sa.CheckConstraint(
            "latency_threshold_ms IS NULL OR latency_threshold_ms > 0",
            name="ck_test_cases_latency_threshold_ms",
        ),
    )
    op.create_index(op.f("ix_test_cases_suite_id"), "test_cases", ["suite_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_test_cases_suite_id"), table_name="test_cases")
    op.drop_table("test_cases")
    op.drop_index(op.f("ix_test_suites_agent_id"), table_name="test_suites")
    op.drop_table("test_suites")
