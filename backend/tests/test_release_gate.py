"""Phase 18 — Release Gate tests.

Three layers:
  - Pure unit tests against app.release_gate.gate's functions directly —
    exhaustive coverage of the locked 5-category hard gate and the
    reused compute_soft_score() adaptation, no DB/HTTP/LLM needed.
  - Integration tests through the full HTTP + Suite Runner stack (real
    LocalAdapter, real background execution, real Phase 13/15/16/17
    evidence) — ownership, status gating, end-to-end hard-gate
    triggers, approval creation, and no-rerun guarantees.
  - Security/persistence static checks.
"""

from __future__ import annotations

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
from app.agents.release_decision import compute_soft_score
from app.ai.client import AIClientError
from app.approvals import service as approvals_service
from app.models.approval import Approval
from app.release_gate.gate import evaluate_case_hard_gate, evaluate_suite_hard_gate, soft_score
from app.repositories.run_repository import RunRepository
from app.repositories.suite_run_repository import SuiteRunRepository
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


async def _insert_raw_suite_run(
    db_session: AsyncSession, *, suite_id: str, agent_version_id: str, status: str
) -> str:
    repo = SuiteRunRepository(db_session)
    suite_run = await repo.create(
        suite_id=uuid.UUID(suite_id),
        agent_version_id=uuid.UUID(agent_version_id),
        max_concurrency=1,
    )
    if status != "pending":
        suite_run = await repo.update(suite_run, status=status)
    await db_session.commit()
    return str(suite_run.id)


def _release_url(suite_run_id: str) -> str:
    return f"/api/v1/suite-runs/{suite_run_id}/release"


# =========================================================================
# Unit tests — app.release_gate.gate (pure functions)
# =========================================================================


def _check(check_type: str, status: str, detail: str = "x") -> dict:
    return {"check_type": check_type, "status": status, "detail": detail, "metadata": {}}


def test_safety_flag_triggers_hard_gate() -> None:
    reasons = evaluate_case_hard_gate(uuid.uuid4(), "PASS", [_check("safety:output", "fail")])
    assert any(r.category == "safety_flag" for r in reasons)


def test_forbidden_tool_triggers_hard_gate() -> None:
    reasons = evaluate_case_hard_gate(
        uuid.uuid4(), "FAIL", [_check("forbidden_tool_calls", "fail")]
    )
    assert any(r.category == "forbidden_tool_called" for r in reasons)


def test_missing_required_tool_triggers_hard_gate() -> None:
    reasons = evaluate_case_hard_gate(
        uuid.uuid4(),
        "FAIL",
        [
            _check(
                "tool_call[0]:search",
                "fail",
                "missing required tool call: 'search' was never called",
            )
        ],
    )
    assert any(r.category == "missing_required_tool_call" for r in reasons)


def test_schema_failure_triggers_hard_gate() -> None:
    reasons = evaluate_case_hard_gate(uuid.uuid4(), "FAIL", [_check("output_schema", "fail")])
    assert any(r.category == "schema_failure" for r in reasons)


def test_expected_output_fail_triggers_correctness_hard_gate() -> None:
    reasons = evaluate_case_hard_gate(
        uuid.uuid4(),
        "FAIL",
        [_check("expected_output", "fail", "mismatch: expected 'a', got 'b'")],
    )
    assert any(r.category == "correctness_failure" for r in reasons)


def test_assertion_fail_triggers_correctness_hard_gate() -> None:
    reasons = evaluate_case_hard_gate(
        uuid.uuid4(),
        "FAIL",
        [_check("assertion[0]", "fail", "$.status: expected 'ok', got 'error'")],
    )
    assert any(r.category == "correctness_failure" for r in reasons)


def test_correctness_hard_gate_requires_actual_evidence_not_bare_verdict() -> None:
    """§22 correction: verdict == "FAIL" alone must never be the sole
    trigger — a FAIL with no correctness-relevant check evidence at all
    (e.g. every deterministic check that failed was `latency`, already
    excluded) produces no correctness_failure reason."""
    reasons = evaluate_case_hard_gate(uuid.uuid4(), "FAIL", [])
    assert not any(r.category == "correctness_failure" for r in reasons)


def test_pass_verdict_with_no_bad_checks_has_no_hard_gate_reasons() -> None:
    reasons = evaluate_case_hard_gate(uuid.uuid4(), "PASS", [_check("expected_output", "pass")])
    assert reasons == []


