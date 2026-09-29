"""Phase 9 agents/root_cause_analysis.py tests.

call_model() and memory_manager.recall()/remember() are mocked at the
same seams every other agent-node test file uses (matching
tests/test_agents.py/test_safety.py) — no network, no real model call,
no real DB.
"""

from __future__ import annotations

import pytest

from app.agents import root_cause_analysis as rca_mod
from app.agents.root_cause_analysis import WHITELISTED_PATTERN_TOO_FEW_TASKS, analyze_failure
from app.agents.schemas import RootCauseHypothesis
from app.agents.state import FlagRecord, ToolCallRecord
from app.ai.client import AIClientError

pytestmark = pytest.mark.anyio


async def _fake_recall_empty(
    query: str, *, source_type: str | None = None, top_k: int = 3
) -> list[str]:
    return []


async def _fake_remember_noop(
    *, content: str, source_type: str, source_id: object | None = None
) -> None:
    return None


@pytest.fixture(autouse=True)
def _mock_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rca_mod.memory_manager, "recall", _fake_recall_empty)
    monkeypatch.setattr(rca_mod.memory_manager, "remember", _fake_remember_noop)


def _exec_tool_call(output: str) -> ToolCallRecord:
    return {
        "tool_name": "run_python",
        "input": {"code": "x"},
        "output": output,
        "duration_ms": 1,
        "ok": True,
    }


async def test_matches_whitelisted_pattern_for_a_too_short_plan() -> None:
    result = await analyze_failure(
        goal="goal", plan=["only one task"], flags=[], tool_calls=[_exec_tool_call("FAIL\n")]
    )

    assert result.whitelisted is True
    assert result.pattern == WHITELISTED_PATTERN_TOO_FEW_TASKS
    assert "too_few_tasks" in result.hypothesis or "task" in result.hypothesis.lower()


async def test_a_safety_flag_excludes_the_whitelist_even_with_a_short_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_call_model(
        prompt: str, schema: type[RootCauseHypothesis], **kwargs: object
    ) -> RootCauseHypothesis:
        return RootCauseHypothesis(hypothesis="Blocked by Safety, not a length issue.")

    monkeypatch.setattr(rca_mod, "call_model", fake_call_model)

    flags: list[FlagRecord] = [
        FlagRecord(agent="safety", type="destructive_filesystem", severity="high", details="d")
    ]
    result = await analyze_failure(
        goal="goal", plan=["only one task"], flags=flags, tool_calls=[_exec_tool_call("FAIL\n")]
    )

    assert result.whitelisted is False
    assert result.pattern is None


async def test_a_plan_with_enough_tasks_is_not_whitelisted(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_call_model(
        prompt: str, schema: type[RootCauseHypothesis], **kwargs: object
    ) -> RootCauseHypothesis:
        assert "task one" in prompt
        return RootCauseHypothesis(hypothesis="Some other reason entirely.")

    monkeypatch.setattr(rca_mod, "call_model", fake_call_model)

    result = await analyze_failure(
        goal="goal",
        plan=["task one", "task two", "task three"],
        flags=[],
        tool_calls=[_exec_tool_call("FAIL\n")],
    )

    assert result.whitelisted is False
    assert result.hypothesis == "Some other reason entirely."


async def test_memory_recall_is_advisory_not_decisive(monkeypatch: pytest.MonkeyPatch) -> None:
    """Even if memory surfaces a similar past failure, the whitelist
    decision itself must stay purely deterministic — recall() returning
    content must never flip a non-whitelisted case to whitelisted."""

    async def fake_recall_with_hits(
        query: str, *, source_type: str | None = None, top_k: int = 3
    ) -> list[str]:
        return ["Failure signature: too_few_tasks. Goal: something else."]

    async def fake_call_model(
        prompt: str, schema: type[RootCauseHypothesis], **kwargs: object
    ) -> RootCauseHypothesis:
        assert "something else" in prompt  # similar_failures context reached the prompt
        return RootCauseHypothesis(hypothesis="Still not whitelisted.")

    monkeypatch.setattr(rca_mod.memory_manager, "recall", fake_recall_with_hits)
    monkeypatch.setattr(rca_mod, "call_model", fake_call_model)

    result = await analyze_failure(
        goal="goal",
        plan=["task one", "task two"],
        flags=[],
        tool_calls=[_exec_tool_call("FAIL\n")],
    )

    assert result.whitelisted is False


async def test_fails_open_with_a_generic_hypothesis_when_llm_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_call_model_raises(
        prompt: str, schema: type[RootCauseHypothesis], **kwargs: object
    ) -> RootCauseHypothesis:
        raise AIClientError("model unavailable")

    monkeypatch.setattr(rca_mod, "call_model", fake_call_model_raises)

    result = await analyze_failure(
        goal="goal",
        plan=["task one", "task two"],
        flags=[],
        tool_calls=[_exec_tool_call("FAIL\n")],
    )

    assert result.whitelisted is False
    assert result.hypothesis  # never empty, always something a human can read
