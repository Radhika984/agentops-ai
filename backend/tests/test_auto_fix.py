"""Phase 9 agents/auto_fix.py tests.

call_model() and call_tool() are mocked at the same seams every other
agent-node test file uses — no network, no real model call, no real
sandbox subprocess spawn.
"""

from __future__ import annotations

import pytest

from app.agents import auto_fix as auto_fix_mod
from app.agents.auto_fix import apply_and_reverify, propose_fix
from app.agents.schemas import AutoFixPatch
from app.ai.client import AIClientError
from app.tools.registry import ToolCallResult

pytestmark = pytest.mark.anyio


async def test_propose_fix_uses_the_llm_when_available(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_call_model(
        prompt: str, schema: type[AutoFixPatch], **kwargs: object
    ) -> AutoFixPatch:
        assert "only one task" in prompt
        return AutoFixPatch(additional_task="Review and finalize the plan.")

    monkeypatch.setattr(auto_fix_mod, "call_model", fake_call_model)

    task = await propose_fix(goal="goal", plan=["only one task"])

    assert task == "Review and finalize the plan."


async def test_propose_fix_falls_back_when_llm_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_call_model_raises(
        prompt: str, schema: type[AutoFixPatch], **kwargs: object
    ) -> AutoFixPatch:
        raise AIClientError("model unavailable")

    monkeypatch.setattr(auto_fix_mod, "call_model", fake_call_model_raises)

    task = await propose_fix(goal="goal", plan=["only one task"])

    assert task == auto_fix_mod._FALLBACK_TASK


async def test_apply_and_reverify_passes_after_appending_the_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_call_tool(tool_name: str, arguments: dict[str, object]) -> ToolCallResult:
        assert "Finish up" in str(arguments["code"])
        return ToolCallResult(
            tool_name="run_python", input=arguments, output="PASS\n", duration_ms=1, ok=True
        )

    monkeypatch.setattr(auto_fix_mod, "call_tool", fake_call_tool)

    original_plan = ["only one task"]
    result = await apply_and_reverify(plan=original_plan, additional_task="Finish up")

    assert result.passed is True
    assert result.new_plan == ["only one task", "Finish up"]
    assert original_plan == ["only one task"]  # the original list is never mutated
    assert result.flags == []


async def test_apply_and_reverify_reports_failure_when_still_failing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_call_tool(tool_name: str, arguments: dict[str, object]) -> ToolCallResult:
        return ToolCallResult(
            tool_name="run_python", input=arguments, output="FAIL\n", duration_ms=1, ok=True
        )

    monkeypatch.setattr(auto_fix_mod, "call_tool", fake_call_tool)

    result = await apply_and_reverify(plan=["only one task"], additional_task="Finish up")

    assert result.passed is False


async def test_apply_and_reverify_records_a_safety_flag_when_the_reverify_is_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_call_tool(tool_name: str, arguments: dict[str, object]) -> ToolCallResult:
        return ToolCallResult(
            tool_name="run_python",
            input=arguments,
            output="Blocked by Safety: matched deny pattern.",
            duration_ms=0,
            ok=False,
            blocked_by_safety=True,
            safety_type="destructive_filesystem",
            safety_severity="high",
        )

    monkeypatch.setattr(auto_fix_mod, "call_tool", fake_call_tool)

    result = await apply_and_reverify(plan=["only one task"], additional_task="Finish up")

    assert result.passed is False
    assert len(result.flags) == 1
    assert result.flags[0]["agent"] == "safety"
    assert result.flags[0]["type"] == "destructive_filesystem"
