"""Phase 4/5/6/7 agent node + graph tests.

All call_model(), call_tool(), and memory_manager.recall() calls are
mocked — no network access, no real model call, no real MCP subprocess
spawn, no real DB session, matching the blueprint's own testing notes
("unit tests per node (mocked LLM calls)"; Phase 5: "unit tests per tool
server (mocked externally)"). Real, end-to-end tool calls (real DuckDuckGo
request, real sandboxed subprocess) are covered separately in
tests/test_tools.py; real embedding+retrieval round trips are covered in
tests/test_memory.py; Safety's real deterministic-vs-LLM-fallback behavior
is covered in tests/test_safety.py.
"""

from __future__ import annotations

import pytest

from app.agents.evaluation import evaluation_node
from app.agents.graph import MAX_RETRIES, build_graph
from app.agents.schemas import HallucinationCheck, PlanOutput
from app.agents.state import initial_state
from app.ai.schemas import AnswerResponse
from app.tools.registry import ToolCallResult

pytestmark = pytest.mark.anyio


def _fake_search_result(output: str = "", ok: bool = True) -> ToolCallResult:
    return ToolCallResult(
        tool_name="web_search", input={"query": "x"}, output=output, duration_ms=1, ok=ok
    )


def _fake_exec_result(output: str, ok: bool = True) -> ToolCallResult:
    return ToolCallResult(
        tool_name="run_python", input={"code": "x"}, output=output, duration_ms=1, ok=ok
    )


async def _fake_recall_empty(
    query: str, *, source_type: str | None = None, top_k: int = 3
) -> list[str]:
    return []


# ---- planner_node ----


