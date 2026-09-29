"""create embeddings

Revision ID: 202608190001
Revises: 202608180001
Create Date: 2026-08-19 00:00:00.000000

"""
from __future__ import annotations

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "202608190001"
down_revision = "202608180001"
branch_labels = None
depends_on = None

# Must match app/models/embedding.py's EMBEDDING_DIMENSIONS.
EMBEDDING_DIMENSIONS = 768


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "embeddings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("vector", pgvector.sqlalchemy.Vector(EMBEDDING_DIMENSIONS), nullable=False),
        sa.Column("source_type", sa.String(length=50), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_embeddings")),
    )
    op.create_index(
        op.f("ix_embeddings_source_type"), "embeddings", ["source_type"], unique=False
    )
    # HNSW, not IVFFlat: no training/list-count tuning required, and this
    # table starts empty — IVFFlat's recommended list count depends on
    # already knowing the row count. Cosine distance to match how
    # memory/retrieval.py queries (matters because Gemini's embeddings are
    # only comparable by cosine similarity when a reduced output
    # dimensionality is requested — see memory/embeddings.py).
    op.execute(
        "CREATE INDEX ix_embeddings_vector_cosine ON embeddings "
        "USING hnsw (vector vector_cosine_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_embeddings_vector_cosine")
    op.drop_index(op.f("ix_embeddings_source_type"), table_name="embeddings")
    op.drop_table("embeddings")
    op.execute("DROP EXTENSION IF EXISTS vector")
