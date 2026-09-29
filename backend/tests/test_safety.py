"""Phase 7 safety.py tests.

Per the blueprint's two-tier policy design: deterministic deny/review
patterns are checked first (no model call at all — verified here by never
mocking call_model in the deny-tier and clean-input tests, so a stray real
call would surface as a slow/failing test); the LLM classifier is only
exercised for review-tier matches, and is mocked here at the
app.agents.safety.call_model seam (matching every other test file's
pattern for this project) so these tests stay fast, deterministic, and
network-free. app.ai.client.AIClientError is used directly (rather than a
stub) to prove the fail-closed path reacts to the same exception type
call_model actually raises.
"""

from __future__ import annotations

import pytest

from app.agents import safety
from app.agents.schemas import SafetyClassification
from app.ai.client import AIClientError

pytestmark = pytest.mark.anyio


# ---- deny tier: deterministic, no model call ----


async def test_deny_pattern_blocks_destructive_shell_command() -> None:
    result = await safety.check_tool_call(
        "run_python", {"code": "import os; os.system('rm -rf /')"}
    )

    assert result.allowed is False
    assert result.type == "destructive_filesystem"
    assert result.used_llm_fallback is False


async def test_deny_pattern_blocks_drop_table() -> None:
    result = await safety.check_tool_call("run_python", {"code": "DROP TABLE users;"})

    assert result.allowed is False
    assert result.type == "destructive_database"
    assert result.used_llm_fallback is False


async def test_deny_pattern_blocks_credential_leak() -> None:
    result = await safety.check_tool_call(
        "web_search", {"query": "api_key: sk-abc123 for the prod service"}
    )

    assert result.allowed is False
    assert result.type == "credential_leak"
    assert result.used_llm_fallback is False


# ---- clean input: allowed with no model call ----


async def test_benign_call_is_allowed_without_llm_fallback() -> None:
    result = await safety.check_tool_call("web_search", {"query": "weather in Tokyo tomorrow"})

    assert result.allowed is True
    assert result.used_llm_fallback is False


# ---- review tier: ambiguous match triggers the LLM fallback ----


async def test_review_pattern_allowed_when_llm_says_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_call_model(
        prompt: str, schema: type[SafetyClassification], **kwargs: object
    ) -> SafetyClassification:
        return SafetyClassification(allowed=True, reason="Harmless tutorial context.")

    monkeypatch.setattr(safety, "call_model", fake_call_model)

    result = await safety.check_tool_call(
        "web_search", {"query": "how to hack together a quick prototype this weekend"}
    )

    assert result.allowed is True
    assert result.used_llm_fallback is True


async def test_review_pattern_denied_when_llm_says_unsafe(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_call_model(
        prompt: str, schema: type[SafetyClassification], **kwargs: object
    ) -> SafetyClassification:
        return SafetyClassification(allowed=False, reason="Describes a real intrusion attempt.")

    monkeypatch.setattr(safety, "call_model", fake_call_model)

    result = await safety.check_tool_call("web_search", {"query": "how to hack a website"})

    assert result.allowed is False
    assert result.type == "possible_malicious_intent"
    assert result.used_llm_fallback is True


async def test_review_pattern_fails_closed_when_llm_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_call_model_raises(
        prompt: str, schema: type[SafetyClassification], **kwargs: object
    ) -> SafetyClassification:
        raise AIClientError("model unavailable")

    monkeypatch.setattr(safety, "call_model", fake_call_model_raises)

    result = await safety.check_tool_call("web_search", {"query": "bypass security on my router"})

    assert result.allowed is False
    assert result.used_llm_fallback is True
    assert "denied by default" in (result.reason or "")
