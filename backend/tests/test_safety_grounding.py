"""Phase 15 — Safety + Grounding repoint tests.

Two layers:
  - Pure unit tests against app.evaluation.checks.safety /
    app.evaluation.checks.grounding directly (no DB, no HTTP) — using
    real deny_patterns from app/observability/policy_rules.yaml for
    Safety (genuinely deterministic, no LLM involved) and a mocked
    call_model for Grounding (every reference_context-present path
    requires an LLM call; no real API key exists in this environment).
  - Integration tests through the full Phase 14 Suite Runner stack (real
    HTTP, real LocalAdapter, real background execution), confirming
    Safety/Grounding checks actually land in the persisted
    TestCaseResult alongside Phase 13's own checks, correctly attributed
    per case and per observability level.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.evaluation.checks.grounding as grounding_mod
import app.services.suite_runner as suite_runner_mod
from app.adapters.execution import AgentExecution, ToolCallRecord
from app.agents.schemas import HallucinationCheck
from app.ai.client import AIClientError
from app.evaluation.checks.grounding import evaluate_grounding
from app.evaluation.checks.safety import evaluate_output_safety, evaluate_tool_call_safety
from app.evaluation.models import CheckStatus, Determinism
from tests.conftest import TEST_DATABASE_URL
from tests.test_suite_runs import (
    _auth_headers,
    _create_agent,
    _create_case,
    _create_project,
    _create_suite,
    _create_suite_run,
    _create_version,
    _register_and_login,
)


@pytest_asyncio.fixture(autouse=True)
async def _background_task_uses_test_database(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncGenerator[None, None]:
    # pytest fixtures don't propagate across modules just because this
    # file imports helper *functions* from tests/test_suite_runs.py — the
    # autouse fixture defined there only applies within that module.
    # Without this copy, execute_suite_run()'s background task would use
    # the real app.db.session.AsyncSessionLocal (pointed at the dev DB,
    # not the test DB), silently looking up suite runs that don't exist
    # there — see tests/test_suite_runs.py's own fixture for the full
    # reasoning.
    engine = create_async_engine(TEST_DATABASE_URL)
    test_session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(suite_runner_mod, "AsyncSessionLocal", test_session_factory)

    yield

    await engine.dispose()


def _tool_call(name: str, ok: bool = True, **input_kwargs: object) -> ToolCallRecord:
    return ToolCallRecord(tool_name=name, input=input_kwargs, output="ok", ok=ok)


def _execution(
    *, output: object = None, tool_calls: list[ToolCallRecord] | None = None
) -> AgentExecution:
    now = datetime.now(UTC)
    return AgentExecution(
        request_id=uuid.uuid4(),
        input={},
        output=output,
        status="ok",
        error=None,
        latency_ms=10,
        started_at=now,
        finished_at=now,
        tool_calls=tool_calls or [],
    )


# =====================================================================
# Unit tests — Safety
# =====================================================================


async def test_level_2_safe_tool_call_is_pass() -> None:
    checks = await evaluate_tool_call_safety(
        [_tool_call("search", query="weather")], observability_level=2
    )

    assert len(checks) == 1
    assert checks[0].status == CheckStatus.PASS
    assert checks[0].determinism == Determinism.DETERMINISTIC
    assert checks[0].check_type.startswith("safety:tool_call[0]")


async def test_level_2_unsafe_tool_call_is_fail() -> None:
    checks = await evaluate_tool_call_safety(
        [_tool_call("shell", command="rm -rf /tmp/data")], observability_level=2
    )

    assert len(checks) == 1
    assert checks[0].status == CheckStatus.FAIL
    assert checks[0].metadata["policy_type"] == "destructive_filesystem"


async def test_check_tool_call_is_invoked_for_every_observed_call() -> None:
    checks = await evaluate_tool_call_safety(
        [
            _tool_call("search", query="weather"),
            _tool_call("shell", command="rm -rf /"),
            _tool_call("search", query="news"),
        ],
        observability_level=2,
    )

    assert len(checks) == 3
    assert [c.status for c in checks] == [CheckStatus.PASS, CheckStatus.FAIL, CheckStatus.PASS]


async def test_level_1_tool_call_safety_is_skipped() -> None:
    checks = await evaluate_tool_call_safety(
        [_tool_call("search", query="weather")], observability_level=1
    )

    assert len(checks) == 1
    assert checks[0].status == CheckStatus.SKIPPED
    assert checks[0].check_type == "safety:tool_calls"


async def test_level_1_never_fabricates_tool_call_pass() -> None:
    """Even with zero tool calls supplied (the only thing a Level 1
    adapter could ever report), the result must be SKIPPED, not PASS —
    absence-of-evidence must never be reported as evidence-of-safety."""
    checks = await evaluate_tool_call_safety([], observability_level=1)

    assert checks[0].status == CheckStatus.SKIPPED
    assert checks[0].status != CheckStatus.PASS


async def test_level_2_zero_observed_calls_is_a_real_pass_not_skipped() -> None:
    """Distinct from Level 1: at Level 2+, zero tool calls is genuine
    information (the agent made none), not missing observability."""
    checks = await evaluate_tool_call_safety([], observability_level=2)

    assert checks[0].status == CheckStatus.PASS
    assert "0 tool calls" in checks[0].detail


async def test_raw_output_safety_evaluated_once() -> None:
    check = await evaluate_output_safety("a perfectly ordinary answer")

    assert check.check_type == "safety:output"
    assert check.status == CheckStatus.PASS


async def test_unsafe_raw_output_is_flagged() -> None:
    check = await evaluate_output_safety("here is the password=hunter2 for the account")

    assert check.status == CheckStatus.FAIL
    assert check.metadata["policy_type"] == "credential_leak"


async def test_output_safety_receives_actual_agent_execution_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Proves the *real* AgentExecution.output is what safety evaluates
    — not some other AgentOps-internal text."""
    import app.evaluation.checks.safety as safety_mod

    seen: list[str] = []
    real_check_tool_call = safety_mod.check_tool_call

    async def _spy(tool_name: str, arguments: dict[str, object]) -> object:
        seen.append(str(arguments.get("output")))
        return await real_check_tool_call(tool_name, arguments)

    monkeypatch.setattr(safety_mod, "check_tool_call", _spy)

    await evaluate_output_safety("this exact string must be what was checked")

    assert seen == ["this exact string must be what was checked"]


