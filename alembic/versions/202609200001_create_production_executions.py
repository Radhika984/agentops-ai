"""create production_executions and add test_cases candidate status

Revision ID: 202609200001
Revises: 202609190001
Create Date: 2026-09-20 00:00:00.000000

Phase 20: post-release execution ingestion/monitoring.

  - `production_executions`: one row per ingested post-release execution
    (agent_version_id, external_execution_id) unique for idempotent
    ingestion — see app/models/production_execution.py.
  - `test_cases.status` / `test_cases.source_execution_id`: additive
    columns so a real production failure can be proposed as a
    `candidate` TestCase (excluded from Suite Runner execution until a
    human accepts it) without a second, parallel TestCase-like table.
    `status` defaults to 'active' for every existing row, so no
    pre-Phase-20 TestCase or Suite Runner behavior changes.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "202609200001"
down_revision = "202609190001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "production_executions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("external_execution_id", sa.String(length=255), nullable=False),
        sa.Column("input", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("actual_output", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "tool_calls",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'"),
            nullable=False,
        ),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("reference_context", sa.Text(), nullable=True),
        sa.Column("trace", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("verdict", sa.String(length=20), nullable=False),
        sa.Column(
            "checks",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_production_executions")),
        sa.ForeignKeyConstraint(
            ["agent_version_id"],
            ["agent_versions.id"],
            name=op.f("fk_production_executions_agent_version_id_agent_versions"),
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "agent_version_id",
            "external_execution_id",
            name="uq_production_executions_agent_version_id_external_execution_id",
        ),
        sa.CheckConstraint(
            "verdict IN ('PASS', 'FAIL', 'INCONCLUSIVE')",
            name="ck_production_executions_verdict",
        ),
    )
    op.create_index(
        op.f("ix_production_executions_agent_version_id"),
        "production_executions",
        ["agent_version_id"],
        unique=False,
    )

    op.add_column(
        "test_cases",
        sa.Column("status", sa.String(length=20), server_default="active", nullable=False),
    )
    op.add_column(
        "test_cases",
        sa.Column("source_execution_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_test_cases_status", "test_cases", "status IN ('active', 'candidate')"
    )
    op.create_foreign_key(
        op.f("fk_test_cases_source_execution_id_production_executions"),
        "test_cases",
        "production_executions",
        ["source_execution_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_test_cases_source_execution_id_production_executions"),
        "test_cases",
        type_="foreignkey",
    )
    op.drop_constraint("ck_test_cases_status", "test_cases", type_="check")
    op.drop_column("test_cases", "source_execution_id")
    op.drop_column("test_cases", "status")

    op.drop_index(
        op.f("ix_production_executions_agent_version_id"), table_name="production_executions"
    )
    op.drop_table("production_executions")
