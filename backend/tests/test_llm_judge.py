"""Phase 19 — LLM Judge tests.

Two layers:
  - Pure/unit tests against app.evaluation.checks.llm_judge's functions
    directly, with call_model monkeypatched (the same pattern
    tests/test_safety_grounding.py already established for Phase 15's
    grounding module) — deterministic-first gating, threshold
    enforcement, and failure handling, with zero real network calls.
  - Integration tests through the full HTTP + Suite Runner stack (real
    LocalAdapter, real background execution, real Phase 13/15/18
    evidence) — proving the judge is only ever invoked when the locked
    §A rules say so, that it can never override an objective hard
    failure, and that SuiteRun.llm_judge_invocation_count is accurate.

IMPORTANT: GEMINI_API_KEY is configured in this dev environment, so any
rubric-declaring TestCase run through the real Suite Runner WOULD
otherwise trigger a real network call unless call_model is mocked —
every integration test below that creates a rubric case mocks
app.evaluation.checks.llm_judge.call_model explicitly (never
app.ai.client.call_model — that is a different, already-bound reference
and patching it would not affect this module; see
tests/test_suite_runs.py's own note on the same lesson).
"""

from __future__ import annotations

import re
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.evaluation.checks.llm_judge as llm_judge_mod
import app.services.suite_runner as suite_runner_mod
from app.ai.client import AIClientError, ModelOutputValidationError
from app.evaluation.checks.llm_judge import (
    RubricJudgeOutput,
    evaluate_rubric_judge,
    has_objective_hard_failure,
    should_invoke_judge,
)
from tests.conftest import TEST_DATABASE_URL
from tests.fixtures import toy_agent
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
    engine = create_async_engine(TEST_DATABASE_URL)
    test_session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(suite_runner_mod, "AsyncSessionLocal", test_session_factory)
    yield
    await engine.dispose()


@pytest.fixture(autouse=True)
def _reset_toy_agent_state() -> None:
    toy_agent.reset_concurrency_state()
    toy_agent.reset_call_counter()


def _release_url(suite_run_id: str) -> str:
    return f"/api/v1/suite-runs/{suite_run_id}/release"


def _check(check_type: str, status: str, detail: str = "x") -> dict:
    return {"check_type": check_type, "status": status, "detail": detail, "metadata": {}}


# =========================================================================
# Unit tests — should_invoke_judge / has_objective_hard_failure
# =========================================================================


def test_no_rubric_never_invokes_judge() -> None:
    assert should_invoke_judge(None, []) is False
    assert should_invoke_judge("", []) is False


def test_rubric_with_no_objective_failure_invokes_judge() -> None:
    assert should_invoke_judge("Is it kind?", [_check("expected_output", "pass")]) is True


def test_rubric_only_case_invokes_judge() -> None:
    assert should_invoke_judge("Is it kind?", []) is True


def test_safety_failure_blocks_judge_invocation() -> None:
    checks = [_check("safety:output", "fail")]
    assert has_objective_hard_failure(checks) is True
    assert should_invoke_judge("Is it kind?", checks) is False


def test_forbidden_tool_blocks_judge_invocation() -> None:
    checks = [_check("forbidden_tool_calls", "fail")]
    assert should_invoke_judge("Is it kind?", checks) is False


def test_missing_required_tool_blocks_judge_invocation() -> None:
    checks = [_check("tool_call[0]:x", "fail", "missing required tool call: 'x' was never called")]
    assert should_invoke_judge("Is it kind?", checks) is False


def test_schema_failure_blocks_judge_invocation() -> None:
    checks = [_check("output_schema", "fail")]
    assert should_invoke_judge("Is it kind?", checks) is False


def test_correctness_failure_blocks_judge_invocation() -> None:
    checks = [_check("expected_output", "fail", "mismatch: expected 'a', got 'b'")]
    assert should_invoke_judge("Is it kind?", checks) is False


def test_latency_and_grounding_do_not_block_judge_invocation() -> None:
    """Neither is an objective hard-gate failure (§15) — a case can
    still legitimately need the judge's opinion alongside them."""
    checks = [
        _check("latency", "fail", "latency 500ms exceeds the 200ms threshold"),
        _check("grounding", "fail", "output makes 1 claim(s) not supported"),
    ]
    assert should_invoke_judge("Is it kind?", checks) is True


