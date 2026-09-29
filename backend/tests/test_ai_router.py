"""Phase 8 ai/router.py tests.

litellm.acompletion is mocked here (no network access, no real
GEMINI_API_KEY) at the seam route_completion() actually calls — these
tests are what prove the fallback loop itself (not call_model()'s
retry-on-invalid-JSON layer, covered separately in test_ai_client.py)
actually tries the next model in a group's priority list when an earlier
one fails, per the blueprint's "unit tests confirming fallback triggers
on a simulated primary-model failure."
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.ai import router
from app.core.config import settings

pytestmark = pytest.mark.anyio


def _fake_response(text: str, *, cost: float = 0.0001) -> MagicMock:
    response = MagicMock()
    response.choices = [MagicMock(message=MagicMock(content=text))]
    response.usage = MagicMock(prompt_tokens=5, completion_tokens=7)
    response._hidden_params = {"response_cost": cost}
    return response


async def test_route_completion_uses_the_primary_model_on_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    async def fake_acompletion(*, model: str, **kwargs: Any) -> MagicMock:
        calls.append(model)
        return _fake_response('{"ok": true}')

    monkeypatch.setattr(router.litellm, "acompletion", fake_acompletion)

    result = await router.route_completion("hello", model_group="reasoning")

    assert calls == [f"gemini/{settings.GEMINI_MODEL}"]
    assert result.text == '{"ok": true}'
    assert result.model == settings.GEMINI_MODEL
    assert result.tokens_in == 5
    assert result.tokens_out == 7
    assert result.cost == 0.0001


async def test_route_completion_falls_back_to_the_secondary_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Simulates a primary-model outage — proves the caller never sees
    the failure, and gets the secondary model's real result instead."""
    calls: list[str] = []

    async def fake_acompletion(*, model: str, **kwargs: Any) -> MagicMock:
        calls.append(model)
        if model == f"gemini/{settings.GEMINI_MODEL}":
            raise RuntimeError("simulated primary model outage")
        return _fake_response('{"ok": true}')

    monkeypatch.setattr(router.litellm, "acompletion", fake_acompletion)

    result = await router.route_completion("hello", model_group="reasoning")

    assert calls == [f"gemini/{settings.GEMINI_MODEL}", f"gemini/{settings.GEMINI_FALLBACK_MODEL}"]
    assert result.model == settings.GEMINI_FALLBACK_MODEL
    assert result.text == '{"ok": true}'


async def test_route_completion_raises_when_every_model_in_the_group_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_acompletion = AsyncMock(side_effect=RuntimeError("simulated total outage"))
    monkeypatch.setattr(router.litellm, "acompletion", fake_acompletion)

    with pytest.raises(router.AllModelsFailedError):
        await router.route_completion("hello", model_group="reasoning")

    assert fake_acompletion.await_count == len(router.MODEL_GROUPS["reasoning"])


async def test_route_completion_unknown_group_raises_key_error() -> None:
    with pytest.raises(KeyError):
        await router.route_completion("hello", model_group="not-a-real-group")
