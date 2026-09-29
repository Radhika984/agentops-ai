"""create suite_runs and test_case_results

Revision ID: 202609180001
Revises: 202609170001
Create Date: 2026-09-18 00:00:00.000000

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "202609180001"
down_revision = "202609170001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "suite_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("suite_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pass_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("fail_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "inconclusive_count", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("skipped_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "llm_judge_invocation_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("max_concurrency", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_suite_runs")),
        sa.ForeignKeyConstraint(
            ["suite_id"],
            ["test_suites.id"],
            name=op.f("fk_suite_runs_suite_id_test_suites"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["agent_version_id"],
            ["agent_versions.id"],
            name=op.f("fk_suite_runs_agent_version_id_agent_versions"),
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'cancelling', 'completed', 'failed')",
            name="ck_suite_runs_status",
        ),
        sa.CheckConstraint("max_concurrency >= 1", name="ck_suite_runs_max_concurrency"),
    )
    op.create_index(op.f("ix_suite_runs_suite_id"), "suite_runs", ["suite_id"], unique=False)
    op.create_index(
        op.f("ix_suite_runs_agent_version_id"), "suite_runs", ["agent_version_id"], unique=False
    )

    op.create_table(
        "test_case_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("suite_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("test_case_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("verdict", sa.String(length=20), nullable=False),
        sa.Column(
            "verdict_method", sa.String(length=20), server_default="majority", nullable=False
        ),
        sa.Column("checks", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "trials",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'"),
            nullable=False,
        ),
        sa.Column("actual_output", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("suggested_fix", sa.Text(), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_test_case_results")),
        sa.ForeignKeyConstraint(
            ["suite_run_id"],
            ["suite_runs.id"],
            name=op.f("fk_test_case_results_suite_run_id_suite_runs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["test_case_id"],
            ["test_cases.id"],
            name=op.f("fk_test_case_results_test_case_id_test_cases"),
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "suite_run_id",
            "test_case_id",
            name="uq_test_case_results_suite_run_id_test_case_id",
        ),
        sa.CheckConstraint(
            "verdict IN ('PASS', 'FAIL', 'INCONCLUSIVE')", name="ck_test_case_results_verdict"
        ),
    )
    op.create_index(
        op.f("ix_test_case_results_suite_run_id"), "test_case_results", ["suite_run_id"], unique=False
    )
    op.create_index(
        op.f("ix_test_case_results_test_case_id"), "test_case_results", ["test_case_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_test_case_results_test_case_id"), table_name="test_case_results")
    op.drop_index(op.f("ix_test_case_results_suite_run_id"), table_name="test_case_results")
    op.drop_table("test_case_results")
    op.drop_index(op.f("ix_suite_runs_agent_version_id"), table_name="suite_runs")
    op.drop_index(op.f("ix_suite_runs_suite_id"), table_name="suite_runs")
    op.drop_table("suite_runs")
