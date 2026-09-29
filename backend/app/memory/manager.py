"""Read/write API used by all agent nodes.

Per the blueprint: "The Memory Manager is not a graph node in the
execution path — it's a shared service every node can call, so it doesn't
block the critical path." Concretely, that means it manages its own DB
session internally (like services/run_service.py's background task does)
rather than requiring every caller to plumb one through — any node, or
any future agent, can call remember()/recall() directly with no session
setup, which is what makes it "agent-agnostic" per the Definition of
Done ("adding a new tool doesn't require touching agent node code" — same
principle as Phase 5's tool registry, applied to memory).

Short-term memory: this module only covers *long-term* (cross-run)
memory. Per-run scratch memory is already AgentState itself (Phase 4) —
it lives only for the duration of one graph.ainvoke() call, which is
exactly what "short-term, per-run scratch" means. The blueprint's Part 1
architecture table also names Redis for short-term storage, but Redis is
explicitly introduced in Phase 8 ("Routing, Cost, Caching") per the
Master Roadmap Table and the blueprint's own rule ("a technology appears
in the phase where it first solves a real problem, never earlier") — there
is no real problem here that AgentState doesn't already solve, so Redis
is deliberately not introduced in this phase.
"""

from __future__ import annotations

import logging
import uuid

from app.db.session import AsyncSessionLocal
from app.memory.embeddings import AIClientError, embed_text
from app.memory.retrieval import find_similar, store_embedding

logger = logging.getLogger(__name__)


async def remember(*, content: str, source_type: str, source_id: uuid.UUID | None = None) -> None:
    """Embeds `content` and stores it as long-term memory.

    Never raises: a memory write failing (e.g. no API key configured, or
    a transient embedding-provider error) must not fail whatever run
    triggered it — see run_service.py, which calls this after a run's
    state is already durably persisted.
    """
    try:
        vector = await embed_text(content)
    except AIClientError:
        logger.exception("remember(): failed to embed content, memory not stored")
        return

    async with AsyncSessionLocal() as session:
        await store_embedding(
            session, content=content, vector=vector, source_type=source_type, source_id=source_id
        )
        await session.commit()


async def recall(query: str, *, source_type: str | None = None, top_k: int = 3) -> list[str]:
    """Returns up to `top_k` pieces of past content most relevant to
    `query`, most relevant first. Returns an empty list (never raises) if
    embedding fails or nothing sufficiently relevant is found — callers
    treat memory as optional context, same as Phase 5's search tool.
    """
    try:
        query_vector = await embed_text(query)
    except AIClientError:
        logger.exception("recall(): failed to embed query, returning no memory")
        return []

    async with AsyncSessionLocal() as session:
        matches = await find_similar(
            session, query_vector, source_type=source_type, top_k=top_k
        )

    return [match.content for match in matches]