async def test_planner_node_sets_plan_from_call_model(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.agents.planner as planner_mod

    async def fake_call_model(
        prompt: str, schema: type[PlanOutput], **kwargs: object
    ) -> PlanOutput:
        assert "Ship a feature" in prompt
        return PlanOutput(tasks=["design it", "build it", "ship it"])

    async def fake_call_tool(tool_name: str, arguments: dict[str, object]) -> ToolCallResult:
        assert tool_name == "web_search"
        return _fake_search_result()

    monkeypatch.setattr(planner_mod, "call_model", fake_call_model)
    monkeypatch.setattr(planner_mod, "call_tool", fake_call_tool)
    monkeypatch.setattr(planner_mod.memory_manager, "recall", _fake_recall_empty)

    state = initial_state("Ship a feature")
    result = await planner_mod.planner_node(state)

    assert result["plan"] == ["design it", "build it", "ship it"]
    assert result["status"] == "planning"


async def test_planner_node_records_the_search_tool_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.agents.planner as planner_mod

    async def fake_call_model(
        prompt: str, schema: type[PlanOutput], **kwargs: object
    ) -> PlanOutput:
        assert "some useful background" in prompt
        return PlanOutput(tasks=["task one", "task two"])

    async def fake_call_tool(tool_name: str, arguments: dict[str, object]) -> ToolCallResult:
        return _fake_search_result(output="some useful background")

    monkeypatch.setattr(planner_mod, "call_model", fake_call_model)
    monkeypatch.setattr(planner_mod, "call_tool", fake_call_tool)
    monkeypatch.setattr(planner_mod.memory_manager, "recall", _fake_recall_empty)

    result = await planner_mod.planner_node(initial_state("goal"))

    assert len(result["tool_calls"]) == 1
    assert result["tool_calls"][0]["tool_name"] == "web_search"
    assert result["tool_calls"][0]["ok"] is True


async def test_planner_node_tolerates_a_failed_search(monkeypatch: pytest.MonkeyPatch) -> None:
    """A failed/blocked search tool call must not crash planning — the
    prompt just falls back to the goal alone."""
    import app.agents.planner as planner_mod

    async def fake_call_model(
        prompt: str, schema: type[PlanOutput], **kwargs: object
    ) -> PlanOutput:
        assert "No results found." in prompt
        return PlanOutput(tasks=["task one", "task two"])

    async def fake_call_tool(tool_name: str, arguments: dict[str, object]) -> ToolCallResult:
        return _fake_search_result(output="network error", ok=False)

    monkeypatch.setattr(planner_mod, "call_model", fake_call_model)
    monkeypatch.setattr(planner_mod, "call_tool", fake_call_tool)
    monkeypatch.setattr(planner_mod.memory_manager, "recall", _fake_recall_empty)

    result = await planner_mod.planner_node(initial_state("goal"))

    assert result["plan"] == ["task one", "task two"]
    assert result["tool_calls"][0]["ok"] is False


async def test_planner_node_includes_retrieved_memory_in_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.agents.planner as planner_mod

    async def fake_call_model(
        prompt: str, schema: type[PlanOutput], **kwargs: object
    ) -> PlanOutput:
        assert "Goal: Plan a birthday party" in prompt
        return PlanOutput(tasks=["task one", "task two"])

    async def fake_call_tool(tool_name: str, arguments: dict[str, object]) -> ToolCallResult:
        return _fake_search_result()

    async def fake_recall(
        query: str, *, source_type: str | None = None, top_k: int = 3
    ) -> list[str]:
        assert query == "Plan a birthday party"
        assert source_type == "run"
        return ["Goal: Plan a birthday party\nPlan:\n- Book a venue"]

    monkeypatch.setattr(planner_mod, "call_model", fake_call_model)
    monkeypatch.setattr(planner_mod, "call_tool", fake_call_tool)
    monkeypatch.setattr(planner_mod.memory_manager, "recall", fake_recall)

    result = await planner_mod.planner_node(initial_state("Plan a birthday party"))

    assert result["retrieved_memory"] == ["Goal: Plan a birthday party\nPlan:\n- Book a venue"]


async def test_planner_node_tolerates_no_retrieved_memory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unrelated/empty recall must not degrade planning — same
    fail-open contract as the search tool."""
    import app.agents.planner as planner_mod

    async def fake_call_model(
        prompt: str, schema: type[PlanOutput], **kwargs: object
    ) -> PlanOutput:
        assert "No similar past runs found." in prompt
        return PlanOutput(tasks=["task one", "task two"])

    async def fake_call_tool(tool_name: str, arguments: dict[str, object]) -> ToolCallResult:
        return _fake_search_result()

    monkeypatch.setattr(planner_mod, "call_model", fake_call_model)
    monkeypatch.setattr(planner_mod, "call_tool", fake_call_tool)
    monkeypatch.setattr(planner_mod.memory_manager, "recall", _fake_recall_empty)

    result = await planner_mod.planner_node(initial_state("goal"))

    assert result["plan"] == ["task one", "task two"]
    assert result["retrieved_memory"] == []


# ---- evaluation_node (no model call, no tool call — rule-based) ----


async def test_evaluation_node_passes_a_substantive_plan() -> None:
    state = initial_state("goal")
    state["plan"] = ["design the feature", "implement it", "write tests"]

    result = await evaluation_node(state)

    assert result["status"] == "evaluating"
    assert len(result["evaluations"]) == 1
    assert result["evaluations"][0]["passed"] is True


async def test_evaluation_node_fails_an_empty_plan() -> None:
    state = initial_state("goal")
    state["plan"] = []

    result = await evaluation_node(state)

    assert result["evaluations"][0]["passed"] is False
    assert result["evaluations"][0]["score"] == 0.0


async def test_evaluation_node_appends_rather_than_overwrites() -> None:
    state = initial_state("goal")
    state["plan"] = ["a real task here"]
    state["evaluations"] = [{"score": 0.5, "passed": False}]

    result = await evaluation_node(state)

    assert len(result["evaluations"]) == 2


# ---- verification_node (deterministic check, executed via the sandboxed
# run_python tool as of Phase 5) ----


async def test_verification_node_passes_when_tool_reports_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.agents.verification as verification_mod

    async def fake_call_tool(tool_name: str, arguments: dict[str, object]) -> ToolCallResult:
        assert tool_name == "run_python"
        return _fake_exec_result("PASS\n")

    monkeypatch.setattr(verification_mod, "call_tool", fake_call_tool)

    state = initial_state("goal")
    state["plan"] = ["task one", "task two"]
    result = await verification_mod.verification_node(state)

    assert result["verification_passed"] is True
    assert result["status"] == "verifying"
    assert result["tool_calls"][0]["tool_name"] == "run_python"


async def test_verification_node_fails_when_tool_reports_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.agents.verification as verification_mod

    async def fake_call_tool(tool_name: str, arguments: dict[str, object]) -> ToolCallResult:
        return _fake_exec_result("FAIL\n")

    monkeypatch.setattr(verification_mod, "call_tool", fake_call_tool)

    result = await verification_mod.verification_node(initial_state("goal"))

    assert result["verification_passed"] is False


async def test_verification_node_fails_safe_when_tool_call_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the sandbox itself errors out, verification must not be trusted
    as passed — fail safe rather than assume success."""
    import app.agents.verification as verification_mod

    async def fake_call_tool(tool_name: str, arguments: dict[str, object]) -> ToolCallResult:
        return _fake_exec_result("Blocked: execution exceeded 5s timeout.", ok=False)

    monkeypatch.setattr(verification_mod, "call_tool", fake_call_tool)

    result = await verification_mod.verification_node(initial_state("goal"))

    assert result["verification_passed"] is False


# ---- hallucination_node ----


async def test_hallucination_node_flags_unsupported_claims(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.agents.hallucination as hallucination_mod

    async def fake_call_model(
        prompt: str, schema: type[HallucinationCheck], **kwargs: object
    ) -> HallucinationCheck:
        assert "task one" in prompt
        return HallucinationCheck(unsupported_claims=["task one"])

    monkeypatch.setattr(hallucination_mod, "call_model", fake_call_model)

    state = initial_state("goal")
    state["plan"] = ["task one", "task two"]
    result = await hallucination_mod.hallucination_node(state)

    assert result["status"] == "checking_hallucination"
    assert result["flags"] == [
        {
            "agent": "hallucination",
            "type": "unsupported_claim",
            "severity": "medium",
            "details": "task one",
        }
    ]


async def test_hallucination_node_no_flags_when_all_supported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.agents.hallucination as hallucination_mod

    async def fake_call_model(
        prompt: str, schema: type[HallucinationCheck], **kwargs: object
    ) -> HallucinationCheck:
        return HallucinationCheck(unsupported_claims=[])

    monkeypatch.setattr(hallucination_mod, "call_model", fake_call_model)

    state = initial_state("goal")
    state["plan"] = ["task one", "task two"]
    result = await hallucination_mod.hallucination_node(state)

    assert result["flags"] == []


async def test_hallucination_node_skips_check_for_empty_plan() -> None:
    import app.agents.hallucination as hallucination_mod

    result = await hallucination_mod.hallucination_node(initial_state("goal"))

    assert result["flags"] == []


async def test_hallucination_node_fails_open_when_model_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unreviewable check must not itself flag anything or crash the
    graph — it fails open (no flags), unlike Safety, which fails closed."""
    import app.agents.hallucination as hallucination_mod
    from app.ai.client import MissingAPIKeyError

    async def failing_call_model(
        prompt: str, schema: type[HallucinationCheck], **kwargs: object
    ) -> HallucinationCheck:
        raise MissingAPIKeyError("no key configured")

    monkeypatch.setattr(hallucination_mod, "call_model", failing_call_model)

    state = initial_state("goal")
    state["plan"] = ["task one"]
    result = await hallucination_mod.hallucination_node(state)

    assert result["flags"] == []


# ---- full graph: the bounded retry loop ----


def _install_fakes(monkeypatch: pytest.MonkeyPatch, plans: list[list[str]]) -> None:
    import app.agents.hallucination as hallucination_mod
    import app.agents.planner as planner_mod
    import app.agents.verification as verification_mod

    call_index = {"n": 0}

    async def fake_call_model(
        prompt: str, schema: type[PlanOutput], **kwargs: object
    ) -> PlanOutput:
        tasks = plans[min(call_index["n"], len(plans) - 1)]
        call_index["n"] += 1
        return PlanOutput(tasks=tasks)

    async def fake_search(tool_name: str, arguments: dict[str, object]) -> ToolCallResult:
        return _fake_search_result()

    async def fake_exec(tool_name: str, arguments: dict[str, object]) -> ToolCallResult:
        # Mirrors verification_node's real MIN_TASKS_TO_VERIFY check without
        # spawning a real sandbox — see module docstring.
        code = str(arguments["code"])
        passed = f"plan = {plans[min(call_index['n'] - 1, len(plans) - 1)]!r}" in code and len(
            plans[min(call_index["n"] - 1, len(plans) - 1)]
        ) >= verification_mod.MIN_TASKS_TO_VERIFY
        return _fake_exec_result("PASS\n" if passed else "FAIL\n")

    async def fake_hallucination_check(
        prompt: str, schema: type[HallucinationCheck], **kwargs: object
    ) -> HallucinationCheck:
        return HallucinationCheck(unsupported_claims=[])

    monkeypatch.setattr(planner_mod, "call_model", fake_call_model)
    monkeypatch.setattr(planner_mod, "call_tool", fake_search)
    monkeypatch.setattr(planner_mod.memory_manager, "recall", _fake_recall_empty)
    monkeypatch.setattr(verification_mod, "call_tool", fake_exec)
    monkeypatch.setattr(hallucination_mod, "call_model", fake_hallucination_check)


async def test_graph_retries_once_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    """First planner call returns a single-task plan (fails verification),
    second call returns a multi-task plan (passes) — proves the retry loop
    from Verification back to Planner actually works."""
    _install_fakes(monkeypatch, [["only one task"], ["task one", "task two"]])

    graph = build_graph()
    final = await graph.ainvoke(initial_state("goal"))

    assert final["status"] == "succeeded"
    assert final["retry_count"] == 1


async def test_graph_stops_after_max_retries_not_infinitely(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A planner that always fails verification must terminate as `failed`
    after exactly MAX_RETRIES retries — never loop unboundedly."""
    _install_fakes(monkeypatch, [["only one task"]])

    graph = build_graph()
    final = await graph.ainvoke(initial_state("impossible goal"))

    assert final["status"] == "failed"
    assert final["retry_count"] == MAX_RETRIES


async def test_graph_succeeds_immediately_with_no_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fakes(monkeypatch, [["task one", "task two", "task three"]])

    graph = build_graph()
    final = await graph.ainvoke(initial_state("goal"))

    assert final["status"] == "succeeded"
    assert final["retry_count"] == 0


async def test_graph_accumulates_tool_calls_from_both_nodes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fakes(monkeypatch, [["task one", "task two"]])

    graph = build_graph()
    final = await graph.ainvoke(initial_state("goal"))

    tool_names = [tc["tool_name"] for tc in final["tool_calls"]]
    assert tool_names == ["web_search", "run_python"]


def test_answer_response_is_unrelated_to_plan_output() -> None:
    # Sanity check that Phase 4's structured output (PlanOutput) is a
    # separate schema from Phase 2's (AnswerResponse) — no accidental reuse.
    assert set(PlanOutput.model_fields) != set(AnswerResponse.model_fields)
