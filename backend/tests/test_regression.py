"""Phase 17 — Regression Comparison tests.

Three layers:
  - Pure unit tests against app.regression.diff's functions directly —
    exhaustive coverage of the locked verdict-transition/output/tool
    -trajectory/latency/safety/grounding rules, no DB/HTTP needed.
  - Service-level unit tests against RegressionService's own join/summary
    methods, using real (unpersisted) SQLAlchemy ORM objects built
    in-memory — covers new/missing-case handling and suite-level
    aggregation deterministically, without needing a live suite
    execution for every scenario.
  - Integration tests through the full HTTP + Suite Runner stack (real
    LocalAdapter, real background execution, real Phase 13/15/16
    evaluation) — ownership, same-suite/baseline validation, status
    gating, and end-to-end classification/safety visibility.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.services.suite_runner as suite_runner_mod
from app.models.suite_run import SuiteRun
from app.models.test_case_result import TestCaseResult
from app.regression.diff import (
    classify_verdict_change,
    diff_grounding,
    diff_latency,
    diff_output,
    diff_safety,
    diff_tool_trajectory,
)
from app.repositories.suite_run_repository import SuiteRunRepository
from app.services.regression_service import RegressionService
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
    # Same lesson as tests/test_trials.py and tests/test_safety_grounding.py:
    # pytest fixtures don't propagate across modules just because this
    # file imports helper *functions* from tests/test_suite_runs.py.
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


async def _insert_raw_suite_run(
    db_session: AsyncSession,
    *,
    suite_id: str,
    agent_version_id: str,
    status: str,
    max_concurrency: int = 1,
) -> str:
    """Creates a SuiteRun row directly through the repository, bypassing
    the create_suite_run API entirely — so no background task is ever
    scheduled for it, letting it be pinned at any status (e.g. "pending"
    or "running") deterministically for testing Phase 17's status-gating
    rule, without racing a real execution to completion."""
    repo = SuiteRunRepository(db_session)
    suite_run = await repo.create(
        suite_id=uuid.UUID(suite_id),
        agent_version_id=uuid.UUID(agent_version_id),
        max_concurrency=max_concurrency,
    )
    if status != "pending":
        suite_run = await repo.update(suite_run, status=status)
    await db_session.commit()
    return str(suite_run.id)


def _regression_url(suite_id: str, candidate_run_id: str) -> str:
    return f"/api/v1/test-suites/{suite_id}/regression?candidate_run_id={candidate_run_id}"


# =========================================================================
# Unit tests — app.regression.diff (pure functions)
# =========================================================================

# ---- classify_verdict_change -------------------------------------------


def test_pass_pass_is_unchanged() -> None:
    assert classify_verdict_change("PASS", "PASS") == "unchanged"


def test_fail_fail_is_unchanged() -> None:
    assert classify_verdict_change("FAIL", "FAIL") == "unchanged"


def test_inconclusive_inconclusive_is_unchanged() -> None:
    assert classify_verdict_change("INCONCLUSIVE", "INCONCLUSIVE") == "unchanged"


def test_pass_to_fail_is_regression() -> None:
    assert classify_verdict_change("PASS", "FAIL") == "regression"


def test_pass_to_inconclusive_is_regression() -> None:
    assert classify_verdict_change("PASS", "INCONCLUSIVE") == "regression"


def test_fail_to_pass_is_improvement() -> None:
    assert classify_verdict_change("FAIL", "PASS") == "improvement"


def test_inconclusive_to_pass_is_improvement() -> None:
    assert classify_verdict_change("INCONCLUSIVE", "PASS") == "improvement"


def test_fail_to_inconclusive_is_not_regression_or_improvement() -> None:
    result = classify_verdict_change("FAIL", "INCONCLUSIVE")
    assert result not in ("regression", "improvement")


def test_inconclusive_to_fail_is_not_regression_or_improvement() -> None:
    result = classify_verdict_change("INCONCLUSIVE", "FAIL")
    assert result not in ("regression", "improvement")


# ---- diff_output ---------------------------------------------------------


def test_identical_json_outputs_are_unchanged() -> None:
    diff = diff_output({"a": 1, "b": [1, 2]}, {"a": 1, "b": [1, 2]})
    assert diff.output_changed is False


def test_different_json_outputs_are_changed() -> None:
    diff = diff_output({"a": 1}, {"a": 2})
    assert diff.output_changed is True


def test_object_key_ordering_does_not_create_false_difference() -> None:
    diff = diff_output({"a": 1, "b": 2}, {"b": 2, "a": 1})
    assert diff.output_changed is False


def test_nested_json_difference_is_detected() -> None:
    diff = diff_output({"a": {"nested": [1, 2, 3]}}, {"a": {"nested": [1, 2, 4]}})
    assert diff.output_changed is True


# ---- diff_tool_trajectory -------------------------------------------------


def _safety_call(index: int, tool_name: str, status: str = "pass") -> dict[str, object]:
    return {
        "check_type": f"safety:tool_call[{index}]:{tool_name}",
        "status": status,
        "determinism": "deterministic",
        "detail": "x",
        "metadata": {"tool_name": tool_name},
    }


def _expected_tool_call(index: int, tool_name: str, status: str) -> dict[str, object]:
    return {
        "check_type": f"tool_call[{index}]:{tool_name}",
        "status": status,
        "determinism": "deterministic",
        "detail": "x",
        "metadata": {"tool": tool_name},
    }


def test_same_tool_trajectory_is_unchanged() -> None:
    baseline = [_safety_call(0, "search")]
    candidate = [_safety_call(0, "search")]
    diff = diff_tool_trajectory(baseline, candidate)
    assert diff.added_tools == []
    assert diff.removed_tools == []
    assert diff.order_changed is False
    assert diff.changed is False


def test_added_tool_is_detected() -> None:
    baseline = [_safety_call(0, "search")]
    candidate = [_safety_call(0, "search"), _safety_call(1, "shell")]
    diff = diff_tool_trajectory(baseline, candidate)
    assert diff.added_tools == ["shell"]
    assert diff.removed_tools == []
    assert diff.changed is True


def test_removed_tool_is_detected() -> None:
    baseline = [_safety_call(0, "search"), _safety_call(1, "shell")]
    candidate = [_safety_call(0, "search")]
    diff = diff_tool_trajectory(baseline, candidate)
    assert diff.removed_tools == ["shell"]
    assert diff.added_tools == []
    assert diff.changed is True


def test_changed_tool_order_is_detected() -> None:
    baseline = [_safety_call(0, "search"), _safety_call(1, "shell")]
    candidate = [_safety_call(0, "shell"), _safety_call(1, "search")]
    diff = diff_tool_trajectory(baseline, candidate)
    assert diff.order_changed is True
    assert diff.added_tools == []
    assert diff.removed_tools == []
    assert diff.changed is True


def test_changed_tool_arguments_is_detected() -> None:
    baseline = [_expected_tool_call(0, "search", "pass")]
    candidate = [_expected_tool_call(0, "search", "fail")]
    diff = diff_tool_trajectory(baseline, candidate)
    assert "tool_call[0]:search" in diff.argument_changes
    assert diff.changed is True


def test_no_tool_calls_either_side_is_unchanged() -> None:
    diff = diff_tool_trajectory([], [])
    assert diff.changed is False
    assert diff.baseline_tools == []
    assert diff.candidate_tools == []


# ---- diff_latency ----------------------------------------------------------


def test_latency_delta_is_calculated_correctly() -> None:
    diff = diff_latency(100, 150)
    assert diff.delta_ms == 50
    assert diff.available is True
    assert diff.changed is True


def test_latency_zero_delta_is_not_changed() -> None:
    diff = diff_latency(100, 100)
    assert diff.delta_ms == 0
    assert diff.changed is False


def test_missing_baseline_latency_is_handled_safely() -> None:
    diff = diff_latency(None, 100)
    assert diff.available is False
    assert diff.delta_ms is None
    assert diff.changed is False


def test_missing_candidate_latency_is_handled_safely() -> None:
    diff = diff_latency(100, None)
    assert diff.available is False
    assert diff.delta_ms is None


def test_both_latencies_missing_is_handled_safely() -> None:
    diff = diff_latency(None, None)
    assert diff.available is False
    assert diff.delta_ms is None


# ---- diff_safety -------------------------------------------------------


def _safety_output(status: str) -> dict[str, object]:
    return {
        "check_type": "safety:output",
        "status": status,
        "determinism": "deterministic",
        "detail": "x",
        "metadata": {},
    }


def test_newly_unsafe_candidate_is_detected() -> None:
    diff = diff_safety([_safety_output("pass")], [_safety_output("fail")])
    assert "safety:output" in diff.newly_unsafe
    assert diff.resolved == []
    assert diff.changed is True


def test_safety_issue_resolved_is_detected() -> None:
    diff = diff_safety([_safety_output("fail")], [_safety_output("pass")])
    assert "safety:output" in diff.resolved
    assert diff.newly_unsafe == []
    assert diff.changed is True


def test_safety_unchanged_when_both_pass() -> None:
    diff = diff_safety([_safety_output("pass")], [_safety_output("pass")])
    assert diff.changed is False


# ---- diff_grounding ------------------------------------------------------


def _grounding(status: str) -> dict[str, object]:
    return {
        "check_type": "grounding",
        "status": status,
        "determinism": "deterministic",
        "detail": "x",
        "metadata": {},
    }


def test_grounding_pass_to_fail_is_detected() -> None:
    diff = diff_grounding([_grounding("pass")], [_grounding("fail")])
    assert diff.baseline_status == "pass"
    assert diff.candidate_status == "fail"
    assert diff.changed is True


def test_grounding_fail_to_pass_is_detected() -> None:
    diff = diff_grounding([_grounding("fail")], [_grounding("pass")])
    assert diff.changed is True


def test_grounding_skipped_remains_skipped() -> None:
    diff = diff_grounding([_grounding("skipped")], [_grounding("skipped")])
    assert diff.baseline_status == "skipped"
    assert diff.candidate_status == "skipped"
    assert diff.changed is False


def test_no_reference_context_does_not_become_pass() -> None:
    diff = diff_grounding([_grounding("skipped")], [_grounding("skipped")])
    assert diff.baseline_status != "pass"
    assert diff.candidate_status != "pass"


# =========================================================================
# Service-level unit tests — RegressionService's join/summary logic,
# using real (unpersisted) ORM objects, no DB/HTTP required.
# =========================================================================


def _result(
    test_case_id: uuid.UUID, verdict: str, *, trials: list[dict[str, object]] | None = None
) -> TestCaseResult:
    return TestCaseResult(
        id=uuid.uuid4(),
        suite_run_id=uuid.uuid4(),
        test_case_id=test_case_id,
        verdict=verdict,
        verdict_method="majority",
        checks=[],
        trials=trials or [],
        actual_output=None,
        latency_ms=10,
        error=None,
        suggested_fix=None,
    )


def _suite_run(agent_version_id: uuid.UUID) -> SuiteRun:
    return SuiteRun(
        id=uuid.uuid4(),
        suite_id=uuid.uuid4(),
        agent_version_id=agent_version_id,
        status="completed",
        max_concurrency=1,
    )


def test_new_test_case_is_reported_when_only_in_candidate() -> None:
    shared_id = uuid.uuid4()
    new_id = uuid.uuid4()
    service = RegressionService(None)  # type: ignore[arg-type]
    response = service._build_response(
        suite_id=uuid.uuid4(),
        baseline_run=_suite_run(uuid.uuid4()),
        candidate_run=_suite_run(uuid.uuid4()),
        baseline_results=[_result(shared_id, "PASS")],
        candidate_results=[_result(shared_id, "PASS"), _result(new_id, "PASS")],
    )
    assert response.new_test_case_ids == [new_id]
    assert response.missing_test_case_ids == []
    assert response.summary.new_cases == 1
    assert response.summary.missing_cases == 0


def test_missing_test_case_is_reported_when_only_in_baseline() -> None:
    shared_id = uuid.uuid4()
    missing_id = uuid.uuid4()
    service = RegressionService(None)  # type: ignore[arg-type]
    response = service._build_response(
        suite_id=uuid.uuid4(),
        baseline_run=_suite_run(uuid.uuid4()),
        candidate_run=_suite_run(uuid.uuid4()),
        baseline_results=[_result(shared_id, "PASS"), _result(missing_id, "FAIL")],
        candidate_results=[_result(shared_id, "PASS")],
    )
    assert response.missing_test_case_ids == [missing_id]
    assert response.new_test_case_ids == []
    assert response.summary.missing_cases == 1


def test_pass_rate_calculated_from_test_case_results() -> None:
    ids = [uuid.uuid4() for _ in range(4)]
    service = RegressionService(None)  # type: ignore[arg-type]
    baseline_results = [
        _result(ids[0], "PASS"),
        _result(ids[1], "PASS"),
        _result(ids[2], "FAIL"),
        _result(ids[3], "INCONCLUSIVE"),
    ]
    candidate_results = [
        _result(ids[0], "PASS"),
        _result(ids[1], "FAIL"),
        _result(ids[2], "FAIL"),
        _result(ids[3], "PASS"),
    ]
    response = service._build_response(
        suite_id=uuid.uuid4(),
        baseline_run=_suite_run(uuid.uuid4()),
        candidate_run=_suite_run(uuid.uuid4()),
        baseline_results=baseline_results,
        candidate_results=candidate_results,
    )
    summary = response.summary
    assert summary.baseline_pass_count == 2
    assert summary.baseline_pass_rate == 0.5
    assert summary.candidate_pass_count == 2
    assert summary.candidate_pass_rate == 0.5
    assert summary.pass_rate_delta == 0.0
    assert summary.regressions == 1  # ids[1]: PASS -> FAIL
    assert summary.improvements == 1  # ids[3]: INCONCLUSIVE -> PASS
    assert summary.unchanged == 2  # ids[0], ids[2]


def test_trials_do_not_inflate_pass_rate() -> None:
    """A case whose *trials* contain PASS entries but whose final,
    majority-aggregated verdict is INCONCLUSIVE (Phase 16's own 2/2
    example) must count toward inconclusive, never pass — proving the
    suite-level pass rate is computed from TestCaseResult.verdict only,
    never by scanning `trials[]` for PASS occurrences."""
    case_id = uuid.uuid4()
    result = _result(
        case_id,
        "INCONCLUSIVE",
        trials=[
            {"trial_index": 0, "verdict": "PASS"},
            {"trial_index": 1, "verdict": "PASS"},
            {"trial_index": 2, "verdict": "FAIL"},
            {"trial_index": 3, "verdict": "FAIL"},
        ],
    )
    service = RegressionService(None)  # type: ignore[arg-type]
    response = service._build_response(
        suite_id=uuid.uuid4(),
        baseline_run=_suite_run(uuid.uuid4()),
        candidate_run=_suite_run(uuid.uuid4()),
        baseline_results=[result],
        candidate_results=[result],
    )
    summary = response.summary
    assert summary.baseline_pass_count == 0
    assert summary.baseline_inconclusive_count == 1
    assert summary.baseline_pass_rate == 0.0
    assert summary.baseline_inconclusive_rate == 1.0
    case = response.cases[0]
    assert case.baseline_verdict == "INCONCLUSIVE"
    assert case.trial_summary.baseline_trial_verdicts == ["PASS", "PASS", "FAIL", "FAIL"]


def test_zero_evaluated_cases_does_not_divide_by_zero() -> None:
    service = RegressionService(None)  # type: ignore[arg-type]
    response = service._build_response(
        suite_id=uuid.uuid4(),
        baseline_run=_suite_run(uuid.uuid4()),
        candidate_run=_suite_run(uuid.uuid4()),
        baseline_results=[],
        candidate_results=[],
    )
    assert response.summary.baseline_pass_rate is None
    assert response.summary.candidate_pass_rate is None
    assert response.summary.pass_rate_delta is None
    assert response.summary.baseline_inconclusive_rate is None


def test_regression_and_improvement_counts_are_correct() -> None:
    ids = [uuid.uuid4() for _ in range(4)]
    service = RegressionService(None)  # type: ignore[arg-type]
    response = service._build_response(
        suite_id=uuid.uuid4(),
        baseline_run=_suite_run(uuid.uuid4()),
        candidate_run=_suite_run(uuid.uuid4()),
        baseline_results=[
            _result(ids[0], "PASS"),
            _result(ids[1], "PASS"),
            _result(ids[2], "FAIL"),
            _result(ids[3], "FAIL"),
        ],
        candidate_results=[
            _result(ids[0], "FAIL"),  # regression
            _result(ids[1], "INCONCLUSIVE"),  # regression
            _result(ids[2], "PASS"),  # improvement
            _result(ids[3], "INCONCLUSIVE"),  # neither
        ],
    )
    assert response.summary.regressions == 2
    assert response.summary.improvements == 1
    assert response.summary.changed == 1
    assert response.summary.unchanged == 0


# =========================================================================
# Integration tests — real HTTP + Suite Runner stack
# =========================================================================


async def test_valid_same_suite_comparison_returns_200(client: AsyncClient) -> None:
    token = await _register_and_login(client, "reg1@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    baseline_version_id = await _create_version(
        client, token, agent_id, label="v1", callable_name="invoke"
    )
    candidate_version_id = await _create_version(
        client, token, agent_id, label="v2", callable_name="invoke"
    )
    await _promote_baseline(client, token, agent_id, baseline_version_id)
    suite_id = await _create_suite(client, token, agent_id)
    await _create_case(
        client, token, suite_id, name="c1", input={"question": "hi"}, expected_output="echo: hi"
    )

    await _create_suite_run(client, token, suite_id, baseline_version_id)
    candidate_run = await _create_suite_run(client, token, suite_id, candidate_version_id)

    resp = await client.get(
        _regression_url(suite_id, str(candidate_run["id"])), headers=_auth_headers(token)
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["suite_id"] == suite_id
    assert body["baseline_agent_version_id"] == baseline_version_id
    assert body["candidate_agent_version_id"] == candidate_version_id
    assert body["summary"]["total_matched_cases"] == 1
    assert body["summary"]["unchanged"] == 1
    assert body["summary"]["regressions"] == 0


async def test_cross_suite_comparison_is_rejected(client: AsyncClient) -> None:
    token = await _register_and_login(client, "reg2@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    version_id = await _create_version(client, token, agent_id)
    await _promote_baseline(client, token, agent_id, version_id)

    suite_a = await _create_suite(client, token, agent_id, name="Suite A")
    suite_b = await _create_suite(client, token, agent_id, name="Suite B")
    await _create_case(client, token, suite_a, name="a1", input={}, expected_output="echo: ")
    await _create_case(client, token, suite_b, name="b1", input={}, expected_output="echo: ")

    await _create_suite_run(client, token, suite_a, version_id)
    run_b = await _create_suite_run(client, token, suite_b, version_id)

    resp = await client.get(
        _regression_url(suite_a, str(run_b["id"])), headers=_auth_headers(token)
    )

    assert resp.status_code == 404


async def test_cross_user_access_is_rejected(client: AsyncClient) -> None:
    owner_token = await _register_and_login(client, "reg3-owner@example.com")
    project_id = await _create_project(client, owner_token)
    agent_id = await _create_agent(client, owner_token, project_id)
    version_id = await _create_version(client, owner_token, agent_id)
    await _promote_baseline(client, owner_token, agent_id, version_id)
    suite_id = await _create_suite(client, owner_token, agent_id)
    await _create_case(client, owner_token, suite_id, name="c1", input={}, expected_output="echo: ")
    await _create_suite_run(client, owner_token, suite_id, version_id)
    candidate_run = await _create_suite_run(client, owner_token, suite_id, version_id)

    other_token = await _register_and_login(client, "reg3-other@example.com")
    resp = await client.get(
        _regression_url(suite_id, str(candidate_run["id"])), headers=_auth_headers(other_token)
    )

    assert resp.status_code in (403, 404)


async def test_missing_baseline_is_rejected(client: AsyncClient) -> None:
    token = await _register_and_login(client, "reg4@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    version_id = await _create_version(client, token, agent_id)
    # Deliberately never promoted to baseline.
    suite_id = await _create_suite(client, token, agent_id)
    await _create_case(client, token, suite_id, name="c1", input={}, expected_output="echo: ")
    candidate_run = await _create_suite_run(client, token, suite_id, version_id)

    resp = await client.get(
        _regression_url(suite_id, str(candidate_run["id"])), headers=_auth_headers(token)
    )

    assert resp.status_code == 404


async def test_candidate_pending_is_rejected(client: AsyncClient, db_session: AsyncSession) -> None:
    token = await _register_and_login(client, "reg5@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    version_id = await _create_version(client, token, agent_id)
    await _promote_baseline(client, token, agent_id, version_id)
    suite_id = await _create_suite(client, token, agent_id)
    await _create_case(client, token, suite_id, name="c1", input={}, expected_output="echo: ")

    await _create_suite_run(client, token, suite_id, version_id)
    pending_run_id = await _insert_raw_suite_run(
        db_session, suite_id=suite_id, agent_version_id=version_id, status="pending"
    )

    resp = await client.get(_regression_url(suite_id, pending_run_id), headers=_auth_headers(token))

    assert resp.status_code == 409


async def test_candidate_running_is_rejected(client: AsyncClient, db_session: AsyncSession) -> None:
    token = await _register_and_login(client, "reg6@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    version_id = await _create_version(client, token, agent_id)
    await _promote_baseline(client, token, agent_id, version_id)
    suite_id = await _create_suite(client, token, agent_id)
    await _create_case(client, token, suite_id, name="c1", input={}, expected_output="echo: ")

    await _create_suite_run(client, token, suite_id, version_id)
    running_run_id = await _insert_raw_suite_run(
        db_session, suite_id=suite_id, agent_version_id=version_id, status="running"
    )

    resp = await client.get(_regression_url(suite_id, running_run_id), headers=_auth_headers(token))

    assert resp.status_code == 409


async def test_baseline_pending_is_rejected(client: AsyncClient, db_session: AsyncSession) -> None:
    token = await _register_and_login(client, "reg7@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    baseline_version_id = await _create_version(client, token, agent_id, label="v1")
    candidate_version_id = await _create_version(client, token, agent_id, label="v2")
    await _promote_baseline(client, token, agent_id, baseline_version_id)
    suite_id = await _create_suite(client, token, agent_id)
    await _create_case(client, token, suite_id, name="c1", input={}, expected_output="echo: ")

    # The baseline SuiteRun itself is left pending — never a real,
    # completed execution.
    await _insert_raw_suite_run(
        db_session, suite_id=suite_id, agent_version_id=baseline_version_id, status="pending"
    )
    candidate_run = await _create_suite_run(client, token, suite_id, candidate_version_id)

    resp = await client.get(
        _regression_url(suite_id, str(candidate_run["id"])), headers=_auth_headers(token)
    )

    assert resp.status_code == 409


async def test_candidate_missing_suite_run_returns_404(client: AsyncClient) -> None:
    token = await _register_and_login(client, "reg8@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    version_id = await _create_version(client, token, agent_id)
    await _promote_baseline(client, token, agent_id, version_id)
    suite_id = await _create_suite(client, token, agent_id)

    resp = await client.get(
        _regression_url(suite_id, str(uuid.uuid4())), headers=_auth_headers(token)
    )

    assert resp.status_code == 404


async def test_candidate_equal_to_baseline_version_is_a_valid_comparison(
    client: AsyncClient,
) -> None:
    """§24: baseline version == candidate version is not rejected — it
    is a valid comparison that simply shows no differences."""
    token = await _register_and_login(client, "reg9@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    version_id = await _create_version(client, token, agent_id)
    await _promote_baseline(client, token, agent_id, version_id)
    suite_id = await _create_suite(client, token, agent_id)
    await _create_case(client, token, suite_id, name="c1", input={}, expected_output="echo: ")

    await _create_suite_run(client, token, suite_id, version_id)
    candidate_run = await _create_suite_run(client, token, suite_id, version_id)

    resp = await client.get(
        _regression_url(suite_id, str(candidate_run["id"])), headers=_auth_headers(token)
    )

    assert resp.status_code == 200
    assert resp.json()["summary"]["regressions"] == 0
    assert resp.json()["summary"]["unchanged"] == 1


async def test_verdict_transition_end_to_end_through_different_agent_versions(
    client: AsyncClient,
) -> None:
    """Baseline PASSes (echoes correctly); candidate is swapped to a
    callable that never matches expected_output — a real, observed
    PASS -> FAIL regression through two genuinely different, real
    adapter invocations, not a synthetic verdict."""
    token = await _register_and_login(client, "reg10@example.com")
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
    await _create_case(
        client, token, suite_id, name="c1", input={"question": "hi"}, expected_output="echo: hi"
    )

    await _create_suite_run(client, token, suite_id, baseline_version_id)
    candidate_run = await _create_suite_run(client, token, suite_id, candidate_version_id)

    resp = await client.get(
        _regression_url(suite_id, str(candidate_run["id"])), headers=_auth_headers(token)
    )

    assert resp.status_code == 200
    body = resp.json()
    case = body["cases"][0]
    assert case["baseline_verdict"] == "PASS"
    assert case["candidate_verdict"] == "FAIL"
    assert case["classification"] == "regression"
    assert case["output_diff"]["output_changed"] is True
    assert body["summary"]["regressions"] == 1


async def test_safety_change_visible_independent_of_verdict(client: AsyncClient) -> None:
    """Both versions produce identical output ("done"), so the TestCase
    verdict PASSes on both sides — but the candidate's tool call is
    unsafe (blocked by policy) while the baseline's is safe. The safety
    diff must surface this even though `classification` stays
    "unchanged"."""
    token = await _register_and_login(client, "reg11@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    baseline_version_id = await _create_version(
        client, token, agent_id, label="v1", callable_name="invoke_with_safe_tool_call"
    )
    candidate_version_id = await _create_version(
        client, token, agent_id, label="v2", callable_name="invoke_with_unsafe_tool_call"
    )
    await _promote_baseline(client, token, agent_id, baseline_version_id)
    suite_id = await _create_suite(client, token, agent_id)
    await _create_case(client, token, suite_id, name="c1", input={}, expected_output="done")

    await _create_suite_run(client, token, suite_id, baseline_version_id)
    candidate_run = await _create_suite_run(client, token, suite_id, candidate_version_id)

    resp = await client.get(
        _regression_url(suite_id, str(candidate_run["id"])), headers=_auth_headers(token)
    )

    assert resp.status_code == 200
    body = resp.json()
    case = body["cases"][0]
    assert case["baseline_verdict"] == "PASS"
    assert case["candidate_verdict"] == "PASS"
    assert case["classification"] == "unchanged"
    assert case["safety_diff"]["changed"] is True
    assert any("shell" in ct for ct in case["safety_diff"]["newly_unsafe"])
    assert body["summary"]["safety_changes"] == 1


async def test_multi_trial_comparison_uses_final_verdict_and_preserves_trial_evidence(
    client: AsyncClient,
) -> None:
    """Phase 16 compatibility: a 4-trial case that alternates PASS/FAIL
    on both sides aggregates (via strict majority) to INCONCLUSIVE on
    both sides — the regression must classify this as "unchanged" using
    the final verdicts only, while still exposing each side's 4
    individual trial verdicts for inspection."""
    token = await _register_and_login(client, "reg12@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    baseline_version_id = await _create_version(
        client, token, agent_id, label="v1", callable_name="invoke_alternating_output"
    )
    candidate_version_id = await _create_version(
        client, token, agent_id, label="v2", callable_name="invoke_alternating_output"
    )
    await _promote_baseline(client, token, agent_id, baseline_version_id)
    suite_id = await _create_suite(client, token, agent_id)
    await _create_case(
        client, token, suite_id, name="c1", input={}, expected_output="yes", trial_count=4
    )

    toy_agent.reset_alternating_state()
    await _create_suite_run(client, token, suite_id, baseline_version_id)
    toy_agent.reset_alternating_state()
    candidate_run = await _create_suite_run(client, token, suite_id, candidate_version_id)

    resp = await client.get(
        _regression_url(suite_id, str(candidate_run["id"])), headers=_auth_headers(token)
    )

    assert resp.status_code == 200
    body = resp.json()
    case = body["cases"][0]
    assert case["baseline_verdict"] == "INCONCLUSIVE"
    assert case["candidate_verdict"] == "INCONCLUSIVE"
    assert case["classification"] == "unchanged"
    assert case["trial_summary"]["baseline_trial_verdicts"] == ["PASS", "FAIL", "PASS", "FAIL"]
    assert case["trial_summary"]["candidate_trial_verdicts"] == ["PASS", "FAIL", "PASS", "FAIL"]
    # Trials never inflate the suite-level pass rate.
    assert body["summary"]["baseline_pass_count"] == 0
    assert body["summary"]["baseline_inconclusive_count"] == 1


async def test_new_test_case_added_after_baseline_run_is_reported(client: AsyncClient) -> None:
    token = await _register_and_login(client, "reg13@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    baseline_version_id = await _create_version(client, token, agent_id, label="v1")
    candidate_version_id = await _create_version(client, token, agent_id, label="v2")
    await _promote_baseline(client, token, agent_id, baseline_version_id)
    suite_id = await _create_suite(client, token, agent_id)
    await _create_case(client, token, suite_id, name="c1", input={}, expected_output="echo: ")

    await _create_suite_run(client, token, suite_id, baseline_version_id)

    # A second case is added only *after* the baseline run already
    # executed — the candidate run below will see it, the baseline won't.
    await _create_case(client, token, suite_id, name="c2", input={}, expected_output="echo: ")
    candidate_run = await _create_suite_run(client, token, suite_id, candidate_version_id)

    resp = await client.get(
        _regression_url(suite_id, str(candidate_run["id"])), headers=_auth_headers(token)
    )

    assert resp.status_code == 200
    body = resp.json()
    assert len(body["new_test_case_ids"]) == 1
    assert body["summary"]["new_cases"] == 1
    assert body["summary"]["total_matched_cases"] == 1


async def test_max_concurrency_respected_and_no_extra_invocations(client: AsyncClient) -> None:
    """Regression comparison must never invoke the agent again — the two
    SuiteRuns it compares were already fully executed by their own
    create_suite_run calls; the GET itself performs zero adapter calls."""
    token = await _register_and_login(client, "reg14@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    baseline_version_id = await _create_version(
        client, token, agent_id, label="v1", callable_name="invoke_incrementing"
    )
    candidate_version_id = await _create_version(
        client, token, agent_id, label="v2", callable_name="invoke_incrementing"
    )
    await _promote_baseline(client, token, agent_id, baseline_version_id)
    suite_id = await _create_suite(client, token, agent_id)
    await _create_case(client, token, suite_id, name="c1", input={}, expected_output="call-1")

    await _create_suite_run(client, token, suite_id, baseline_version_id)
    candidate_run = await _create_suite_run(client, token, suite_id, candidate_version_id)

    calls_before = toy_agent.get_call_count()
    assert calls_before == 2  # one real invocation per suite run

    resp = await client.get(
        _regression_url(suite_id, str(candidate_run["id"])), headers=_auth_headers(token)
    )
    resp2 = await client.get(
        _regression_url(suite_id, str(candidate_run["id"])), headers=_auth_headers(token)
    )

    assert resp.status_code == 200
    assert resp2.status_code == 200
    # Two more GETs against the same comparison invoke the agent zero
    # additional times — regression is computed purely from persisted evidence.
    assert toy_agent.get_call_count() == calls_before


async def test_no_credentials_exposed_in_response_schema(client: AsyncClient) -> None:
    schema_source = (
        Path(__file__).resolve().parent.parent / "app" / "schemas" / "regression.py"
    ).read_text(encoding="utf-8")
    lowered = schema_source.lower()
    for forbidden in ("adapter_config", "authorization", "api_key", "credential", "secret"):
        assert forbidden not in lowered


# =========================================================================
# Security / static-source checks
# =========================================================================

_SOURCE_FILES = [
    Path(__file__).resolve().parent.parent / "app" / "regression" / "diff.py",
    Path(__file__).resolve().parent.parent / "app" / "services" / "regression_service.py",
    Path(__file__).resolve().parent.parent / "app" / "api" / "v1" / "regression.py",
]


def test_no_eval_exec_or_subprocess_in_regression_source() -> None:
    forbidden = re.compile(r"\beval\(|\bexec\(|subprocess\.|os\.system\(")
    for path in _SOURCE_FILES:
        source = path.read_text(encoding="utf-8")
        assert not forbidden.search(source), f"forbidden pattern found in {path}"


def test_regression_module_never_reruns_agent_safety_or_llm() -> None:
    """Phase 17 must be entirely reproducible from persisted evidence —
    structurally verified by scanning the two modules that actually
    compute a comparison for any reference to the adapter layer,
    Phase 15's Safety/Grounding evaluators, or an LLM call. Only
    app/services/suite_runner.py (a completely different module,
    already executed and approved in Phase 14/16) is allowed to call any
    of these."""
    forbidden_symbols = (
        "build_adapter",
        "adapter.invoke",
        "evaluate_tool_call_safety",
        "evaluate_output_safety",
        "evaluate_grounding(",
        "call_model",
        "litellm",
        "AgentAdapter(",
    )
    for path in [
        Path(__file__).resolve().parent.parent / "app" / "regression" / "diff.py",
        Path(__file__).resolve().parent.parent / "app" / "services" / "regression_service.py",
    ]:
        source = path.read_text(encoding="utf-8")
        for symbol in forbidden_symbols:
            assert symbol not in source, f"found forbidden symbol {symbol!r} in {path}"


def test_no_regression_persistence_model_exists() -> None:
    models_dir = Path(__file__).resolve().parent.parent / "app" / "models"
    names = [p.name for p in models_dir.glob("*.py")]
    assert not any("regression" in name.lower() for name in names)


def test_no_paid_service_reference_in_regression_source() -> None:
    forbidden = ("openai", "anthropic", "genai", "gemini", "litellm")
    for path in _SOURCE_FILES:
        lowered = path.read_text(encoding="utf-8").lower()
        for symbol in forbidden:
            assert symbol not in lowered, f"found {symbol!r} in {path}"