# =========================================================================
# Unit tests — evaluate_rubric_judge
# =========================================================================


async def test_judge_pass_when_score_meets_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_call_model(prompt: str, schema: type, **kwargs: object) -> RubricJudgeOutput:
        return RubricJudgeOutput(score=0.9, rationale="Clearly satisfies the rubric.")

    monkeypatch.setattr(llm_judge_mod, "call_model", _fake_call_model)

    check = await evaluate_rubric_judge(
        rubric="Is it kind?",
        rubric_threshold=0.7,
        test_case_input={"question": "hi"},
        actual_output="a kind reply",
        expected_output=None,
        reference_context=None,
        tool_calls=[],
    )

    assert check.status.value == "pass"
    assert check.check_type == "rubric_judge"
    assert check.metadata["score"] == 0.9


async def test_judge_fail_when_score_below_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_call_model(prompt: str, schema: type, **kwargs: object) -> RubricJudgeOutput:
        return RubricJudgeOutput(score=0.3, rationale="Does not satisfy the rubric.")

    monkeypatch.setattr(llm_judge_mod, "call_model", _fake_call_model)

    check = await evaluate_rubric_judge(
        rubric="Is it kind?",
        rubric_threshold=0.7,
        test_case_input={"question": "hi"},
        actual_output="an unkind reply",
        expected_output=None,
        reference_context=None,
        tool_calls=[],
    )

    assert check.status.value == "fail"


async def test_malformed_judge_output_is_rejected_safely(monkeypatch: pytest.MonkeyPatch) -> None:
    """call_model() itself validates structured output and raises
    ModelOutputValidationError (an AIClientError subclass) after its one
    retry fails — never left to fragile string-parsing here."""

    async def _raise(*args: object, **kwargs: object) -> object:
        raise ModelOutputValidationError("model output did not match the schema")

    monkeypatch.setattr(llm_judge_mod, "call_model", _raise)

    check = await evaluate_rubric_judge(
        rubric="Is it kind?",
        rubric_threshold=0.7,
        test_case_input={},
        actual_output="x",
        expected_output=None,
        reference_context=None,
        tool_calls=[],
    )

    assert check.status.value == "inconclusive"
    assert check.status.value not in ("pass", "fail")


async def test_judge_invocation_failure_returns_inconclusive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _raise(*args: object, **kwargs: object) -> object:
        raise AIClientError("model unavailable")

    monkeypatch.setattr(llm_judge_mod, "call_model", _raise)

    check = await evaluate_rubric_judge(
        rubric="Is it kind?",
        rubric_threshold=0.7,
        test_case_input={},
        actual_output="x",
        expected_output=None,
        reference_context=None,
        tool_calls=[],
    )

    assert check.status.value == "inconclusive"
    assert "model unavailable" in check.detail


def test_no_credential_shaped_content_in_judge_source() -> None:
    """The module docstring explains, in prose, that adapter_config is
    never read here — this checks that claim structurally: no import of
    AgentVersion (the only place adapter_config lives) anywhere in the
    module, so there is no object this code could even call
    `.adapter_config` on."""
    source = (
        Path(__file__).resolve().parent.parent / "app" / "evaluation" / "checks" / "llm_judge.py"
    )
    text = source.read_text(encoding="utf-8")
    import_lines = [
        line for line in text.splitlines() if line.strip().startswith(("import ", "from "))
    ]
    assert not any("agent_version" in line.lower() for line in import_lines)


# =========================================================================
# Integration tests — real HTTP + Suite Runner stack
# =========================================================================