# =====================================================================
# Unit tests — Grounding
# =====================================================================


async def test_grounding_with_reference_context_receives_output_and_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, str] = {}

    async def _fake_call_model(
        prompt: str, schema: type[HallucinationCheck], **kwargs: object
    ) -> HallucinationCheck:
        captured["prompt"] = prompt
        return schema(unsupported_claims=[])

    monkeypatch.setattr(grounding_mod, "call_model", _fake_call_model)

    check = await evaluate_grounding("The store closes at 9pm.", "It closes at 9pm.")

    assert check.status == CheckStatus.PASS
    assert "The store closes at 9pm." in captured["prompt"]
    assert "It closes at 9pm." in captured["prompt"]


async def test_grounding_flags_unsupported_claims(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_call_model(
        prompt: str, schema: type[HallucinationCheck], **kwargs: object
    ) -> HallucinationCheck:
        return schema(unsupported_claims=["the store closes at midnight"])

    monkeypatch.setattr(grounding_mod, "call_model", _fake_call_model)

    check = await evaluate_grounding("The store closes at 9pm.", "It closes at midnight.")

    assert check.status == CheckStatus.FAIL
    assert check.metadata["unsupported_claims"] == ["the store closes at midnight"]


async def test_grounding_without_reference_context_is_skipped() -> None:
    check = await evaluate_grounding(None, "anything at all")

    assert check.status == CheckStatus.SKIPPED
    assert check.status != CheckStatus.PASS
    assert check.status != CheckStatus.FAIL


async def test_missing_reference_context_never_calls_the_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fail_if_called(*args: object, **kwargs: object) -> object:
        raise AssertionError("call_model must not be invoked when reference_context is absent")

    monkeypatch.setattr(grounding_mod, "call_model", _fail_if_called)

    check = await evaluate_grounding(None, "anything")

    assert check.status == CheckStatus.SKIPPED


async def test_missing_reference_context_never_triggers_duckduckgo_or_memory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No web_search tool, no memory_manager import at all in the
    grounding module — this asserts the module simply has no such
    attribute to call, structurally ruling out the old
    goal+search+memory context-building path."""
    assert not hasattr(grounding_mod, "memory_manager")
    assert not hasattr(grounding_mod, "call_tool")

    check = await evaluate_grounding(None, "anything")
    assert check.status == CheckStatus.SKIPPED


async def test_grounding_inconclusive_when_model_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _raise(*args: object, **kwargs: object) -> object:
        raise AIClientError("model unavailable")

    monkeypatch.setattr(grounding_mod, "call_model", _raise)

    check = await evaluate_grounding("some reference", "some output")

    assert check.status == CheckStatus.INCONCLUSIVE
    assert check.status != CheckStatus.PASS


# =====================================================================
# Integration tests — through the real Suite Runner
# =====================================================================


@pytest.fixture(autouse=True)
def _grounding_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every integration test below exercises the real Suite Runner end
    to end; grounding's LLM call is mocked at its own import site (the
    only network-touching part of the whole pipeline), matching
    tests/test_ask.py's established mocking convention. Everything else
    — the adapter, Phase 13, Safety — runs for real."""

    async def _fake_call_model(
        prompt: str, schema: type[HallucinationCheck], **kwargs: object
    ) -> HallucinationCheck:
        return schema(unsupported_claims=[])

    monkeypatch.setattr(grounding_mod, "call_model", _fake_call_model)


async def test_safety_result_attaches_to_the_correct_test_case_result(client: AsyncClient) -> None:
    token = await _register_and_login(client, "safety1@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    version_id = await _create_version(
        client, token, agent_id, callable_name="invoke_with_unsafe_tool_call"
    )
    suite_id = await _create_suite(client, token, agent_id)
    await _create_case(client, token, suite_id, name="c1", input={}, expected_output="done")

    suite_run = await _create_suite_run(client, token, suite_id, version_id)
    results = (
        await client.get(
            f"/api/v1/suite-runs/{suite_run['id']}/results", headers=_auth_headers(token)
        )
    ).json()

    safety_checks = [
        c for c in results[0]["checks"] if c["check_type"].startswith("safety:tool_call")
    ]
    assert len(safety_checks) == 1
    assert safety_checks[0]["status"] == "fail"


async def test_two_test_cases_retain_independent_safety_results(client: AsyncClient) -> None:
    token = await _register_and_login(client, "safety2@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    safe_version = await _create_version(
        client, token, agent_id, label="safe", callable_name="invoke_with_safe_tool_call"
    )
    suite_id = await _create_suite(client, token, agent_id)
    await _create_case(client, token, suite_id, name="c1", input={}, expected_output="done")

    unsafe_version = await _create_version(
        client, token, agent_id, label="unsafe", callable_name="invoke_with_unsafe_tool_call"
    )
    await _create_case(client, token, suite_id, name="c2", input={}, expected_output="done")

    safe_run = await _create_suite_run(client, token, suite_id, safe_version)
    unsafe_run = await _create_suite_run(client, token, suite_id, unsafe_version)

    safe_results = (
        await client.get(
            f"/api/v1/suite-runs/{safe_run['id']}/results", headers=_auth_headers(token)
        )
    ).json()
    unsafe_results = (
        await client.get(
            f"/api/v1/suite-runs/{unsafe_run['id']}/results", headers=_auth_headers(token)
        )
    ).json()

    def tool_safety_statuses(results: list[dict[str, object]]) -> set[str]:
        statuses = set()
        for r in results:
            for c in r["checks"]:  # type: ignore[union-attr]
                if c["check_type"].startswith("safety:tool_call["):
                    statuses.add(c["status"])
        return statuses

    assert tool_safety_statuses(safe_results) == {"pass"}
    assert tool_safety_statuses(unsafe_results) == {"fail"}


async def test_multiple_tool_calls_each_get_their_own_safety_check(client: AsyncClient) -> None:
    token = await _register_and_login(client, "safety3@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    version_id = await _create_version(
        client, token, agent_id, callable_name="invoke_with_multiple_tool_calls"
    )
    suite_id = await _create_suite(client, token, agent_id)
    await _create_case(client, token, suite_id, name="c1", input={}, expected_output="done")

    suite_run = await _create_suite_run(client, token, suite_id, version_id)
    results = (
        await client.get(
            f"/api/v1/suite-runs/{suite_run['id']}/results", headers=_auth_headers(token)
        )
    ).json()

    per_call_checks = [
        c for c in results[0]["checks"] if c["check_type"].startswith("safety:tool_call[")
    ]
    assert len(per_call_checks) == 2
    assert {c["status"] for c in per_call_checks} == {"pass", "fail"}


async def test_level_1_agent_version_skips_tool_call_safety_in_a_real_run(
    client: AsyncClient,
) -> None:
    token = await _register_and_login(client, "obs1@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    resp = await client.post(
        f"/api/v1/agents/{agent_id}/versions",
        json={
            "label": "level1",
            "adapter_type": "local",
            "adapter_config": {
                "module_path": "tests.fixtures.toy_agent",
                "callable_name": "invoke_with_safe_tool_call",
            },
            "observability_level": 1,
        },
        headers=_auth_headers(token),
    )
    version_id = resp.json()["id"]
    suite_id = await _create_suite(client, token, agent_id)
    await _create_case(client, token, suite_id, name="c1", input={}, expected_output="done")

    suite_run = await _create_suite_run(client, token, suite_id, version_id)
    results = (
        await client.get(
            f"/api/v1/suite-runs/{suite_run['id']}/results", headers=_auth_headers(token)
        )
    ).json()

    tool_check = next(c for c in results[0]["checks"] if c["check_type"] == "safety:tool_calls")
    assert tool_check["status"] == "skipped"
    # The toy agent *did* report a tool call in its raw response — but at
    # Level 1 the runner must not have evaluated it as if it were visible.
    assert not any(c["check_type"].startswith("safety:tool_call[") for c in results[0]["checks"])


async def test_real_agentexecution_flows_through_phase13_and_phase15_into_one_result(
    client: AsyncClient,
) -> None:
    token = await _register_and_login(client, "integration1@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    version_id = await _create_version(
        client, token, agent_id, callable_name="invoke_with_safe_tool_call"
    )
    suite_id = await _create_suite(client, token, agent_id)
    await _create_case(
        client,
        token,
        suite_id,
        name="c1",
        input={},
        expected_output="done",
        reference_context="Real reference text.",
    )

    suite_run = await _create_suite_run(client, token, suite_id, version_id)
    results = (
        await client.get(
            f"/api/v1/suite-runs/{suite_run['id']}/results", headers=_auth_headers(token)
        )
    ).json()

    check_types = {c["check_type"] for c in results[0]["checks"]}
    assert "expected_output" in check_types  # Phase 13
    assert any(t.startswith("safety:tool_call[") for t in check_types)  # Phase 15 safety
    assert "safety:output" in check_types  # Phase 15 output safety
    assert "grounding" in check_types  # Phase 15 grounding
    assert results[0]["verdict"] == "PASS"


async def test_grounding_result_in_a_real_run_uses_real_output_and_reference_context(
    client: AsyncClient,
) -> None:
    token = await _register_and_login(client, "grounding1@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    version_id = await _create_version(client, token, agent_id, callable_name="invoke_safe_output")
    suite_id = await _create_suite(client, token, agent_id)
    await _create_case(
        client,
        token,
        suite_id,
        name="c1",
        input={},
        expected_output="the weather today is sunny",
        reference_context="Today's forecast: sunny.",
    )

    suite_run = await _create_suite_run(client, token, suite_id, version_id)
    results = (
        await client.get(
            f"/api/v1/suite-runs/{suite_run['id']}/results", headers=_auth_headers(token)
        )
    ).json()

    grounding_check = next(c for c in results[0]["checks"] if c["check_type"] == "grounding")
    assert grounding_check["status"] == "pass"


async def test_no_reference_context_in_a_real_run_is_skipped_not_pass(client: AsyncClient) -> None:
    token = await _register_and_login(client, "grounding2@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    version_id = await _create_version(client, token, agent_id, callable_name="invoke_safe_output")
    suite_id = await _create_suite(client, token, agent_id)
    await _create_case(
        client, token, suite_id, name="c1", input={}, expected_output="the weather today is sunny"
    )

    suite_run = await _create_suite_run(client, token, suite_id, version_id)
    results = (
        await client.get(
            f"/api/v1/suite-runs/{suite_run['id']}/results", headers=_auth_headers(token)
        )
    ).json()

    grounding_check = next(c for c in results[0]["checks"] if c["check_type"] == "grounding")
    assert grounding_check["status"] == "skipped"


async def test_phase13_verdict_computation_is_unaffected_by_safety_or_grounding(
    client: AsyncClient,
) -> None:
    """A case whose Phase 13 checks all pass must still verdict PASS even
    when a Safety check on the same execution fails — Phase 15 checks
    are captured for visibility, not gating, in this phase."""
    token = await _register_and_login(client, "verdict1@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    version_id = await _create_version(
        client, token, agent_id, callable_name="invoke_with_unsafe_tool_call"
    )
    suite_id = await _create_suite(client, token, agent_id)
    await _create_case(client, token, suite_id, name="c1", input={}, expected_output="done")

    suite_run = await _create_suite_run(client, token, suite_id, version_id)
    results = (
        await client.get(
            f"/api/v1/suite-runs/{suite_run['id']}/results", headers=_auth_headers(token)
        )
    ).json()

    tool_safety = next(
        c for c in results[0]["checks"] if c["check_type"].startswith("safety:tool_call[")
    )
    assert tool_safety["status"] == "fail"
    assert results[0]["verdict"] == "PASS"  # Phase 13's own check (expected_output) passed


async def test_suite_aggregate_counts_remain_correct_with_safety_and_grounding_present(
    client: AsyncClient,
) -> None:
    token = await _register_and_login(client, "aggregate2@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    version_id = await _create_version(
        client, token, agent_id, callable_name="invoke_with_unsafe_tool_call"
    )
    suite_id = await _create_suite(client, token, agent_id)
    await _create_case(client, token, suite_id, name="pass1", input={}, expected_output="done")
    await _create_case(client, token, suite_id, name="fail1", input={}, expected_output="nope")

    suite_run = await _create_suite_run(client, token, suite_id, version_id)
    final = (
        await client.get(f"/api/v1/suite-runs/{suite_run['id']}", headers=_auth_headers(token))
    ).json()

    # Both cases had an unsafe tool call, but pass_count/fail_count still
    # reflect only Phase 13's own expected_output verdicts.
    assert final["pass_count"] == 1
    assert final["fail_count"] == 1


# =====================================================================
# Security
# =====================================================================


async def test_agent_output_is_never_executed_as_code() -> None:
    malicious_output = "__import__('os').system('echo pwned')"
    check = await evaluate_output_safety(malicious_output)

    # It must be evaluated as *text* (possibly flagged, possibly not —
    # policy_rules.yaml has no pattern for this specific string) and
    # must never have actually run; there is no side effect to observe
    # because this module contains no eval/exec/subprocess call at all.
    assert check.check_type == "safety:output"


async def test_tool_args_are_passed_as_data_never_executed() -> None:
    checks = await evaluate_tool_call_safety(
        [_tool_call("shell", command="__import__('os').system('echo pwned')")],
        observability_level=2,
    )
    assert checks[0].check_type.startswith("safety:tool_call[0]")


def test_no_eval_exec_or_shell_execution_in_safety_or_grounding_modules() -> None:
    from pathlib import Path

    forbidden = ["eval(", "exec(", "subprocess", "os.system", "__import__"]
    offending: list[str] = []
    for name in ("safety.py", "grounding.py"):
        path = Path(__file__).resolve().parent.parent / "app" / "evaluation" / "checks" / name
        text = path.read_text(encoding="utf-8")
        for needle in forbidden:
            if needle in text:
                offending.append(f"{name}: {needle!r}")
    assert offending == []


async def test_safety_and_grounding_never_see_or_persist_adapter_headers() -> None:
    """Phase 10's HTTPAdapter/AgentAdapter contract (app/adapters/execution.py)
    never carries request headers into AgentExecution.output or
    .tool_calls — Safety/Grounding only ever receive `execution.output`
    and `tool_call.input`, so a credential configured on an
    AgentVersion's adapter_config structurally cannot reach a persisted
    check, without Phase 15 needing any redaction logic of its own."""
    execution = _execution(output="a normal answer", tool_calls=[_tool_call("search", query="x")])

    assert not hasattr(execution, "headers")
    assert not any("header" in key.lower() for key in execution.model_dump())

    output_check = await evaluate_output_safety(execution.output)
    tool_checks = await evaluate_tool_call_safety(execution.tool_calls, observability_level=2)

    assert "header" not in output_check.model_dump_json().lower()
    assert all("header" not in c.model_dump_json().lower() for c in tool_checks)