def test_inconclusive_verdict_alone_is_not_a_hard_gate_reason() -> None:
    """A rubric-only case (INCONCLUSIVE, no deterministic checks at all)
    must never automatically hard-gate (§16)."""
    reasons = evaluate_case_hard_gate(
        uuid.uuid4(), "INCONCLUSIVE", [_check("rubric", "pending_llm")]
    )
    assert reasons == []


def test_latency_only_failure_is_not_a_hard_gate_reason() -> None:
    """§15/§30 correction: performance alone is not a hard gate — a case
    that FAILs *solely* because of `latency` must produce ZERO hard-gate
    reasons, not a "correctness_failure" fallback derived from the bare
    verdict (that was the exact bug this correction fixes)."""
    reasons = evaluate_case_hard_gate(
        uuid.uuid4(),
        "FAIL",
        [_check("latency", "fail", "latency 500ms exceeds the 200ms threshold")],
    )
    assert reasons == []


def test_latency_exceeded_is_not_a_hard_gate_category_even_when_other_checks_also_fail() -> None:
    """The `latency` check itself never contributes a hard-gate reason —
    verified alongside a genuine, independent correctness failure so the
    correctness_failure reason present here can only have come from the
    expected_output check, never from latency."""
    reasons = evaluate_case_hard_gate(
        uuid.uuid4(),
        "FAIL",
        [
            _check("latency", "fail", "latency 500ms exceeds the 200ms threshold"),
            _check("expected_output", "fail", "mismatch: expected 'a', got 'b'"),
        ],
    )
    categories = {r.category for r in reasons}
    assert "latency_exceeded" not in categories
    assert "correctness_failure" in categories


def test_grounding_failure_alone_is_not_a_hard_gate_reason() -> None:
    """§15's hard-gate list does not include grounding as its own
    category — documented, deliberate classification."""
    reasons = evaluate_case_hard_gate(uuid.uuid4(), "PASS", [_check("grounding", "fail")])
    assert reasons == []


def test_suite_hard_gate_passes_when_every_case_is_clean() -> None:
    results = [(uuid.uuid4(), "PASS", [_check("expected_output", "pass")]) for _ in range(5)]
    result = evaluate_suite_hard_gate(results)
    assert result.passed is True
    assert result.reasons == []


def test_suite_hard_gate_holds_when_one_case_among_many_is_unsafe() -> None:
    """§26: a high pass rate cannot override a single safety flag."""
    clean = [(uuid.uuid4(), "PASS", [_check("expected_output", "pass")]) for _ in range(9)]
    dirty = [(uuid.uuid4(), "PASS", [_check("safety:output", "fail")])]
    result = evaluate_suite_hard_gate(clean + dirty)
    assert result.passed is False
    assert any(r.category == "safety_flag" for r in result.reasons)


def test_suite_hard_gate_holds_when_one_case_has_forbidden_tool() -> None:
    clean = [(uuid.uuid4(), "PASS", [_check("expected_output", "pass")]) for _ in range(9)]
    dirty = [(uuid.uuid4(), "FAIL", [_check("forbidden_tool_calls", "fail")])]
    result = evaluate_suite_hard_gate(clean + dirty)
    assert result.passed is False


def test_suite_hard_gate_holds_when_one_case_is_missing_required_tool() -> None:
    clean = [(uuid.uuid4(), "PASS", [_check("expected_output", "pass")]) for _ in range(9)]
    dirty = [
        (
            uuid.uuid4(),
            "FAIL",
            [_check("tool_call[0]:x", "fail", "missing required tool call: 'x' was never called")],
        )
    ]
    result = evaluate_suite_hard_gate(clean + dirty)
    assert result.passed is False


def test_soft_score_reuses_compute_soft_score_formula() -> None:
    result = soft_score(pass_rate=0.75)
    expected = compute_soft_score(
        evaluations=[{"score": 0.75}], retry_count=0, auto_fix_applied=False
    )
    assert result.value == expected.value
    assert result.components == expected.components


def test_soft_score_handles_none_pass_rate_as_zero_base() -> None:
    result = soft_score(pass_rate=None)
    assert result.components["base_evaluation_score"] == 0.0


def test_soft_score_never_applies_retry_or_autofix_penalty() -> None:
    """Phase 19 AutoFix does not exist and the Suite Runner has no retry
    concept — §17's "represent as zero/not-applicable" instruction."""
    result = soft_score(pass_rate=1.0)
    assert "retry_penalty" not in result.components
    assert "auto_fix_penalty" not in result.components


# =========================================================================
# Integration tests — real HTTP + Suite Runner stack
# =========================================================================


