"""Phase 18 — Root Cause Analysis tests.

Three layers:
  - Pure unit tests against app.rca.evidence's deterministic pattern
    detectors directly — exhaustive coverage of the locked 4-category
    RCA whitelist, no DB/HTTP/LLM needed.
  - Unit tests against app.rca.service.analyze_case() using real
    (unpersisted) TestCase/TestCaseResult ORM objects, with call_model
    monkeypatched (the same pattern tests/test_safety_grounding.py
    already uses for Phase 15's grounding module) — covers the
    deterministic/LLM-hypothesis/insufficient-evidence tiers precisely,
    without ever making a real network call.
  - Integration tests through the full HTTP + Suite Runner stack (real
    LocalAdapter, real background execution, real Phase 13/15/16/17
    evidence) — ownership, evidence availability, and confirming
    deterministic RCA never touches the LLM.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.rca.service as rca_service_mod
import app.services.suite_runner as suite_runner_mod
from app.agents.schemas import RootCauseHypothesis
from app.ai.client import AIClientError
from app.models.test_case import TestCase
from app.models.test_case_result import TestCaseResult
from app.rca.evidence import (
    classify_deterministic,
    find_correctness_failures,
    find_forbidden_tool_called,
    find_latency_exceeded,
    find_missing_required_tool_calls,
    find_schema_field_missing,
)
from app.rca.service import analyze_case
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
    toy_agent.reset_alternating_state()
    toy_agent.reset_fail_second_state()


async def _promote_baseline(
    client: AsyncClient, token: str, agent_id: str, version_id: str
) -> None:
    resp = await client.post(
        f"/api/v1/agents/{agent_id}/versions/{version_id}/baseline",
        headers=_auth_headers(token),
    )
    assert resp.status_code == 200


async def _get_result_id_for_case(
    client: AsyncClient, token: str, suite_run_id: str, test_case_id: str
) -> str:
    resp = await client.get(
        f"/api/v1/suite-runs/{suite_run_id}/results", headers=_auth_headers(token)
    )
    for result in resp.json():
        if result["test_case_id"] == test_case_id:
            return str(result["id"])
    raise AssertionError(f"no result for test case {test_case_id} in suite run {suite_run_id}")


def _rca_url(suite_run_id: str, result_id: str) -> str:
    return f"/api/v1/suite-runs/{suite_run_id}/results/{result_id}/rca"


# =========================================================================
# Unit tests — app.rca.evidence (pure deterministic detectors)
# =========================================================================


def _check(
    check_type: str, status: str, detail: str, metadata: dict[str, object] | None = None
) -> dict:
    return {
        "check_type": check_type,
        "status": status,
        "detail": detail,
        "metadata": metadata or {},
    }


def test_missing_required_tool_call_is_detected() -> None:
    checks = [
        _check(
            "tool_call[0]:search", "fail", "missing required tool call: 'search' was never called"
        )
    ]
    findings = find_missing_required_tool_calls(checks)
    assert len(findings) == 1
    assert findings[0].category == "missing_required_tool_call"


def test_missing_required_tool_call_does_not_match_arg_constraint_failure() -> None:
    checks = [
        _check(
            "tool_call[0]:search",
            "fail",
            "tool 'search' was called, but no call satisfied its argument constraints "
            "(last attempt: x)",
        )
    ]
    assert find_missing_required_tool_calls(checks) == []


def test_schema_field_missing_is_detected() -> None:
    checks = [
        _check(
            "output_schema",
            "fail",
            "schema validation failed at <root>: 'confidence' is a required property",
        )
    ]
    findings = find_schema_field_missing(checks)
    assert len(findings) == 1
    assert findings[0].category == "schema_field_missing"


def test_schema_field_missing_does_not_match_other_schema_errors() -> None:
    checks = [
        _check(
            "output_schema",
            "fail",
            "schema validation failed at /age: 'twelve' is not of type 'integer'",
        )
    ]
    assert find_schema_field_missing(checks) == []


def test_latency_exceeded_is_detected() -> None:
    checks = [_check("latency", "fail", "latency 500ms exceeds the 200ms threshold")]
    findings = find_latency_exceeded(checks)
    assert len(findings) == 1
    assert findings[0].category == "latency_exceeded"


def test_latency_exceeded_does_not_match_missing_latency() -> None:
    checks = [
        _check(
            "latency",
            "fail",
            "actual latency is missing; cannot evaluate against latency_threshold_ms",
        )
    ]
    assert find_latency_exceeded(checks) == []


def test_forbidden_tool_called_is_detected() -> None:
    checks = [_check("forbidden_tool_calls", "fail", "forbidden tool call(s) made: shell")]
    findings = find_forbidden_tool_called(checks)
    assert len(findings) == 1
    assert findings[0].category == "forbidden_tool_called"


def test_correctness_failure_detects_expected_output_fail() -> None:
    checks = [_check("expected_output", "fail", "mismatch: expected 'a', got 'b'")]
    findings = find_correctness_failures(checks)
    assert len(findings) == 1
    assert findings[0].category == "correctness_failure"
    assert findings[0].check_type == "expected_output"


def test_correctness_failure_detects_assertion_fail() -> None:
    checks = [_check("assertion[0]", "fail", "$.status: expected 'ok', got 'error'")]
    findings = find_correctness_failures(checks)
    assert len(findings) == 1
    assert findings[0].check_type == "assertion[0]"


def test_correctness_failure_detects_tool_call_order_fail() -> None:
    checks = [_check("tool_call_order", "fail", "tool calls did not occur in the expected order")]
    findings = find_correctness_failures(checks)
    assert len(findings) == 1


def test_correctness_failure_excludes_latency() -> None:
    checks = [_check("latency", "fail", "latency 500ms exceeds the 200ms threshold")]
    assert find_correctness_failures(checks) == []


def test_correctness_failure_excludes_grounding() -> None:
    checks = [
        _check("grounding", "fail", "output makes 1 claim(s) not supported by reference_context")
    ]
    assert find_correctness_failures(checks) == []


def test_correctness_failure_excludes_rubric() -> None:
    checks = [_check("rubric", "pending_llm", "subjective rubric criterion")]
    assert find_correctness_failures(checks) == []


def test_correctness_failure_excludes_already_categorized_missing_tool() -> None:
    checks = [
        _check(
            "tool_call[0]:search", "fail", "missing required tool call: 'search' was never called"
        )
    ]
    assert find_correctness_failures(checks) == []


def test_correctness_failure_excludes_already_categorized_forbidden_tool() -> None:
    checks = [_check("forbidden_tool_calls", "fail", "forbidden tool call(s) made: shell")]
    assert find_correctness_failures(checks) == []


def test_correctness_failure_excludes_already_categorized_schema() -> None:
    checks = [
        _check(
            "output_schema",
            "fail",
            "schema validation failed at <root>: 'x' is a required property",
        )
    ]
    assert find_correctness_failures(checks) == []


def test_correctness_failure_excludes_safety() -> None:
    checks = [_check("safety:output", "fail", "blocked by policy")]
    assert find_correctness_failures(checks) == []


def test_correctness_failure_includes_tool_call_argument_mismatch() -> None:
    """A tool_call[i]:tool FAIL caused by unsatisfied argument
    constraints (NOT "never called") is a real correctness failure,
    distinct from missing_required_tool_call."""
    checks = [
        _check(
            "tool_call[0]:search",
            "fail",
            "tool 'search' was called, but no call satisfied its argument constraints",
        )
    ]
    findings = find_correctness_failures(checks)
    assert len(findings) == 1


def test_classify_deterministic_returns_empty_when_nothing_matches() -> None:
    checks = [_check("expected_output", "fail", "mismatch: expected 'a', got 'b'")]
    assert classify_deterministic(checks) == []


def test_classify_deterministic_priority_order() -> None:
    checks = [
        _check("forbidden_tool_calls", "fail", "forbidden tool call(s) made: shell"),
        _check(
            "tool_call[0]:search", "fail", "missing required tool call: 'search' was never called"
        ),
    ]
    findings = classify_deterministic(checks)
    assert [f.category for f in findings] == ["missing_required_tool_call", "forbidden_tool_called"]


# =========================================================================
# Unit tests — app.rca.service.analyze_case (real ORM objects, no DB)
# =========================================================================


def _test_case(**overrides: object) -> TestCase:
    defaults: dict[str, object] = {"id": uuid.uuid4(), "name": "case-1"}
    defaults.update(overrides)
    return TestCase(**defaults)  # type: ignore[arg-type]


def _result(verdict: str, checks: list[dict[str, object]], **overrides: object) -> TestCaseResult:
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "suite_run_id": uuid.uuid4(),
        "test_case_id": uuid.uuid4(),
        "verdict": verdict,
        "verdict_method": "majority",
        "checks": checks,
        "trials": [],
        "actual_output": None,
        "latency_ms": 10,
        "error": None,
        "suggested_fix": None,
    }
    defaults.update(overrides)
    return TestCaseResult(**defaults)  # type: ignore[arg-type]


async def test_deterministic_tier_never_calls_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fail_if_called(*args: object, **kwargs: object) -> object:
        raise AssertionError("call_model must not be invoked for a deterministic match")

    monkeypatch.setattr(rca_service_mod, "call_model", _fail_if_called)

    case = _test_case()
    result = _result(
        "FAIL",
        [
            _check(
                "tool_call[0]:search",
                "fail",
                "missing required tool call: 'search' was never called",
            )
        ],
    )
    rca = await analyze_case(test_case=case, result=result)

    assert rca.tier == "deterministic"
    assert rca.root_cause_category == "missing_required_tool_call"
    assert "tool_call[0]:search" in rca.related_check_types


async def test_unmatched_failure_reaches_llm_hypothesis(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_call_model(
        prompt: str, schema: type[RootCauseHypothesis], **kwargs: object
    ) -> RootCauseHypothesis:
        assert "expected_output" in prompt
        return schema(
            hypothesis="The output did not match expected_output per the expected_output check."
        )

    monkeypatch.setattr(rca_service_mod, "call_model", _fake_call_model)

    case = _test_case()
    result = _result("FAIL", [_check("expected_output", "fail", "mismatch: expected 'a', got 'b'")])
    rca = await analyze_case(test_case=case, result=result)

    assert rca.tier == "llm_hypothesis"
    assert "expected_output" in rca.explanation
    assert any(e.check_type == "expected_output" for e in rca.evidence_references)


async def test_llm_hypothesis_cites_observable_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_call_model(
        prompt: str, schema: type[RootCauseHypothesis], **kwargs: object
    ) -> RootCauseHypothesis:
        return schema(hypothesis="Generic hypothesis text.")

    monkeypatch.setattr(rca_service_mod, "call_model", _fake_call_model)

    case = _test_case()
    result = _result("FAIL", [_check("expected_output", "fail", "mismatch: expected 'a', got 'b'")])
    rca = await analyze_case(test_case=case, result=result)

    # Traceability is guaranteed structurally: evidence_references is
    # always populated from the SAME checks the prompt was built from,
    # independent of what the LLM's free text happens to say.
    assert len(rca.evidence_references) >= 1
    assert rca.evidence_references[0].check_type == "expected_output"
    assert rca.evidence_references[0].detail == "mismatch: expected 'a', got 'b'"


async def test_insufficient_evidence_when_no_relevant_checks() -> None:
    case = _test_case()
    result = _result("FAIL", [])  # a FAIL verdict but nothing recorded to explain it
    rca = await analyze_case(test_case=case, result=result)

    assert rca.tier == "insufficient_evidence"
    assert "insufficient observable evidence" in rca.explanation
    assert rca.evidence_references == []


async def test_insufficient_evidence_never_fabricates_a_cause() -> None:
    case = _test_case()
    result = _result("FAIL", [])
    rca = await analyze_case(test_case=case, result=result)

    assert rca.root_cause_category is None


async def test_llm_unavailable_falls_back_to_insufficient_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _raise(*args: object, **kwargs: object) -> object:
        raise AIClientError("model unavailable")

    monkeypatch.setattr(rca_service_mod, "call_model", _raise)

    case = _test_case()
    result = _result("FAIL", [_check("expected_output", "fail", "mismatch: expected 'a', got 'b'")])
    rca = await analyze_case(test_case=case, result=result)

    assert rca.tier == "insufficient_evidence"
    assert rca.evidence_references  # the checks that would have been sent remain visible


async def test_not_applicable_for_a_clean_pass() -> None:
    case = _test_case()
    result = _result(
        "PASS", [_check("expected_output", "pass", "actual output matches expected_output")]
    )
    rca = await analyze_case(test_case=case, result=result)

    assert rca.tier == "not_applicable"
    assert rca.evidence_references == []


async def test_trace_span_ids_empty_when_no_trace_persisted() -> None:
    case = _test_case()
    result = _result("FAIL", [], trials=[{"trial_index": 0, "verdict": "FAIL"}])
    rca = await analyze_case(test_case=case, result=result)

    assert rca.trace_span_ids == []


async def test_trace_span_ids_extracted_when_present() -> None:
    case = _test_case()
    result = _result(
        "FAIL",
        [],
        trials=[{"trial_index": 0, "verdict": "FAIL", "trace": [{"span_id": "abc123"}]}],
    )
    rca = await analyze_case(test_case=case, result=result)

    assert rca.trace_span_ids == ["abc123"]


def test_prompt_forbids_hidden_internal_speculation() -> None:
    prompt_path = (
        Path(__file__).resolve().parent.parent
        / "app"
        / "agents"
        / "prompts"
        / "suite_case_root_cause_analysis.txt"
    )
    text = prompt_path.read_text(encoding="utf-8").lower()
    for phrase in (
        "hidden prompt",
        "model internal",
        "developer's intent",
        "private infrastructure",
    ):
        assert phrase in text


# =========================================================================
# Integration tests — real HTTP + Suite Runner stack
# =========================================================================


async def test_missing_required_tool_call_deterministic_via_api(client: AsyncClient) -> None:
    token = await _register_and_login(client, "rca1@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    version_id = await _create_version(client, token, agent_id, callable_name="invoke")
    suite_id = await _create_suite(client, token, agent_id)
    case_id = await _create_case(
        client,
        token,
        suite_id,
        name="c1",
        input={},
        expected_tool_calls=[{"tool": "search", "required": True}],
    )

    suite_run = await _create_suite_run(client, token, suite_id, version_id)
    result_id = await _get_result_id_for_case(client, token, str(suite_run["id"]), case_id)

    resp = await client.get(_rca_url(str(suite_run["id"]), result_id), headers=_auth_headers(token))

    assert resp.status_code == 200
    body = resp.json()
    assert body["tier"] == "deterministic"
    assert body["root_cause_category"] == "missing_required_tool_call"


async def test_schema_field_missing_deterministic_via_api(client: AsyncClient) -> None:
    token = await _register_and_login(client, "rca2@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    version_id = await _create_version(client, token, agent_id, callable_name="invoke_async")
    suite_id = await _create_suite(client, token, agent_id)
    case_id = await _create_case(
        client,
        token,
        suite_id,
        name="c1",
        input={},
        # output_schema alone is not a recognized ground-truth field
        # (Phase 12's GROUND_TRUTH_FIELDS) — a trivial always-satisfied
        # assertion supplies real ground truth without interfering with
        # the schema failure this test is actually about.
        assertions=[{"path": "$.answer", "op": "exists"}],
        output_schema={
            "type": "object",
            "required": ["answer", "confidence"],
            "properties": {"answer": {"type": "string"}, "confidence": {"type": "number"}},
        },
    )

    suite_run = await _create_suite_run(client, token, suite_id, version_id)
    result_id = await _get_result_id_for_case(client, token, str(suite_run["id"]), case_id)

    resp = await client.get(_rca_url(str(suite_run["id"]), result_id), headers=_auth_headers(token))

    assert resp.status_code == 200
    body = resp.json()
    assert body["tier"] == "deterministic"
    assert body["root_cause_category"] == "schema_field_missing"


async def test_latency_exceeded_deterministic_via_api(client: AsyncClient) -> None:
    token = await _register_and_login(client, "rca3@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    version_id = await _create_version(client, token, agent_id, callable_name="invoke_slow")
    suite_id = await _create_suite(client, token, agent_id)
    case_id = await _create_case(
        client,
        token,
        suite_id,
        name="c1",
        input={},
        expected_output="done",
        latency_threshold_ms=50,
    )

    suite_run = await _create_suite_run(client, token, suite_id, version_id)
    result_id = await _get_result_id_for_case(client, token, str(suite_run["id"]), case_id)

    resp = await client.get(_rca_url(str(suite_run["id"]), result_id), headers=_auth_headers(token))

    assert resp.status_code == 200
    body = resp.json()
    assert body["tier"] == "deterministic"
    assert body["root_cause_category"] == "latency_exceeded"


async def test_forbidden_tool_deterministic_via_api(client: AsyncClient) -> None:
    token = await _register_and_login(client, "rca4@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    version_id = await _create_version(
        client, token, agent_id, callable_name="invoke_with_safe_tool_call"
    )
    suite_id = await _create_suite(client, token, agent_id)
    case_id = await _create_case(
        client,
        token,
        suite_id,
        name="c1",
        input={},
        expected_output="done",
        allowed_tools=["some_other_tool"],
    )

    suite_run = await _create_suite_run(client, token, suite_id, version_id)
    result_id = await _get_result_id_for_case(client, token, str(suite_run["id"]), case_id)

    resp = await client.get(_rca_url(str(suite_run["id"]), result_id), headers=_auth_headers(token))

    assert resp.status_code == 200
    body = resp.json()
    assert body["tier"] == "deterministic"
    assert body["root_cause_category"] == "forbidden_tool_called"


async def test_deterministic_rca_does_not_call_llm_via_api(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _fail_if_called(*args: object, **kwargs: object) -> object:
        raise AssertionError("call_model must not be invoked for a deterministic match")

    monkeypatch.setattr(rca_service_mod, "call_model", _fail_if_called)

    token = await _register_and_login(client, "rca5@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    version_id = await _create_version(client, token, agent_id, callable_name="invoke")
    suite_id = await _create_suite(client, token, agent_id)
    case_id = await _create_case(
        client,
        token,
        suite_id,
        name="c1",
        input={},
        expected_tool_calls=[{"tool": "search", "required": True}],
    )

    suite_run = await _create_suite_run(client, token, suite_id, version_id)
    result_id = await _get_result_id_for_case(client, token, str(suite_run["id"]), case_id)

    resp = await client.get(_rca_url(str(suite_run["id"]), result_id), headers=_auth_headers(token))

    assert resp.status_code == 200
    assert resp.json()["tier"] == "deterministic"


async def test_unmatched_failure_uses_llm_tier_via_api(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _fake_call_model(
        prompt: str, schema: type[RootCauseHypothesis], **kwargs: object
    ) -> RootCauseHypothesis:
        return schema(hypothesis="The expected_output check failed to match the actual output.")

    monkeypatch.setattr(rca_service_mod, "call_model", _fake_call_model)

    token = await _register_and_login(client, "rca6@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    version_id = await _create_version(client, token, agent_id, callable_name="invoke_plain_string")
    suite_id = await _create_suite(client, token, agent_id)
    case_id = await _create_case(
        client, token, suite_id, name="c1", input={"question": "hi"}, expected_output="echo: hi"
    )

    suite_run = await _create_suite_run(client, token, suite_id, version_id)
    result_id = await _get_result_id_for_case(client, token, str(suite_run["id"]), case_id)

    resp = await client.get(_rca_url(str(suite_run["id"]), result_id), headers=_auth_headers(token))

    assert resp.status_code == 200
    body = resp.json()
    assert body["tier"] == "llm_hypothesis"
    assert body["root_cause_category"] is None


async def test_cross_user_rca_access_is_rejected(client: AsyncClient) -> None:
    owner_token = await _register_and_login(client, "rca7-owner@example.com")
    project_id = await _create_project(client, owner_token)
    agent_id = await _create_agent(client, owner_token, project_id)
    version_id = await _create_version(client, owner_token, agent_id, callable_name="invoke")
    suite_id = await _create_suite(client, owner_token, agent_id)
    case_id = await _create_case(
        client, owner_token, suite_id, name="c1", input={}, expected_output="echo: "
    )
    suite_run = await _create_suite_run(client, owner_token, suite_id, version_id)
    result_id = await _get_result_id_for_case(client, owner_token, str(suite_run["id"]), case_id)

    other_token = await _register_and_login(client, "rca7-other@example.com")
    resp = await client.get(
        _rca_url(str(suite_run["id"]), result_id), headers=_auth_headers(other_token)
    )

    assert resp.status_code in (403, 404)


async def test_safety_evidence_available_to_rca(client: AsyncClient) -> None:
    token = await _register_and_login(client, "rca8@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    version_id = await _create_version(
        client, token, agent_id, callable_name="invoke_with_unsafe_tool_call"
    )
    suite_id = await _create_suite(client, token, agent_id)
    case_id = await _create_case(
        client, token, suite_id, name="c1", input={}, expected_output="done"
    )

    suite_run = await _create_suite_run(client, token, suite_id, version_id)
    result_id = await _get_result_id_for_case(client, token, str(suite_run["id"]), case_id)

    resp = await client.get(_rca_url(str(suite_run["id"]), result_id), headers=_auth_headers(token))

    assert resp.status_code == 200
    # The case PASSes (output "done" matches) but a safety check still
    # failed — not one of the 4 RCA whitelist categories, so it falls
    # through; still, no exception, and the case remains fully analyzable.
    assert resp.json()["verdict"] == "PASS"


async def test_regression_evidence_available_to_rca(client: AsyncClient) -> None:
    token = await _register_and_login(client, "rca9@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    baseline_version_id = await _create_version(
        client, token, agent_id, label="v1", callable_name="invoke"
    )
    candidate_version_id = await _create_version(
        client, token, agent_id, label="v2", callable_name="invoke_plain_string"
    )
    await _promote_baseline(client, token, agent_id, baseline_version_id)
    suite_id = await _create_suite(client, token, agent_id)
    case_id = await _create_case(
        client, token, suite_id, name="c1", input={"question": "hi"}, expected_output="echo: hi"
    )

    await _create_suite_run(client, token, suite_id, baseline_version_id)
    candidate_run = await _create_suite_run(client, token, suite_id, candidate_version_id)
    result_id = await _get_result_id_for_case(client, token, str(candidate_run["id"]), case_id)

    resp = await client.get(
        _rca_url(str(candidate_run["id"]), result_id), headers=_auth_headers(token)
    )

    assert resp.status_code == 200
    regression = resp.json()["regression"]
    assert regression is not None
    assert regression["baseline_verdict"] == "PASS"
    assert regression["candidate_verdict"] == "FAIL"


# =========================================================================
# Security / persistence static checks
# =========================================================================

_SOURCE_FILES = [
    Path(__file__).resolve().parent.parent / "app" / "rca" / "evidence.py",
    Path(__file__).resolve().parent.parent / "app" / "rca" / "service.py",
    Path(__file__).resolve().parent.parent / "app" / "services" / "rca_service.py",
    Path(__file__).resolve().parent.parent / "app" / "api" / "v1" / "rca.py",
]


def test_no_eval_exec_or_subprocess_in_rca_source() -> None:
    forbidden = re.compile(r"\beval\(|\bexec\(|subprocess\.|os\.system\(")
    for path in _SOURCE_FILES:
        assert not forbidden.search(path.read_text(encoding="utf-8")), path


def test_rca_never_reruns_agent_or_evaluators() -> None:
    forbidden_symbols = (
        "build_adapter",
        "adapter.invoke",
        "evaluate_tool_call_safety",
        "evaluate_output_safety",
        "evaluate_grounding(",
        "execute_suite_run",
    )
    for path in [
        Path(__file__).resolve().parent.parent / "app" / "rca" / "evidence.py",
        Path(__file__).resolve().parent.parent / "app" / "services" / "rca_service.py",
    ]:
        source = path.read_text(encoding="utf-8")
        for symbol in forbidden_symbols:
            assert symbol not in source, f"found forbidden symbol {symbol!r} in {path}"


def test_no_rca_result_persistence_model_exists() -> None:
    models_dir = Path(__file__).resolve().parent.parent / "app" / "models"
    names = [p.name for p in models_dir.glob("*.py")]
    assert not any("rca" in name.lower() or "root_cause" in name.lower() for name in names)


def test_no_paid_service_reference_in_rca_source() -> None:
    forbidden = ("openai", "anthropic", "genai_client", "litellm")
    for path in _SOURCE_FILES:
        lowered = path.read_text(encoding="utf-8").lower()
        for symbol in forbidden:
            assert symbol not in lowered, f"found {symbol!r} in {path}"
