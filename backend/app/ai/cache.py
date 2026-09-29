"""Redis-backed response cache for read-only/judgment-style model calls.

Per the blueprint's own "Common Mistakes" warning for this phase — "caching
non-idempotent or time-sensitive calls" — only calls whose "correct" answer
is a genuine function of their input, not of when/how many times they're
run, are ever cached here. Concretely: Safety's LLM-fallback classification
and Hallucination's entailment check (both "judgment" group, both pure
input->verdict classification) opt into caching via call_model()'s
`cacheable` flag; Planner's plan generation and /ask's free-form answers
(both "reasoning" group, both intentionally generative) never do.

Fails open: any Redis error (connection refused, timeout, etc.) is treated
as a cache miss / a no-op write, never surfaced to the caller — the same
fail-open contract as every other optional-infrastructure dependency in
this project (Hallucination on a down model, Safety's LLM fallback,
memory.manager on a down embedding call). A cache outage must degrade to
"every call goes to the model", never break the app.
"""

from __future__ import annotations

import hashlib
import logging

from redis.asyncio import Redis

from app.core.config import settings

logger = logging.getLogger(__name__)

_DEFAULT_TTL_SECONDS = 3600

_redis: Redis | None = None


def _client() -> Redis:
    global _redis
    if _redis is None:
        _redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis


def cache_key(model_group: str, prompt: str) -> str:
    """A deterministic key covering both the model group and the full
    prompt text — per the blueprint's other warning ("cache keys that
    don't include enough context"), the *entire* rendered prompt is
    hashed (not e.g. just the goal/claim being checked), so any change to
    context, instructions, or template automatically produces a different
    key rather than serving a stale answer for a subtly different input.
    """
    digest = hashlib.sha256(f"{model_group}:{prompt}".encode()).hexdigest()
    return f"agentops:model-cache:{digest}"


async def get_cached(key: str) -> str | None:
    try:
        value: str | None = await _client().get(key)
    except Exception:  # noqa: BLE001
        logger.warning("Redis cache read failed; treating as a cache miss.", exc_info=True)
        return None
    return value


async def set_cached(key: str, value: str, *, ttl_seconds: int = _DEFAULT_TTL_SECONDS) -> None:
    try:
        await _client().set(key, value, ex=ttl_seconds)
    except Exception:  # noqa: BLE001
        logger.warning("Redis cache write failed; continuing without caching.", exc_info=True)


async def close() -> None:
    """Called from the app lifespan on shutdown — mirrors
    app/tools/mcp_client.py's shutdown() pattern from Phase 5/7 (closing
    a cached async client explicitly instead of leaving it to a
    no-event-loop-left garbage collection)."""
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None
