"""Phase 19 — AutoFix tests.

Two layers:
  - Pure unit tests against app.autofix.proposal/app.autofix.apply's
    functions directly — the deterministic RCA-category-to-proposal
    mapping and the whitelist validation, no DB/HTTP/LLM needed.
  - Integration tests through the full HTTP stack (real LocalAdapter,
    real Suite Runner, real Phase 18 Approval system) — proposal
    creation, approval-gated apply, re-verification, and every locked
    security boundary (no adapter_config writes, no arbitrary fields, no
    code execution, no external-agent "fix" calls).
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.evaluation.checks.llm_judge as llm_judge_mod
import app.services.suite_runner as suite_runner_mod
from app.autofix.apply import bound_trial_count, validate_agent_field, validate_testcase_field
from app.autofix.proposal import (
    AGENT_DEFAULT_EDITABLE_FIELDS,
    MAX_AUTOFIX_TRIAL_COUNT,
    TESTCASE_EDITABLE_FIELDS,
    build_autofix_proposal,
)
from app.core.exceptions import ValidationError
from app.models.agent import Agent
from app.models.approval import Approval
from app.models.test_case import TestCase
from app.models.test_case_result import TestCaseResult
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


@pytest.fixture(autouse=True)
def _judge_never_called_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """None of this file's TestCases declare a rubric, so the judge
    should never be invoked — a hard safety net for these tests."""

    async def _fail_if_called(*args: object, **kwargs: object) -> object:
        raise AssertionError("no LLM call should occur in these AutoFix tests")

    monkeypatch.setattr(llm_judge_mod, "call_model", _fail_if_called)


def _autofix_url(suite_run_id: str, result_id: str, *, prefer_agent_default: bool = False) -> str:
    url = f"/api/v1/suite-runs/{suite_run_id}/results/{result_id}/autofix"
    if prefer_agent_default:
        url += "?prefer_agent_default=true"
    return url


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


async def _find_approval_for_suite_run(client: AsyncClient, token: str, suite_run_id: str) -> dict:
    approvals = (await client.get("/api/v1/approvals", headers=_auth_headers(token))).json()
    matching = [a for a in approvals if a.get("suite_run_id") == suite_run_id]
    assert len(matching) == 1, f"expected exactly one approval for {suite_run_id}, got {matching}"
    return matching[0]


# =========================================================================
# Unit tests — app.autofix.proposal.build_autofix_proposal
# =========================================================================


def _check(check_type: str, status: str, detail: str = "x", metadata: dict | None = None) -> dict:
    return {
        "check_type": check_type,
        "status": status,
        "detail": detail,
        "metadata": metadata or {},
    }


def _test_case(**overrides: object) -> TestCase:
    defaults: dict[str, object] = {"id": uuid.uuid4(), "name": "c1", "trial_count": 1}
    defaults.update(overrides)
    return TestCase(**defaults)  # type: ignore[arg-type]


def _result(
    checks: list[dict], trials: list[dict] | None = None, verdict: str = "FAIL"
) -> TestCaseResult:
    return TestCaseResult(
        id=uuid.uuid4(),
        suite_run_id=uuid.uuid4(),
        test_case_id=uuid.uuid4(),
        verdict=verdict,
        verdict_method="majority",
        checks=checks,
        trials=trials or [],
        actual_output=None,
        latency_ms=10,
        error=None,
        suggested_fix=None,
    )


def test_forbidden_tool_proposes_owner_suggestion_only() -> None:
    case = _test_case()
    result = _result([_check("forbidden_tool_calls", "fail", "forbidden tool call(s) made: shell")])
    proposal = build_autofix_proposal(case, result)
    assert proposal.option == "owner_suggestion"
    assert proposal.requires_approval is False


def test_missing_required_tool_proposes_testcase_edit() -> None:
    case = _test_case(expected_tool_calls=[{"tool": "search", "required": True}])
    result = _result(
        [
            _check(
                "tool_call[0]:search",
                "fail",
                "missing required tool call: 'search' was never called",
            )
        ]
    )
    proposal = build_autofix_proposal(case, result)
    assert proposal.option == "testcase_edit"
    assert proposal.field == "expected_tool_calls"
    assert proposal.proposed_value == []
    assert proposal.requires_approval is True


def test_schema_field_missing_proposes_testcase_edit_by_default() -> None:
    case = _test_case(output_schema={"type": "object", "required": ["confidence"]})
    result = _result(
        [
            _check(
                "output_schema",
                "fail",
                "schema validation failed at <root>: 'confidence' is a required property",
            )
        ]
    )
    proposal = build_autofix_proposal(case, result)
    assert proposal.option == "testcase_edit"
    assert proposal.field == "output_schema"
    assert proposal.proposed_value["required"] == []


def test_schema_field_missing_proposes_agent_default_edit_when_preferred() -> None:
    case = _test_case(output_schema={"type": "object", "required": ["confidence"]})
    result = _result(
        [
            _check(
                "output_schema",
                "fail",
                "schema validation failed at <root>: 'confidence' is a required property",
            )
        ]
    )
    agent = Agent(
        id=uuid.uuid4(), default_output_schema={"type": "object", "required": ["confidence"]}
    )
    proposal = build_autofix_proposal(case, result, agent=agent, prefer_agent_default=True)
    assert proposal.option == "agent_default_edit"
    assert proposal.field == "default_output_schema"
    assert proposal.proposed_value["required"] == []


def test_latency_exceeded_proposes_bounded_trial_increase() -> None:
    case = _test_case(trial_count=1)
    result = _result([_check("latency", "fail", "latency 500ms exceeds the 200ms threshold")])
    proposal = build_autofix_proposal(case, result)
    assert proposal.option == "trial_count_increase"
    assert proposal.field == "trial_count"
    assert proposal.proposed_value == 2
    assert proposal.proposed_value <= MAX_AUTOFIX_TRIAL_COUNT


def test_mixed_trial_results_proposes_trial_increase() -> None:
    case = _test_case(trial_count=2)
    result = _result(
        checks=[],
        trials=[{"trial_index": 0, "verdict": "PASS"}, {"trial_index": 1, "verdict": "FAIL"}],
        verdict="INCONCLUSIVE",
    )
    proposal = build_autofix_proposal(case, result)
    assert proposal.option == "trial_count_increase"


def test_trial_count_at_max_falls_back_to_owner_suggestion() -> None:
    case = _test_case(trial_count=MAX_AUTOFIX_TRIAL_COUNT)
    result = _result([_check("latency", "fail", "latency 500ms exceeds the 200ms threshold")])
    proposal = build_autofix_proposal(case, result)
    assert proposal.option == "owner_suggestion"
    assert proposal.requires_approval is False


def test_unmatched_failure_falls_back_to_owner_suggestion() -> None:
    case = _test_case()
    result = _result(
        [_check("expected_output", "fail", "mismatch: expected 'a', got 'b'")], verdict="FAIL"
    )
    proposal = build_autofix_proposal(case, result)
    assert proposal.option == "owner_suggestion"
    assert proposal.requires_approval is False


def test_trial_count_increase_is_always_within_bound() -> None:
    for start in range(1, 20):
        case = _test_case(trial_count=start)
        result = _result([_check("latency", "fail", "latency 500ms exceeds the 200ms threshold")])
        proposal = build_autofix_proposal(case, result)
        if proposal.option == "trial_count_increase":
            assert proposal.proposed_value <= MAX_AUTOFIX_TRIAL_COUNT


# =========================================================================
# Unit tests — app.autofix.apply whitelist validation
# =========================================================================


def test_validate_testcase_field_accepts_whitelisted_field() -> None:
    validate_testcase_field("expected_output")  # must not raise


def test_validate_testcase_field_rejects_adapter_config() -> None:
    with pytest.raises(ValidationError):
        validate_testcase_field("adapter_config")


def test_validate_testcase_field_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError):
        validate_testcase_field("not_a_real_field")


def test_validate_agent_field_rejects_adapter_config() -> None:
    with pytest.raises(ValidationError):
        validate_agent_field("adapter_config")


def test_validate_agent_field_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError):
        validate_agent_field("name")


def test_bound_trial_count_clamps_to_maximum() -> None:
    assert bound_trial_count(999) == MAX_AUTOFIX_TRIAL_COUNT
    assert bound_trial_count(1) == 1
    assert bound_trial_count(0) == 1


def test_neither_whitelist_contains_adapter_config_or_credentials() -> None:
    all_fields = TESTCASE_EDITABLE_FIELDS | AGENT_DEFAULT_EDITABLE_FIELDS
    for forbidden in ("adapter_config", "credential", "api_key", "secret", "password", "auth"):
        assert not any(forbidden in field.lower() for field in all_fields)


# =========================================================================
# Integration tests — real HTTP stack
# =========================================================================


async def test_testcase_fix_proposal_can_be_created(client: AsyncClient) -> None:
    token = await _register_and_login(client, "autofix1@example.com")
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

    resp = await client.post(
        _autofix_url(str(suite_run["id"]), result_id), headers=_auth_headers(token)
    )

    assert resp.status_code == 201
    body = resp.json()
    assert body["option"] == "testcase_edit"
    assert body["requires_approval"] is True
    assert body["approval_id"] is not None
    assert body["suggested_fix_recorded"] is False


async def test_agent_default_fix_proposal_can_be_created(client: AsyncClient) -> None:
    token = await _register_and_login(client, "autofix2@example.com")
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
        assertions=[{"path": "$.answer", "op": "exists"}],
        output_schema={
            "type": "object",
            "required": ["answer", "confidence"],
            "properties": {"answer": {"type": "string"}, "confidence": {"type": "number"}},
        },
    )

    suite_run = await _create_suite_run(client, token, suite_id, version_id)
    result_id = await _get_result_id_for_case(client, token, str(suite_run["id"]), case_id)

    resp = await client.post(
        _autofix_url(str(suite_run["id"]), result_id, prefer_agent_default=True),
        headers=_auth_headers(token),
    )

    assert resp.status_code == 201
    body = resp.json()
    assert body["option"] == "agent_default_edit"
    assert body["field"] == "default_output_schema"
    assert body["requires_approval"] is True


async def test_increased_trial_proposal_can_be_created(client: AsyncClient) -> None:
    token = await _register_and_login(client, "autofix3@example.com")
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

    resp = await client.post(
        _autofix_url(str(suite_run["id"]), result_id), headers=_auth_headers(token)
    )

    assert resp.status_code == 201
    body = resp.json()
    assert body["option"] == "trial_count_increase"
    assert body["proposed_value"] <= MAX_AUTOFIX_TRIAL_COUNT


async def test_owner_suggestion_stored_as_not_applied(client: AsyncClient) -> None:
    token = await _register_and_login(client, "autofix4@example.com")
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
        allowed_tools=["other"],
    )

    suite_run = await _create_suite_run(client, token, suite_id, version_id)
    result_id = await _get_result_id_for_case(client, token, str(suite_run["id"]), case_id)

    resp = await client.post(
        _autofix_url(str(suite_run["id"]), result_id), headers=_auth_headers(token)
    )

    assert resp.status_code == 201
    body = resp.json()
    assert body["option"] == "owner_suggestion"
    assert body["requires_approval"] is False
    assert body["approval_id"] is None
    assert body["suggested_fix_recorded"] is True

    results = (
        await client.get(
            f"/api/v1/suite-runs/{suite_run['id']}/results", headers=_auth_headers(token)
        )
    ).json()
    assert results[0]["suggested_fix"].startswith("[NOT APPLIED]")


async def test_option_4_creates_no_approval(client: AsyncClient) -> None:
    token = await _register_and_login(client, "autofix5@example.com")
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
        allowed_tools=["other"],
    )

    suite_run = await _create_suite_run(client, token, suite_id, version_id)
    result_id = await _get_result_id_for_case(client, token, str(suite_run["id"]), case_id)
    await client.post(_autofix_url(str(suite_run["id"]), result_id), headers=_auth_headers(token))

    approvals = (await client.get("/api/v1/approvals", headers=_auth_headers(token))).json()
    assert all(a.get("suite_run_id") != str(suite_run["id"]) for a in approvals)


async def test_unapproved_fix_cannot_be_applied(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _register_and_login(client, "autofix6@example.com")
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
    await client.post(_autofix_url(str(suite_run["id"]), result_id), headers=_auth_headers(token))

    # Never decided — the TestCase must remain exactly as it was.
    case_row = (
        await db_session.execute(select(TestCase).where(TestCase.id == uuid.UUID(case_id)))
    ).scalar_one()
    assert case_row.expected_tool_calls == [{"tool": "search", "required": True}]


async def test_approved_testcase_fix_can_be_applied_and_reverified(client: AsyncClient) -> None:
    token = await _register_and_login(client, "autofix7@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    version_id = await _create_version(client, token, agent_id, callable_name="invoke")
    suite_id = await _create_suite(client, token, agent_id)
    case_id = await _create_case(
        client,
        token,
        suite_id,
        name="c1",
        input={"question": "hi"},
        # A second ground-truth field (expected_output) alongside
        # expected_tool_calls — Phase 12's ground-truth rule would
        # otherwise reject AutoFix's proposed edit (emptying
        # expected_tool_calls) if that were this case's only
        # ground-truth mechanism.
        expected_output="echo: hi",
        expected_tool_calls=[{"tool": "search", "required": True}],
    )

    suite_run = await _create_suite_run(client, token, suite_id, version_id)
    result_id = await _get_result_id_for_case(client, token, str(suite_run["id"]), case_id)
    await client.post(_autofix_url(str(suite_run["id"]), result_id), headers=_auth_headers(token))

    approval = await _find_approval_for_suite_run(client, token, str(suite_run["id"]))
    resp = await client.post(
        f"/api/v1/approvals/{approval['id']}/decide",
        json={"approved": True, "reason": "looks safe"},
        headers=_auth_headers(token),
    )

    assert resp.status_code == 200
    decided = resp.json()
    assert decided["status"] == "approved"

    # Re-verification actually ran: a fresh SuiteRun exists, and its
    # outcome is recorded in the (still-JSON) approval reason.
    payload = json.loads(decided["reason"])
    assert "reverification" in payload
    assert payload["reverification"]["suite_run_id"] is not None
    assert payload["reverification"]["new_verdict"] == "PASS"
    assert payload["reverification"]["resolved"] is True

    cases_resp = await client.get(
        f"/api/v1/test-suites/{suite_id}/test-cases", headers=_auth_headers(token)
    )
    updated_case = cases_resp.json()[0]
    assert updated_case["expected_tool_calls"] == []


async def test_approved_agent_default_fix_can_be_applied(client: AsyncClient) -> None:
    token = await _register_and_login(client, "autofix8@example.com")
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
        assertions=[{"path": "$.answer", "op": "exists"}],
        output_schema={
            "type": "object",
            "required": ["answer", "confidence"],
            "properties": {"answer": {"type": "string"}, "confidence": {"type": "number"}},
        },
    )

    suite_run = await _create_suite_run(client, token, suite_id, version_id)
    result_id = await _get_result_id_for_case(client, token, str(suite_run["id"]), case_id)
    await client.post(
        _autofix_url(str(suite_run["id"]), result_id, prefer_agent_default=True),
        headers=_auth_headers(token),
    )

    approval = await _find_approval_for_suite_run(client, token, str(suite_run["id"]))
    resp = await client.post(
        f"/api/v1/approvals/{approval['id']}/decide",
        json={"approved": True},
        headers=_auth_headers(token),
    )

    assert resp.status_code == 200
    agent_resp = await client.get(f"/api/v1/agents/{agent_id}", headers=_auth_headers(token))
    assert agent_resp.json()["default_output_schema"]["required"] == []


async def test_approved_trial_increase_is_bounded_when_applied(client: AsyncClient) -> None:
    token = await _register_and_login(client, "autofix9@example.com")
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
    await client.post(_autofix_url(str(suite_run["id"]), result_id), headers=_auth_headers(token))

    approval = await _find_approval_for_suite_run(client, token, str(suite_run["id"]))
    await client.post(
        f"/api/v1/approvals/{approval['id']}/decide",
        json={"approved": True},
        headers=_auth_headers(token),
    )

    cases_resp = await client.get(
        f"/api/v1/test-suites/{suite_id}/test-cases", headers=_auth_headers(token)
    )
    updated_case = next(c for c in cases_resp.json() if c["id"] == case_id)
    assert 1 < updated_case["trial_count"] <= MAX_AUTOFIX_TRIAL_COUNT


async def test_autofix_cannot_write_adapter_config(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Even a hand-crafted Approval payload targeting adapter_config
    (simulating a compromised/malformed proposal) must be rejected at
    apply time by the whitelist re-validation — not merely relied upon
    to never be proposed in the first place."""
    token = await _register_and_login(client, "autofix10@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    version_id = await _create_version(client, token, agent_id, callable_name="invoke")
    suite_id = await _create_suite(client, token, agent_id)
    case_id = await _create_case(
        client, token, suite_id, name="c1", input={"question": "hi"}, expected_output="echo: hi"
    )
    suite_run = await _create_suite_run(client, token, suite_id, version_id)

    malicious_payload = {
        "autofix": True,
        "action": "testcase_edit",
        "test_case_id": case_id,
        "suite_id": suite_id,
        "agent_id": agent_id,
        "agent_version_id": version_id,
        "field": "adapter_config",
        "proposed_value": {"module_path": "evil", "callable_name": "evil"},
    }
    approval = Approval(
        suite_run_id=uuid.UUID(str(suite_run["id"])),
        node="auto_fix",
        status="pending",
        reason=json.dumps(malicious_payload),
    )
    db_session.add(approval)
    await db_session.commit()

    resp = await client.post(
        f"/api/v1/approvals/{approval.id}/decide",
        json={"approved": True},
        headers=_auth_headers(token),
    )

    assert resp.status_code == 422
    version_resp = await client.get(
        f"/api/v1/agents/{agent_id}/versions", headers=_auth_headers(token)
    )
    assert version_resp.json()[0]["adapter_config"]["module_path"] == "tests.fixtures.toy_agent"


async def test_cross_user_autofix_proposal_is_rejected(client: AsyncClient) -> None:
    owner_token = await _register_and_login(client, "autofix11-owner@example.com")
    project_id = await _create_project(client, owner_token)
    agent_id = await _create_agent(client, owner_token, project_id)
    version_id = await _create_version(client, owner_token, agent_id, callable_name="invoke")
    suite_id = await _create_suite(client, owner_token, agent_id)
    case_id = await _create_case(
        client,
        owner_token,
        suite_id,
        name="c1",
        input={"question": "hi"},
        expected_output="echo: hi",
    )
    suite_run = await _create_suite_run(client, owner_token, suite_id, version_id)
    result_id = await _get_result_id_for_case(client, owner_token, str(suite_run["id"]), case_id)

    other_token = await _register_and_login(client, "autofix11-other@example.com")
    resp = await client.post(
        _autofix_url(str(suite_run["id"]), result_id), headers=_auth_headers(other_token)
    )

    assert resp.status_code in (403, 404)


# =========================================================================
# Security / persistence static checks
# =========================================================================

_SOURCE_FILES = [
    Path(__file__).resolve().parent.parent / "app" / "autofix" / "proposal.py",
    Path(__file__).resolve().parent.parent / "app" / "autofix" / "apply.py",
    Path(__file__).resolve().parent.parent / "app" / "services" / "autofix_service.py",
    Path(__file__).resolve().parent.parent / "app" / "api" / "v1" / "autofix.py",
]


def test_no_eval_exec_or_subprocess_in_autofix_source() -> None:
    forbidden = re.compile(r"\beval\(|\bexec\(|subprocess\.|shell=True|os\.system\(")
    for path in _SOURCE_FILES:
        assert not forbidden.search(path.read_text(encoding="utf-8")), path


def test_autofix_never_imports_the_adapter_layer() -> None:
    """AutoFix cannot "call the external agent with a fix": nothing in
    app/autofix/ ever imports build_adapter/AgentAdapter directly. The
    one adapter invocation in this flow is app/services/autofix_service.py's
    reuse of the existing, unmodified execute_suite_run() for
    re-verification — a real re-run of the ORIGINAL test, never a
    "send this fix to the agent" call."""
    for path in [
        Path(__file__).resolve().parent.parent / "app" / "autofix" / "proposal.py",
        Path(__file__).resolve().parent.parent / "app" / "autofix" / "apply.py",
    ]:
        source = path.read_text(encoding="utf-8")
        assert "build_adapter" not in source
        assert "AgentAdapter" not in source
        # The docstrings mention "adapter_config" only in prose
        # explaining that it's never touched — the structural proof is
        # that neither module ever imports the model that even has that
        # column (AgentVersion), so there is no object either could call
        # .adapter_config on in the first place.
        import_lines = [
            line for line in source.splitlines() if line.strip().startswith(("import ", "from "))
        ]
        assert not any("agent_version" in line.lower() for line in import_lines)


def test_no_new_approval_table_or_model_exists() -> None:
    models_dir = Path(__file__).resolve().parent.parent / "app" / "models"
    names = [p.name.lower() for p in models_dir.glob("*.py")]
    for forbidden in (
        "autofixresult",
        "autofix_result",
        "autofixapproval",
        "autofix_approval",
        "fixapproval",
    ):
        assert not any(forbidden in name for name in names)
    # Exactly one Approval model file, reused.
    assert "approval.py" in names


def test_no_paid_service_reference_in_autofix_source() -> None:
    forbidden = ("openai", "anthropic", "genai", "gemini")
    for path in _SOURCE_FILES:
        lowered = path.read_text(encoding="utf-8").lower()
        for symbol in forbidden:
            assert symbol not in lowered, f"found {symbol!r} in {path}"
