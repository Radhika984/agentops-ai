"""create activity events and api keys, add user notification prefs

Revision ID: 202609260001
Revises: 202609200001
Create Date: 2026-09-26 00:00:00.000000

Hand-written (not left as `alembic revision --autogenerate`'s raw output):
autogenerate also proposed dropping `ix_embeddings_vector_cosine` — a
false positive. That index is a raw-SQL pgvector ivfflat index created
directly in 202608190001_create_embeddings.py's upgrade() (`op.execute(...)`,
not a declarative Column/Index SQLAlchemy can represent), so autogenerate's
diff sees "an index Base.metadata doesn't know about" and proposes removing
it — which would be a real, destructive, unrelated regression to Phase 6's
embeddings feature. This migration only contains the two new tables and
the four new user columns actually intended here.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "202609260001"
down_revision = "202609200001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "activity_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("entity_type", sa.String(length=50), nullable=True),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("event_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_activity_events")),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["users.id"],
            name=op.f("fk_activity_events_owner_id_users"),
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        op.f("ix_activity_events_owner_id"), "activity_events", ["owner_id"], unique=False
    )
    op.create_index(
        op.f("ix_activity_events_created_at"), "activity_events", ["created_at"], unique=False
    )

    op.create_table(
        "api_keys",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("key_prefix", sa.String(length=12), nullable=False),
        sa.Column("hashed_key", sa.String(length=255), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_api_keys")),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["users.id"],
            name=op.f("fk_api_keys_owner_id_users"),
            ondelete="CASCADE",
        ),
    )
    op.create_index(op.f("ix_api_keys_owner_id"), "api_keys", ["owner_id"], unique=False)

    op.add_column(
        "users",
        sa.Column(
            "notify_on_suite_run_complete",
            sa.Boolean(),
            nullable=False,
            server_default="true",
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "notify_on_release_gate", sa.Boolean(), nullable=False, server_default="true"
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "notify_on_autofix_proposed", sa.Boolean(), nullable=False, server_default="true"
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "notify_on_approval_decided", sa.Boolean(), nullable=False, server_default="true"
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "notify_on_approval_decided")
    op.drop_column("users", "notify_on_autofix_proposed")
    op.drop_column("users", "notify_on_release_gate")
    op.drop_column("users", "notify_on_suite_run_complete")

    op.drop_index(op.f("ix_api_keys_owner_id"), table_name="api_keys")
    op.drop_table("api_keys")

    op.drop_index(op.f("ix_activity_events_created_at"), table_name="activity_events")
    op.drop_index(op.f("ix_activity_events_owner_id"), table_name="activity_events")
    op.drop_table("activity_events")
