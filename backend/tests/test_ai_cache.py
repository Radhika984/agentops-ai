"""Phase 8 ai/cache.py tests.

Redis itself is mocked here (no real Redis connection, no network) — the
real, live Redis round trip is verified manually against the Docker
Redis container (see the Phase 8 completion report's Manual Testing
Checklist), matching how this project treats every other "real external
service" verification (real DuckDuckGo, real Gemini API) as a live
smoke test, not an automated one. These tests instead verify cache.py's
own logic: deterministic key generation, and the fail-open contract
(never raise on a Redis error) documented in its own module docstring.
"""

from __future__ import annotations

import pytest

from app.ai import cache

pytestmark = pytest.mark.anyio


def test_cache_key_is_deterministic() -> None:
    key1 = cache.cache_key("judgment", "some prompt text")
    key2 = cache.cache_key("judgment", "some prompt text")

    assert key1 == key2


def test_cache_key_differs_by_model_group() -> None:
    assert cache.cache_key("reasoning", "same prompt") != cache.cache_key(
        "judgment", "same prompt"
    )


def test_cache_key_differs_by_prompt() -> None:
    assert cache.cache_key("judgment", "prompt A") != cache.cache_key("judgment", "prompt B")


class _RaisingRedis:
    async def get(self, key: str) -> str:
        raise ConnectionError("simulated Redis outage")

    async def set(self, key: str, value: str, ex: int) -> None:
        raise ConnectionError("simulated Redis outage")


async def test_get_cached_fails_open_on_redis_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cache, "_client", lambda: _RaisingRedis())

    result = await cache.get_cached("some-key")

    assert result is None


async def test_set_cached_fails_open_on_redis_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cache, "_client", lambda: _RaisingRedis())

    # Must not raise.
    await cache.set_cached("some-key", "some-value")


class _FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.last_ttl: int | None = None

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def set(self, key: str, value: str, ex: int) -> None:
        self.store[key] = value
        self.last_ttl = ex


async def test_set_then_get_round_trips_through_the_client(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_redis = _FakeRedis()
    monkeypatch.setattr(cache, "_client", lambda: fake_redis)

    await cache.set_cached("k", "v", ttl_seconds=42)

    assert await cache.get_cached("k") == "v"
    assert fake_redis.last_ttl == 42
