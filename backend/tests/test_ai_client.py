"""Phase 2.3 / Phase 8 AI client tests.

Phase 8 rewrite: call_model() no longer talks to google.genai directly —
it goes through app/ai/router.py. These tests mock `ai_client.router` at
the same seam call_model() actually calls (`router.route_completion`), not
litellm/network — no GEMINI_API_KEY, no network access, no real model
call. `_log_model_call` (a real DB write against whatever AsyncSessionLocal
happens to point at) is mocked to a no-op in every test here: this file
intentionally stays a pure, DB-free unit test file, matching its pre
-Phase-8 shape — model_calls' real persistence is covered by
tests/test_runs.py (via the full authenticated /runs flow) instead.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from app.ai import client as ai_client
from app.ai.client import (
    MissingAPIKeyError,
    ModelOutputValidationError,
    ModelUnavailableError,
    call_model,
)
from app.ai.router import AllModelsFailedError, RouteResult
from app.ai.schemas import AnswerResponse
from app.core.config import settings

VALID_PAYLOAD = json.dumps({"answer": "Paris is the capital of France.", "confidence": 0.9})
INVALID_PAYLOAD = "this is not valid json"


class _FakeRouter:
    """Fakes the subset of app.ai.router used by call_model."""

    def __init__(self, outputs: list[str]) -> None:
        self._outputs = list(outputs)
        self.call_count = 0
        self.calls: list[dict[str, Any]] = []

    async def route_completion(self, prompt: str, *, model_group: str) -> RouteResult:
        self.call_count += 1
        self.calls.append({"prompt": prompt, "model_group": model_group})
        output_text = self._outputs.pop(0)
        return RouteResult(
            text=output_text, model="gemini-3.5-flash-lite", tokens_in=10, tokens_out=10, cost=0.0
        )


class _FakeFailingRouter:
    """Fakes every model in the group failing."""

    def __init__(self) -> None:
        self.call_count = 0

    async def route_completion(self, prompt: str, *, model_group: str) -> RouteResult:
        self.call_count += 1
        raise AllModelsFailedError("all models failed")


async def _noop_log_model_call(**kwargs: object) -> None:
    return None


def _install_fake_router(monkeypatch: pytest.MonkeyPatch, outputs: list[str]) -> _FakeRouter:
    fake_router = _FakeRouter(outputs)
    monkeypatch.setattr(ai_client.router, "route_completion", fake_router.route_completion)
    monkeypatch.setattr(ai_client, "_log_model_call", _noop_log_model_call)
    return fake_router


async def test_successful_first_attempt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-key")
    fake_router = _install_fake_router(monkeypatch, [VALID_PAYLOAD])

    result = await call_model("What is the capital of France?", AnswerResponse)

    assert fake_router.call_count == 1
    assert isinstance(result, AnswerResponse)
    assert result.answer == "Paris is the capital of France."
    assert result.confidence == 0.9


async def test_invalid_then_valid_retries_once(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-key")
    fake_router = _install_fake_router(monkeypatch, [INVALID_PAYLOAD, VALID_PAYLOAD])

    result = await call_model("What is the capital of France?", AnswerResponse)

    assert fake_router.call_count == 2
    assert isinstance(result, AnswerResponse)
    assert result.answer == "Paris is the capital of France."


async def test_invalid_twice_raises_after_exactly_two_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-key")
    fake_router = _install_fake_router(monkeypatch, [INVALID_PAYLOAD, INVALID_PAYLOAD])

    with pytest.raises(ModelOutputValidationError):
        await call_model("What is the capital of France?", AnswerResponse)

    assert fake_router.call_count == 2


async def test_missing_api_key_raises_without_calling_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "GEMINI_API_KEY", None)
    fake_router = _install_fake_router(monkeypatch, [VALID_PAYLOAD])

    with pytest.raises(MissingAPIKeyError):
        await call_model("What is the capital of France?", AnswerResponse)

    assert fake_router.call_count == 0


async def test_returned_value_is_a_validated_answer_response_instance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-key")
    _install_fake_router(monkeypatch, [VALID_PAYLOAD])

    result = await call_model("What is the capital of France?", AnswerResponse)

    assert isinstance(result, AnswerResponse)
    assert not isinstance(result, dict)
    assert not isinstance(result, str)
    assert 0.0 <= result.confidence <= 1.0


# ---- Phase 8: router-layer failures surface as an AIClientError subclass ----


async def test_all_models_failing_raises_model_unavailable_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Proves router.AllModelsFailedError is translated into
    ModelUnavailableError (an AIClientError subclass) — not left as a raw
    router-layer exception — so Safety/Hallucination's existing `except
    AIClientError` fail-closed/fail-open handling actually catches a
    genuine "every model unavailable" failure, not just MissingAPIKeyError.
    """
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-key")
    fake_router = _FakeFailingRouter()
    monkeypatch.setattr(ai_client.router, "route_completion", fake_router.route_completion)
    monkeypatch.setattr(ai_client, "_log_model_call", _noop_log_model_call)

    with pytest.raises(ModelUnavailableError):
        await call_model("What is the capital of France?", AnswerResponse)

    assert fake_router.call_count == 1


# ---- Phase 8: the Redis cache ----


async def test_cache_hit_skips_the_actual_model_call(monkeypatch: pytest.MonkeyPatch) -> None:
    """Per the blueprint: 'unit tests confirming cache hits skip the
    actual model call.' Uses an in-memory fake cache (not real Redis —
    that's covered live, see app/ai/cache.py's docstring) so this stays a
    pure, network-free unit test."""
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-key")
    fake_router = _install_fake_router(monkeypatch, [VALID_PAYLOAD])

    store: dict[str, str] = {}

    async def fake_get_cached(key: str) -> str | None:
        return store.get(key)

    async def fake_set_cached(key: str, value: str, **kwargs: object) -> None:
        store[key] = value

    monkeypatch.setattr(ai_client.cache, "get_cached", fake_get_cached)
    monkeypatch.setattr(ai_client.cache, "set_cached", fake_set_cached)

    # First call: a real cache miss — goes through the router, then writes
    # the cache entry.
    first = await call_model(
        "What is the capital of France?", AnswerResponse, cacheable=True
    )
    assert fake_router.call_count == 1
    assert isinstance(first, AnswerResponse)

    # Second, identical call: must be served from the cache — the router
    # is never called again.
    second = await call_model(
        "What is the capital of France?", AnswerResponse, cacheable=True
    )
    assert fake_router.call_count == 1
    assert second.answer == first.answer


async def test_non_cacheable_calls_never_touch_the_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-key")
    _install_fake_router(monkeypatch, [VALID_PAYLOAD, VALID_PAYLOAD])

    async def fail_if_called(*args: object, **kwargs: object) -> None:
        raise AssertionError("cache must not be consulted for a non-cacheable call")

    monkeypatch.setattr(ai_client.cache, "get_cached", fail_if_called)
    monkeypatch.setattr(ai_client.cache, "set_cached", fail_if_called)

    await call_model("What is the capital of France?", AnswerResponse)  # cacheable defaults False
