"""text -> vector.

Reuses the same Gemini Developer API key/provider as app/ai/client.py, but
a separate, smaller/cheaper model (GEMINI_EMBEDDING_MODEL) — per the
blueprint's "Embeddings model (small/cheap, separate from the reasoning
model)". Requests a reduced 768-dimension output (the model's native size
is 3072) — smaller vectors are what pgvector's HNSW index is built against
here (see the embeddings migration), and keep storage/query cost down.

Note: Gemini's reduced-dimension embeddings are not unit-length (only the
native 3072-dim output is pre-normalized), so they must always be compared
with cosine distance, never plain dot product or L2 — cosine similarity is
scale-invariant, so this doesn't require normalizing the vectors
ourselves. memory/retrieval.py's query and the embeddings migration's
index are both built on cosine distance for exactly this reason.
"""

from __future__ import annotations

from google.genai import Client, types

from app.ai.client import AIClientError, MissingAPIKeyError
from app.core.config import settings
from app.models.embedding import EMBEDDING_DIMENSIONS

__all__ = ["AIClientError", "MissingAPIKeyError", "embed_text"]


async def embed_text(text: str) -> list[float]:
    """Embeds `text` into a 768-dimension vector.

    Raises MissingAPIKeyError if GEMINI_API_KEY is not configured — the
    application must still start and existing functionality must still
    work without one, matching app/ai/client.py's contract.
    """
    if not settings.GEMINI_API_KEY:
        raise MissingAPIKeyError("GEMINI_API_KEY is not configured; cannot embed text.")

    client = Client(api_key=settings.GEMINI_API_KEY)
    result = await client.aio.models.embed_content(
        model=settings.GEMINI_EMBEDDING_MODEL,
        contents=text,
        config=types.EmbedContentConfig(output_dimensionality=EMBEDDING_DIMENSIONS),
    )

    if not result.embeddings:
        raise AIClientError("Embedding response contained no embeddings.")

    values = result.embeddings[0].values
    if values is None:
        raise AIClientError("Embedding response contained no vector values.")

    return list(values)