async def test_safety_flag_holds_release(client: AsyncClient) -> None:
    token = await _register_and_login(client, "gate1@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    version_id = await _create_version(
        client, token, agent_id, callable_name="invoke_with_unsafe_tool_call"
    )
    suite_id = await _create_suite(client, token, agent_id)
    await _create_case(client, token, suite_id, name="c1", input={}, expected_output="done")

    suite_run = await _create_suite_run(client, token, suite_id, version_id)
    resp = await client.get(f"/api/v1/suite-runs/{suite_run['id']}", headers=_auth_headers(token))
    assert resp.json()["status"] in ("completed", "failed")

    resp = await client.post(_release_url(str(suite_run["id"])), headers=_auth_headers(token))

    assert resp.status_code == 200
    body = resp.json()
    assert body["decision"] == "hold"
    assert body["hard_gate_passed"] is False
    assert any(r["category"] == "safety_flag" for r in body["hard_gate_reasons"])


async def test_case_verdict_stays_pass_while_release_holds_on_same_safety_flag(
    client: AsyncClient,
) -> None:
    """The exact chain a case's own TestCaseResult.verdict (Phase 13,
    unaffected by Phase 15 safety — see
    tests/test_safety_grounding.py::test_phase13_verdict_computation_is_unaffected_by_safety_or_grounding)
    and the Release Gate's independent use of that same safety evidence
    (this module's own test_safety_flag_holds_release) are two facts
    about ONE run, never contradicting each other: a case can be PASS
    while the release it belongs to is HELD for the very safety flag
    that case carries. Neither half alone proves the two are connected
    correctly — this asserts both against the same suite run."""
    token = await _register_and_login(client, "gate1b@example.com")
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
    assert results[0]["verdict"] == "PASS"

    resp = await client.post(_release_url(str(suite_run["id"])), headers=_auth_headers(token))

    assert resp.status_code == 200
    body = resp.json()
    assert body["decision"] == "hold"
    assert body["hard_gate_passed"] is False
    assert any(r["category"] == "safety_flag" for r in body["hard_gate_reasons"])


async def test_forbidden_tool_holds_release(client: AsyncClient) -> None:
    token = await _register_and_login(client, "gate2@example.com")
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
        allowed_tools=["some_other_tool"],
    )

    suite_run = await _create_suite_run(client, token, suite_id, version_id)
    resp = await client.post(_release_url(str(suite_run["id"])), headers=_auth_headers(token))

    assert resp.status_code == 200
    body = resp.json()
    assert body["decision"] == "hold"
    assert any(r["category"] == "forbidden_tool_called" for r in body["hard_gate_reasons"])


async def test_missing_required_tool_holds_release(client: AsyncClient) -> None:
    token = await _register_and_login(client, "gate3@example.com")
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
        expected_tool_calls=[{"tool": "search", "required": True}],
    )

    suite_run = await _create_suite_run(client, token, suite_id, version_id)
    resp = await client.post(_release_url(str(suite_run["id"])), headers=_auth_headers(token))

    assert resp.status_code == 200
    body = resp.json()
    assert body["decision"] == "hold"
    assert any(r["category"] == "missing_required_tool_call" for r in body["hard_gate_reasons"])


async def test_schema_failure_holds_release(client: AsyncClient) -> None:
    token = await _register_and_login(client, "gate4@example.com")
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
        assertions=[{"path": "$.answer", "op": "exists"}],
        output_schema={
            "type": "object",
            "required": ["answer", "confidence"],
            "properties": {"answer": {"type": "string"}, "confidence": {"type": "number"}},
        },
    )

    suite_run = await _create_suite_run(client, token, suite_id, version_id)
    resp = await client.post(_release_url(str(suite_run["id"])), headers=_auth_headers(token))

    assert resp.status_code == 200
    body = resp.json()
    assert body["decision"] == "hold"
    assert any(r["category"] == "schema_failure" for r in body["hard_gate_reasons"])