async def test_deterministic_pass_does_not_call_llm(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _fail_if_called(*args: object, **kwargs: object) -> object:
        raise AssertionError("no LLM call should occur for a non-rubric case")

    monkeypatch.setattr(llm_judge_mod, "call_model", _fail_if_called)

    token = await _register_and_login(client, "judge1@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    version_id = await _create_version(client, token, agent_id, callable_name="invoke")
    suite_id = await _create_suite(client, token, agent_id)
    await _create_case(
        client, token, suite_id, name="c1", input={"question": "hi"}, expected_output="echo: hi"
    )

    suite_run = await _create_suite_run(client, token, suite_id, version_id)
    resp = await client.get(f"/api/v1/suite-runs/{suite_run['id']}", headers=_auth_headers(token))

    assert resp.json()["status"] == "completed"
    assert resp.json()["llm_judge_invocation_count"] == 0


async def test_objective_failure_skips_llm_even_with_rubric(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A case that declares BOTH a rubric and an expected_tool_calls
    requirement, where the required tool is never called, must not
    invoke the judge — the objective missing-tool failure is already
    authoritative (§A.5/§A.6)."""
    call_count = {"n": 0}

    async def _count_calls(*args: object, **kwargs: object) -> object:
        call_count["n"] += 1
        raise AssertionError("LLM must not be invoked when an objective failure is authoritative")

    monkeypatch.setattr(llm_judge_mod, "call_model", _count_calls)

    token = await _register_and_login(client, "judge2@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    version_id = await _create_version(client, token, agent_id, callable_name="invoke")
    suite_id = await _create_suite(client, token, agent_id)
    await _create_case(
        client,
        token,
        suite_id,
        name="c1",
        input={},
        rubric="Was it helpful?",
        expected_tool_calls=[{"tool": "search", "required": True}],
    )

    suite_run = await _create_suite_run(client, token, suite_id, version_id)
    resp = await client.get(
        f"/api/v1/suite-runs/{suite_run['id']}/results", headers=_auth_headers(token)
    )

    assert call_count["n"] == 0
    result = resp.json()[0]
    assert result["verdict"] == "FAIL"
    assert not any(c["check_type"] == "rubric_judge" for c in result["checks"])


async def test_rubric_only_case_invokes_judge_via_api(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    call_count = {"n": 0}

    async def _fake_call_model(prompt: str, schema: type, **kwargs: object) -> RubricJudgeOutput:
        call_count["n"] += 1
        return schema(score=0.9, rationale="Meets the rubric.")

    monkeypatch.setattr(llm_judge_mod, "call_model", _fake_call_model)

    token = await _register_and_login(client, "judge3@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    version_id = await _create_version(client, token, agent_id, callable_name="invoke")
    suite_id = await _create_suite(client, token, agent_id)
    await _create_case(
        client, token, suite_id, name="c1", input={"question": "hi"}, rubric="Is it kind?"
    )

    suite_run = await _create_suite_run(client, token, suite_id, version_id)
    resp = await client.get(
        f"/api/v1/suite-runs/{suite_run['id']}/results", headers=_auth_headers(token)
    )

    assert call_count["n"] == 1
    assert resp.json()[0]["verdict"] == "PASS"


async def test_rubric_threshold_pass_via_api(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _fake_call_model(prompt: str, schema: type, **kwargs: object) -> RubricJudgeOutput:
        return schema(score=0.8, rationale="Meets the rubric.")

    monkeypatch.setattr(llm_judge_mod, "call_model", _fake_call_model)

    token = await _register_and_login(client, "judge4@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    version_id = await _create_version(client, token, agent_id, callable_name="invoke")
    suite_id = await _create_suite(client, token, agent_id)
    await _create_case(
        client,
        token,
        suite_id,
        name="c1",
        input={"question": "hi"},
        rubric="Is it kind?",
        rubric_threshold=0.7,
    )

    suite_run = await _create_suite_run(client, token, suite_id, version_id)
    resp = await client.get(
        f"/api/v1/suite-runs/{suite_run['id']}/results", headers=_auth_headers(token)
    )

    assert resp.json()[0]["verdict"] == "PASS"


async def test_rubric_threshold_fail_via_api(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _fake_call_model(prompt: str, schema: type, **kwargs: object) -> RubricJudgeOutput:
        return schema(score=0.4, rationale="Does not meet the rubric.")

    monkeypatch.setattr(llm_judge_mod, "call_model", _fake_call_model)

    token = await _register_and_login(client, "judge5@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    version_id = await _create_version(client, token, agent_id, callable_name="invoke")
    suite_id = await _create_suite(client, token, agent_id)
    await _create_case(
        client,
        token,
        suite_id,
        name="c1",
        input={"question": "hi"},
        rubric="Is it kind?",
        rubric_threshold=0.7,
    )

    suite_run = await _create_suite_run(client, token, suite_id, version_id)
    resp = await client.get(
        f"/api/v1/suite-runs/{suite_run['id']}/results", headers=_auth_headers(token)
    )
    result = resp.json()[0]

    assert result["verdict"] == "FAIL"


async def test_rubric_only_fail_does_not_become_hard_gate(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§D: a rubric-only judge FAIL must not become a correctness hard
    gate — re-verified end to end against the actual Release Gate."""

    async def _fake_call_model(prompt: str, schema: type, **kwargs: object) -> RubricJudgeOutput:
        return schema(score=0.1, rationale="Does not meet the rubric.")

    monkeypatch.setattr(llm_judge_mod, "call_model", _fake_call_model)

    token = await _register_and_login(client, "judge6@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    version_id = await _create_version(client, token, agent_id, callable_name="invoke")
    suite_id = await _create_suite(client, token, agent_id)
    await _create_case(client, token, suite_id, name="c1", input={}, rubric="Is it kind?")

    suite_run = await _create_suite_run(client, token, suite_id, version_id)
    resp = await client.post(_release_url(str(suite_run["id"])), headers=_auth_headers(token))

    assert resp.status_code == 200
    body = resp.json()
    assert body["decision"] == "pass"
    assert body["hard_gate_passed"] is True
    assert body["fail_count"] == 1


async def test_llm_judge_invocation_count_increments_via_api(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _fake_call_model(prompt: str, schema: type, **kwargs: object) -> RubricJudgeOutput:
        return schema(score=0.9, rationale="ok")

    monkeypatch.setattr(llm_judge_mod, "call_model", _fake_call_model)

    token = await _register_and_login(client, "judge7@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    version_id = await _create_version(client, token, agent_id, callable_name="invoke")
    suite_id = await _create_suite(client, token, agent_id)
    await _create_case(client, token, suite_id, name="c1", input={}, rubric="Is it kind?")
    await _create_case(
        client, token, suite_id, name="c2", input={"question": "hi"}, expected_output="echo: hi"
    )

    suite_run = await _create_suite_run(client, token, suite_id, version_id)
    resp = await client.get(f"/api/v1/suite-runs/{suite_run['id']}", headers=_auth_headers(token))

    assert resp.json()["llm_judge_invocation_count"] == 1


async def test_deterministic_only_suite_has_zero_invocation_count(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _fail_if_called(*args: object, **kwargs: object) -> object:
        raise AssertionError("no LLM call should occur in a deterministic-only suite")

    monkeypatch.setattr(llm_judge_mod, "call_model", _fail_if_called)

    token = await _register_and_login(client, "judge8@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    version_id = await _create_version(client, token, agent_id, callable_name="invoke")
    suite_id = await _create_suite(client, token, agent_id)
    for i in range(3):
        await _create_case(
            client,
            token,
            suite_id,
            name=f"c{i}",
            input={"question": str(i)},
            expected_output=f"echo: {i}",
        )

    suite_run = await _create_suite_run(client, token, suite_id, version_id)
    resp = await client.get(f"/api/v1/suite-runs/{suite_run['id']}", headers=_auth_headers(token))

    assert resp.json()["llm_judge_invocation_count"] == 0


async def test_safety_failure_cannot_be_overridden_by_llm(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _fail_if_called(*args: object, **kwargs: object) -> object:
        raise AssertionError("LLM must not be invoked when safety already failed")

    monkeypatch.setattr(llm_judge_mod, "call_model", _fail_if_called)

    token = await _register_and_login(client, "judge9@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    version_id = await _create_version(
        client, token, agent_id, callable_name="invoke_with_unsafe_tool_call"
    )
    suite_id = await _create_suite(client, token, agent_id)
    await _create_case(client, token, suite_id, name="c1", input={}, rubric="Was it professional?")

    suite_run = await _create_suite_run(client, token, suite_id, version_id)
    resp = await client.get(
        f"/api/v1/suite-runs/{suite_run['id']}/results", headers=_auth_headers(token)
    )
    result = resp.json()[0]

    assert any(
        c["check_type"].startswith("safety:") and c["status"] == "fail" for c in result["checks"]
    )
    assert not any(c["check_type"] == "rubric_judge" for c in result["checks"])


async def test_schema_failure_cannot_be_overridden_by_llm(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _fail_if_called(*args: object, **kwargs: object) -> object:
        raise AssertionError("LLM must not be invoked when schema already failed")

    monkeypatch.setattr(llm_judge_mod, "call_model", _fail_if_called)

    token = await _register_and_login(client, "judge10@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    version_id = await _create_version(client, token, agent_id, callable_name="invoke_async")
    suite_id = await _create_suite(client, token, agent_id)
    await _create_case(
        client,
        token,
        suite_id,
        name="c1",
        input={},
        rubric="Is the answer well-explained?",
        output_schema={
            "type": "object",
            "required": ["answer", "confidence"],
            "properties": {"answer": {"type": "string"}, "confidence": {"type": "number"}},
        },
    )

    suite_run = await _create_suite_run(client, token, suite_id, version_id)
    resp = await client.get(
        f"/api/v1/suite-runs/{suite_run['id']}/results", headers=_auth_headers(token)
    )
    result = resp.json()[0]

    assert any(
        c["check_type"] == "output_schema" and c["status"] == "fail" for c in result["checks"]
    )
    assert not any(c["check_type"] == "rubric_judge" for c in result["checks"])


async def test_forbidden_tool_cannot_be_overridden_by_llm(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _fail_if_called(*args: object, **kwargs: object) -> object:
        raise AssertionError("LLM must not be invoked when a forbidden tool was already called")

    monkeypatch.setattr(llm_judge_mod, "call_model", _fail_if_called)

    token = await _register_and_login(client, "judge11@example.com")
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
        rubric="Was the search useful?",
        allowed_tools=["some_other_tool"],
    )

    suite_run = await _create_suite_run(client, token, suite_id, version_id)
    resp = await client.get(
        f"/api/v1/suite-runs/{suite_run['id']}/results", headers=_auth_headers(token)
    )
    result = resp.json()[0]

    assert any(
        c["check_type"] == "forbidden_tool_calls" and c["status"] == "fail"
        for c in result["checks"]
    )
    assert not any(c["check_type"] == "rubric_judge" for c in result["checks"])


async def test_missing_required_tool_cannot_be_overridden_by_llm(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _fail_if_called(*args: object, **kwargs: object) -> object:
        raise AssertionError("LLM must not be invoked when a required tool is missing")

    monkeypatch.setattr(llm_judge_mod, "call_model", _fail_if_called)

    token = await _register_and_login(client, "judge12@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    version_id = await _create_version(client, token, agent_id, callable_name="invoke")
    suite_id = await _create_suite(client, token, agent_id)
    await _create_case(
        client,
        token,
        suite_id,
        name="c1",
        input={},
        rubric="Was the search useful?",
        expected_tool_calls=[{"tool": "search", "required": True}],
    )

    suite_run = await _create_suite_run(client, token, suite_id, version_id)
    resp = await client.get(
        f"/api/v1/suite-runs/{suite_run['id']}/results", headers=_auth_headers(token)
    )
    result = resp.json()[0]

    assert not any(c["check_type"] == "rubric_judge" for c in result["checks"])


async def test_no_credential_leakage_to_judge_input(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, str] = {}

    async def _capture(prompt: str, schema: type, **kwargs: object) -> RubricJudgeOutput:
        captured["prompt"] = prompt
        return schema(score=0.9, rationale="ok")

    monkeypatch.setattr(llm_judge_mod, "call_model", _capture)

    token = await _register_and_login(client, "judge13@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    version_id = await _create_version(client, token, agent_id, callable_name="invoke")
    suite_id = await _create_suite(client, token, agent_id)
    await _create_case(
        client, token, suite_id, name="c1", input={"question": "hi"}, rubric="Is it kind?"
    )

    suite_run = await _create_suite_run(client, token, suite_id, version_id)
    await client.get(f"/api/v1/suite-runs/{suite_run['id']}/results", headers=_auth_headers(token))

    assert "prompt" in captured
    lowered = captured["prompt"].lower()
    for forbidden in ("adapter_config", "module_path", "callable_name", "authorization", "api_key"):
        assert forbidden not in lowered


# =========================================================================
# Security static checks
# =========================================================================


def test_no_eval_exec_or_subprocess_in_llm_judge_source() -> None:
    forbidden = re.compile(r"\beval\(|\bexec\(|subprocess\.|os\.system\(")
    source = (
        Path(__file__).resolve().parent.parent / "app" / "evaluation" / "checks" / "llm_judge.py"
    )
    assert not forbidden.search(source.read_text(encoding="utf-8"))
