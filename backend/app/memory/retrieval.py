"""Vector similarity query against pgvector.

Cosine distance throughout (see embeddings.py's docstring for why) via
pgvector's `<=>` operator, exposed by the pgvector SQLAlchemy type as
`.cosine_distance()`. A max-distance threshold filters out results that
are merely the "least dissimilar" of an unrelated set — without it,
top-k always returns k rows even when nothing in the table is actually
relevant to the query (see the blueprint's Manual Testing Checklist: "An
unrelated goal does not pull in irrelevant memory").
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.embedding import Embedding

# Cosine distance ranges from 0 (identical) to 2 (opposite), with 1
# meaning "orthogonal" in the textbook sense — but that doesn't predict
# where real goal-description embeddings actually land. Measured directly
# (see Phase 6 Definition of Done: "retrieval quality manually spot-checked
# against at least 10 example queries") across 8 goals / 13 pairs with
# Gemini's embedding model: same-topic pairs ("plan a birthday party for a
# 10 year old" vs "...12 year old") landed at ~0.12-0.33, while every
# genuinely unrelated pair (party planning vs C++ debugging, a recipe vs a
# resume, etc.) landed at 0.44-0.57 — clustered well short of 1.0, not
# spread across the full range. 0.6 (the textbook-plausible first guess)
# was too loose and let an unrelated goal retrieve irrelevant memory in
# live testing; 0.4 is the threshold that actually separates the two
# clusters observed.
DEFAULT_MAX_DISTANCE = 0.4


async def find_similar(
    session: AsyncSession,
    query_vector: list[float],
    *,
    source_type: str | None = None,
    top_k: int = 3,
    max_distance: float = DEFAULT_MAX_DISTANCE,
) -> list[Embedding]:
    """Returns up to `top_k` embeddings most similar to `query_vector`,
    excluding anything farther than `max_distance` (cosine distance).
    Optionally restricted to one `source_type`.
    """
    distance = Embedding.vector.cosine_distance(query_vector)

    stmt = select(Embedding).where(distance < max_distance).order_by(distance).limit(top_k)
    if source_type is not None:
        stmt = stmt.where(Embedding.source_type == source_type)

    result = await session.execute(stmt)
    return list(result.scalars().all())


async def store_embedding(
    session: AsyncSession,
    *,
    content: str,
    vector: list[float],
    source_type: str,
    source_id: uuid.UUID | None = None,
) -> Embedding:
    embedding = Embedding(
        content=content, vector=vector, source_type=source_type, source_id=source_id
    )
    session.add(embedding)
    await session.flush()
    await session.refresh(embedding)
    return embedding