async def test_correctness_failure_holds_release(client: AsyncClient) -> None:
    token = await _register_and_login(client, "gate5@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    version_id = await _create_version(client, token, agent_id, callable_name="invoke_plain_string")
    suite_id = await _create_suite(client, token, agent_id)
    await _create_case(
        client, token, suite_id, name="c1", input={"question": "hi"}, expected_output="echo: hi"
    )

    suite_run = await _create_suite_run(client, token, suite_id, version_id)
    resp = await client.post(_release_url(str(suite_run["id"])), headers=_auth_headers(token))

    assert resp.status_code == 200
    body = resp.json()
    assert body["decision"] == "hold"
    assert any(r["category"] == "correctness_failure" for r in body["hard_gate_reasons"])


async def test_latency_only_failure_does_not_hold_release(client: AsyncClient) -> None:
    """§22/§30 correction: a case whose *only* deterministic failure is
    `latency` FAILs (verdict == "FAIL") but must NOT hard-gate — latency
    is a real, separate RCA category (§6/§9), never one of §15's five
    named hard-gate categories."""
    token = await _register_and_login(client, "gate19@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    version_id = await _create_version(client, token, agent_id, callable_name="invoke_slow")
    suite_id = await _create_suite(client, token, agent_id)
    await _create_case(
        client,
        token,
        suite_id,
        name="c1",
        input={},
        expected_output="done",
        latency_threshold_ms=50,
    )

    suite_run = await _create_suite_run(client, token, suite_id, version_id)
    resp = await client.get(
        f"/api/v1/suite-runs/{suite_run['id']}/results", headers=_auth_headers(token)
    )
    assert resp.json()[0]["verdict"] == "FAIL"  # latency alone makes the deterministic verdict FAIL

    resp = await client.post(_release_url(str(suite_run["id"])), headers=_auth_headers(token))

    assert resp.status_code == 200
    body = resp.json()
    assert body["decision"] == "pass"
    assert body["hard_gate_passed"] is True
    assert body["hard_gate_reasons"] == []


async def test_subjective_rubric_only_does_not_automatically_hold(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Phase 19: this case is rubric-only, so the Suite Runner now
    # actually invokes the LLM judge (app/evaluation/checks/llm_judge.py)
    # to resolve it — mocked here (judge "unavailable") so this test
    # deterministically observes the pre-judge-resolution INCONCLUSIVE
    # state it's actually testing (the hard-gate exclusion), rather than
    # depending on a real judge call's outcome.
    async def _raise(*args: object, **kwargs: object) -> object:
        raise AIClientError("no judge configured in this test")

    monkeypatch.setattr(llm_judge_mod, "call_model", _raise)

    token = await _register_and_login(client, "gate6@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    version_id = await _create_version(client, token, agent_id, callable_name="invoke")
    suite_id = await _create_suite(client, token, agent_id)
    await _create_case(
        client, token, suite_id, name="c1", input={}, rubric="Was the response helpful?"
    )

    suite_run = await _create_suite_run(client, token, suite_id, version_id)
    resp = await client.post(_release_url(str(suite_run["id"])), headers=_auth_headers(token))

    assert resp.status_code == 200
    body = resp.json()
    assert body["decision"] == "pass"
    assert body["hard_gate_passed"] is True
    assert body["inconclusive_count"] == 1
    assert body["rubric_case_count"] == 1


async def test_high_pass_rate_cannot_override_safety_hard_gate(client: AsyncClient) -> None:
    token = await _register_and_login(client, "gate7@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    version_id = await _create_version(
        client, token, agent_id, callable_name="invoke_conditional_tool_call"
    )
    suite_id = await _create_suite(client, token, agent_id)
    for i in range(4):
        await _create_case(
            client, token, suite_id, name=f"clean-{i}", input={}, expected_output="done"
        )
    await _create_case(
        client,
        token,
        suite_id,
        name="unsafe-one",
        input={"unsafe": True},
        expected_output="done",
    )

    suite_run = await _create_suite_run(client, token, suite_id, version_id)
    resp = await client.post(_release_url(str(suite_run["id"])), headers=_auth_headers(token))

    assert resp.status_code == 200
    body = resp.json()
    assert body["pass_rate"] == 1.0  # every case's *verdict* PASSes (same output "done")
    assert body["decision"] == "hold"  # yet the safety flag still blocks it
    assert body["hard_gate_passed"] is False


async def test_pass_rate_inconclusive_rate_and_regression_delta_supplied(
    client: AsyncClient,
) -> None:
    token = await _register_and_login(client, "gate8@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    baseline_version_id = await _create_version(
        client, token, agent_id, label="v1", callable_name="invoke"
    )
    candidate_version_id = await _create_version(
        client, token, agent_id, label="v2", callable_name="invoke"
    )
    resp = await client.post(
        f"/api/v1/agents/{agent_id}/versions/{baseline_version_id}/baseline",
        headers=_auth_headers(token),
    )
    assert resp.status_code == 200
    suite_id = await _create_suite(client, token, agent_id)
    await _create_case(
        client, token, suite_id, name="c1", input={"question": "hi"}, expected_output="echo: hi"
    )

    await _create_suite_run(client, token, suite_id, baseline_version_id)
    candidate_run = await _create_suite_run(client, token, suite_id, candidate_version_id)

    resp = await client.post(_release_url(str(candidate_run["id"])), headers=_auth_headers(token))

    assert resp.status_code == 200
    body = resp.json()
    assert body["pass_rate"] == 1.0
    assert body["inconclusive_rate"] == 0.0
    assert body["regression"]["available"] is True
    assert body["regression"]["pass_rate_delta"] == 0.0


async def test_trials_do_not_inflate_release_gate_counts(client: AsyncClient) -> None:
    token = await _register_and_login(client, "gate9@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    version_id = await _create_version(
        client, token, agent_id, callable_name="invoke_alternating_output"
    )
    suite_id = await _create_suite(client, token, agent_id)
    await _create_case(
        client, token, suite_id, name="c1", input={}, expected_output="yes", trial_count=4
    )

    toy_agent.reset_alternating_state()
    suite_run = await _create_suite_run(client, token, suite_id, version_id)

    resp = await client.get(
        f"/api/v1/suite-runs/{suite_run['id']}/results", headers=_auth_headers(token)
    )
    assert resp.json()[0]["verdict"] == "INCONCLUSIVE"  # the locked 2 PASS + 2 FAIL example

    resp = await client.post(_release_url(str(suite_run["id"])), headers=_auth_headers(token))

    assert resp.status_code == 200
    body = resp.json()
    assert body["total_cases"] == 1  # one TestCaseResult, not 4 trials
    assert body["pass_count"] == 0
    assert body["inconclusive_count"] == 1
    assert body["hard_gate_passed"] is True  # INCONCLUSIVE alone is never a hard gate


async def test_valid_completed_suite_run_returns_release_result(client: AsyncClient) -> None:
    token = await _register_and_login(client, "gate10@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    version_id = await _create_version(client, token, agent_id, callable_name="invoke")
    suite_id = await _create_suite(client, token, agent_id)
    await _create_case(
        client, token, suite_id, name="c1", input={"question": "hi"}, expected_output="echo: hi"
    )

    suite_run = await _create_suite_run(client, token, suite_id, version_id)
    resp = await client.post(_release_url(str(suite_run["id"])), headers=_auth_headers(token))

    assert resp.status_code == 200
    assert resp.json()["decision"] == "pass"


async def test_cross_user_release_access_is_rejected(client: AsyncClient) -> None:
    owner_token = await _register_and_login(client, "gate11-owner@example.com")
    project_id = await _create_project(client, owner_token)
    agent_id = await _create_agent(client, owner_token, project_id)
    version_id = await _create_version(client, owner_token, agent_id, callable_name="invoke")
    suite_id = await _create_suite(client, owner_token, agent_id)
    await _create_case(client, owner_token, suite_id, name="c1", input={}, expected_output="echo: ")
    suite_run = await _create_suite_run(client, owner_token, suite_id, version_id)

    other_token = await _register_and_login(client, "gate11-other@example.com")
    resp = await client.post(_release_url(str(suite_run["id"])), headers=_auth_headers(other_token))

    assert resp.status_code in (403, 404)


async def test_incomplete_suite_run_is_rejected(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _register_and_login(client, "gate12@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    version_id = await _create_version(client, token, agent_id, callable_name="invoke")
    suite_id = await _create_suite(client, token, agent_id)
    pending_run_id = await _insert_raw_suite_run(
        db_session, suite_id=suite_id, agent_version_id=version_id, status="running"
    )

    resp = await client.post(_release_url(pending_run_id), headers=_auth_headers(token))

    assert resp.status_code == 409


async def test_release_does_not_rerun_agent(client: AsyncClient) -> None:
    token = await _register_and_login(client, "gate13@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    version_id = await _create_version(client, token, agent_id, callable_name="invoke_incrementing")
    suite_id = await _create_suite(client, token, agent_id)
    await _create_case(client, token, suite_id, name="c1", input={}, expected_output="call-1")

    suite_run = await _create_suite_run(client, token, suite_id, version_id)
    calls_before = toy_agent.get_call_count()
    assert calls_before == 1

    resp = await client.post(_release_url(str(suite_run["id"])), headers=_auth_headers(token))
    resp2 = await client.post(_release_url(str(suite_run["id"])), headers=_auth_headers(token))

    assert resp.status_code == 200
    assert resp2.status_code == 200
    assert toy_agent.get_call_count() == calls_before


async def test_repeated_release_evaluation_is_deterministic(client: AsyncClient) -> None:
    token = await _register_and_login(client, "gate14@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    version_id = await _create_version(client, token, agent_id, callable_name="invoke")
    suite_id = await _create_suite(client, token, agent_id)
    await _create_case(
        client, token, suite_id, name="c1", input={"question": "hi"}, expected_output="echo: hi"
    )

    suite_run = await _create_suite_run(client, token, suite_id, version_id)
    resp1 = await client.post(_release_url(str(suite_run["id"])), headers=_auth_headers(token))
    resp2 = await client.post(_release_url(str(suite_run["id"])), headers=_auth_headers(token))

    assert resp1.json() == resp2.json()


# =========================================================================
# Approval integration
# =========================================================================


async def test_existing_approval_row_created_on_pass(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _register_and_login(client, "gate15@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    version_id = await _create_version(client, token, agent_id, callable_name="invoke")
    suite_id = await _create_suite(client, token, agent_id)
    await _create_case(
        client, token, suite_id, name="c1", input={"question": "hi"}, expected_output="echo: hi"
    )

    suite_run = await _create_suite_run(client, token, suite_id, version_id)
    resp = await client.post(_release_url(str(suite_run["id"])), headers=_auth_headers(token))
    assert resp.json()["decision"] == "pass"

    result = await db_session.execute(
        select(Approval).where(Approval.suite_run_id == uuid.UUID(str(suite_run["id"])))
    )
    approval = result.scalar_one()
    assert approval.run_id is None
    assert approval.node == "release_decision"
    assert approval.status == "pending"


async def test_no_approval_row_created_on_hold(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _register_and_login(client, "gate16@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    version_id = await _create_version(
        client, token, agent_id, callable_name="invoke_with_unsafe_tool_call"
    )
    suite_id = await _create_suite(client, token, agent_id)
    await _create_case(client, token, suite_id, name="c1", input={}, expected_output="done")

    suite_run = await _create_suite_run(client, token, suite_id, version_id)
    resp = await client.post(_release_url(str(suite_run["id"])), headers=_auth_headers(token))
    assert resp.json()["decision"] == "hold"

    result = await db_session.execute(
        select(Approval).where(Approval.suite_run_id == uuid.UUID(str(suite_run["id"])))
    )
    assert result.scalar_one_or_none() is None


async def test_repeated_pass_evaluation_does_not_duplicate_approval(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _register_and_login(client, "gate17@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    version_id = await _create_version(client, token, agent_id, callable_name="invoke")
    suite_id = await _create_suite(client, token, agent_id)
    await _create_case(
        client, token, suite_id, name="c1", input={"question": "hi"}, expected_output="echo: hi"
    )

    suite_run = await _create_suite_run(client, token, suite_id, version_id)
    await client.post(_release_url(str(suite_run["id"])), headers=_auth_headers(token))
    await client.post(_release_url(str(suite_run["id"])), headers=_auth_headers(token))
    await client.post(_release_url(str(suite_run["id"])), headers=_auth_headers(token))

    result = await db_session.execute(
        select(Approval).where(Approval.suite_run_id == uuid.UUID(str(suite_run["id"])))
    )
    approvals = result.scalars().all()
    assert len(approvals) == 1


async def test_cross_user_cannot_trigger_approval_creation(client: AsyncClient) -> None:
    owner_token = await _register_and_login(client, "gate18-owner@example.com")
    project_id = await _create_project(client, owner_token)
    agent_id = await _create_agent(client, owner_token, project_id)
    version_id = await _create_version(client, owner_token, agent_id, callable_name="invoke")
    suite_id = await _create_suite(client, owner_token, agent_id)
    await _create_case(
        client,
        owner_token,
        suite_id,
        name="c1",
        input={"question": "hi"},
        expected_output="echo: hi",
    )
    suite_run = await _create_suite_run(client, owner_token, suite_id, version_id)

    other_token = await _register_and_login(client, "gate18-other@example.com")
    resp = await client.post(_release_url(str(suite_run["id"])), headers=_auth_headers(other_token))
    assert resp.status_code in (403, 404)


# =========================================================================
# SuiteRun approval resolution (Phase 18 correction)
# =========================================================================


async def _create_passing_suite_run(client: AsyncClient, token: str, email_prefix: str) -> str:
    """Registers a fresh user and drives a real SuiteRun to a "pass"
    release decision, which creates a real, pending
    suite_run_id-scoped Approval row. Returns the suite_run id."""
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    version_id = await _create_version(client, token, agent_id, callable_name="invoke")
    suite_id = await _create_suite(client, token, agent_id)
    await _create_case(
        client, token, suite_id, name="c1", input={"question": "hi"}, expected_output="echo: hi"
    )
    suite_run = await _create_suite_run(client, token, suite_id, version_id)
    resp = await client.post(_release_url(str(suite_run["id"])), headers=_auth_headers(token))
    assert resp.json()["decision"] == "pass"
    return str(suite_run["id"])


async def test_suite_run_approval_is_created_once(client: AsyncClient) -> None:
    token = await _register_and_login(client, "sra1@example.com")
    suite_run_id = await _create_passing_suite_run(client, token, "sra1")

    approvals = (await client.get("/api/v1/approvals", headers=_auth_headers(token))).json()
    matching = [a for a in approvals if a.get("suite_run_id") == suite_run_id]
    assert len(matching) == 1
    assert matching[0]["run_id"] is None
    assert matching[0]["node"] == "release_decision"
    assert matching[0]["status"] == "pending"


async def test_pending_suite_run_approval_is_listable_by_owner(client: AsyncClient) -> None:
    token = await _register_and_login(client, "sra2@example.com")
    suite_run_id = await _create_passing_suite_run(client, token, "sra2")

    resp = await client.get("/api/v1/approvals?status_filter=pending", headers=_auth_headers(token))
    assert resp.status_code == 200
    matching = [a for a in resp.json() if a.get("suite_run_id") == suite_run_id]
    assert len(matching) == 1


async def test_cross_user_suite_run_approval_access_is_rejected(client: AsyncClient) -> None:
    owner_token = await _register_and_login(client, "sra3-owner@example.com")
    suite_run_id = await _create_passing_suite_run(client, owner_token, "sra3")
    owner_approvals = (
        await client.get("/api/v1/approvals", headers=_auth_headers(owner_token))
    ).json()
    approval_id = next(a["id"] for a in owner_approvals if a.get("suite_run_id") == suite_run_id)

    other_token = await _register_and_login(client, "sra3-other@example.com")

    # Not visible in another user's list.
    other_approvals = (
        await client.get("/api/v1/approvals", headers=_auth_headers(other_token))
    ).json()
    assert all(a.get("suite_run_id") != suite_run_id for a in other_approvals)

    # Not decidable by another user.
    resp = await client.post(
        f"/api/v1/approvals/{approval_id}/decide",
        json={"approved": True},
        headers=_auth_headers(other_token),
    )
    assert resp.status_code in (403, 404)


async def test_suite_run_approval_can_be_approved(client: AsyncClient) -> None:
    token = await _register_and_login(client, "sra4@example.com")
    suite_run_id = await _create_passing_suite_run(client, token, "sra4")
    approvals = (await client.get("/api/v1/approvals", headers=_auth_headers(token))).json()
    approval_id = next(a["id"] for a in approvals if a.get("suite_run_id") == suite_run_id)

    resp = await client.post(
        f"/api/v1/approvals/{approval_id}/decide",
        json={"approved": True, "reason": "looks good"},
        headers=_auth_headers(token),
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "approved"
    assert body["suite_run_id"] == suite_run_id
    assert body["run_id"] is None


async def test_suite_run_approval_can_be_rejected(client: AsyncClient) -> None:
    token = await _register_and_login(client, "sra5@example.com")
    suite_run_id = await _create_passing_suite_run(client, token, "sra5")
    approvals = (await client.get("/api/v1/approvals", headers=_auth_headers(token))).json()
    approval_id = next(a["id"] for a in approvals if a.get("suite_run_id") == suite_run_id)

    resp = await client.post(
        f"/api/v1/approvals/{approval_id}/decide",
        json={"approved": False, "reason": "not ready"},
        headers=_auth_headers(token),
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "rejected"


async def test_repeated_release_evaluation_does_not_duplicate_pending_approval_via_api(
    client: AsyncClient,
) -> None:
    token = await _register_and_login(client, "sra6@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    version_id = await _create_version(client, token, agent_id, callable_name="invoke")
    suite_id = await _create_suite(client, token, agent_id)
    await _create_case(
        client, token, suite_id, name="c1", input={"question": "hi"}, expected_output="echo: hi"
    )
    suite_run = await _create_suite_run(client, token, suite_id, version_id)

    for _ in range(3):
        resp = await client.post(_release_url(str(suite_run["id"])), headers=_auth_headers(token))
        assert resp.json()["decision"] == "pass"

    approvals = (await client.get("/api/v1/approvals", headers=_auth_headers(token))).json()
    matching = [a for a in approvals if a.get("suite_run_id") == str(suite_run["id"])]
    assert len(matching) == 1


async def test_deciding_a_suite_run_approval_never_dereferences_a_null_run(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _fail_if_called(*args: object, **kwargs: object) -> object:
        raise AssertionError("RunRepository.get_by_id must not be called for a suite_run approval")

    monkeypatch.setattr(RunRepository, "get_by_id", _fail_if_called)

    token = await _register_and_login(client, "sra7@example.com")
    suite_run_id = await _create_passing_suite_run(client, token, "sra7")
    approvals = (await client.get("/api/v1/approvals", headers=_auth_headers(token))).json()
    approval_id = next(a["id"] for a in approvals if a.get("suite_run_id") == suite_run_id)

    resp = await client.post(
        f"/api/v1/approvals/{approval_id}/decide",
        json={"approved": True},
        headers=_auth_headers(token),
    )

    assert resp.status_code == 200


async def test_deciding_a_suite_run_approval_never_triggers_legacy_run_continuation(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _fail_if_called(*args: object, **kwargs: object) -> object:
        raise AssertionError(
            "legacy approvals_service.decide() must not be called for a suite_run approval"
        )

    monkeypatch.setattr(approvals_service, "decide", _fail_if_called)

    token = await _register_and_login(client, "sra8@example.com")
    suite_run_id = await _create_passing_suite_run(client, token, "sra8")
    approvals = (await client.get("/api/v1/approvals", headers=_auth_headers(token))).json()
    approval_id = next(a["id"] for a in approvals if a.get("suite_run_id") == suite_run_id)

    resp = await client.post(
        f"/api/v1/approvals/{approval_id}/decide",
        json={"approved": True},
        headers=_auth_headers(token),
    )

    assert resp.status_code == 200
    assert resp.json()["status"] == "approved"


# =========================================================================
# Security / persistence static checks
# =========================================================================

_SOURCE_FILES = [
    Path(__file__).resolve().parent.parent / "app" / "release_gate" / "gate.py",
    Path(__file__).resolve().parent.parent / "app" / "services" / "release_gate_service.py",
    Path(__file__).resolve().parent.parent / "app" / "api" / "v1" / "release.py",
]


def test_no_eval_exec_or_subprocess_in_release_gate_source() -> None:
    forbidden = re.compile(r"\beval\(|\bexec\(|subprocess\.|os\.system\(")
    for path in _SOURCE_FILES:
        assert not forbidden.search(path.read_text(encoding="utf-8")), path


def test_release_gate_never_reruns_agent_safety_grounding_or_llm() -> None:
    forbidden_symbols = (
        "build_adapter",
        "adapter.invoke",
        "evaluate_tool_call_safety",
        "evaluate_output_safety",
        "evaluate_grounding(",
        "call_model",
        "litellm",
        "execute_suite_run",
    )
    for path in [
        Path(__file__).resolve().parent.parent / "app" / "release_gate" / "gate.py",
        Path(__file__).resolve().parent.parent / "app" / "services" / "release_gate_service.py",
    ]:
        source = path.read_text(encoding="utf-8")
        for symbol in forbidden_symbols:
            assert symbol not in source, f"found forbidden symbol {symbol!r} in {path}"


def test_no_credentials_exposed_in_release_response_schema() -> None:
    schema_source = (
        Path(__file__).resolve().parent.parent / "app" / "schemas" / "release.py"
    ).read_text(encoding="utf-8")
    lowered = schema_source.lower()
    for forbidden in ("adapter_config", "authorization", "api_key", "credential", "secret"):
        assert forbidden not in lowered


def test_no_release_decision_or_gate_result_persistence_model_exists() -> None:
    models_dir = Path(__file__).resolve().parent.parent / "app" / "models"
    names = [p.name.lower() for p in models_dir.glob("*.py")]
    for forbidden in ("release_decision", "releasedecision", "gate_result", "rca_result"):
        assert not any(forbidden in name for name in names)


def test_no_paid_service_reference_in_release_gate_source() -> None:
    forbidden = ("openai", "anthropic", "genai", "gemini")
    for path in _SOURCE_FILES:
        lowered = path.read_text(encoding="utf-8").lower()
        for symbol in forbidden:
            assert symbol not in lowered, f"found {symbol!r} in {path}"
