"""Phase 14 — Suite Runner + persistence tests.

Exercises the full authenticated HTTP stack, with the background suite
-execution task actually running (httpx's ASGITransport awaits
BackgroundTasks before the POST response returns — same mechanism
tests/test_runs.py already relies on for the legacy Run system), against
the real Phase 10 LocalAdapter + real Phase 13 evaluate() — no fake
success responses.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.evaluation.checks.llm_judge as llm_judge_mod
import app.services.suite_runner as suite_runner_mod
from app.adapters.exceptions import AdapterConfigError
from app.ai.client import AIClientError
from app.models.test_case_result import TestCaseResult
from app.services.suite_runner import execute_suite_run
from tests.conftest import TEST_DATABASE_URL
from tests.fixtures import toy_agent


async def _judge_unavailable(*args: object, **kwargs: object) -> object:
    """Phase 19: the Suite Runner now actually invokes the LLM judge
    (app/evaluation/checks/llm_judge.py) for any rubric-declaring
    TestCase with no objective hard failure — this project's tests
    always mock a real model call rather than depend on one (see
    tests/test_safety_grounding.py's own call_model mocks for Phase 15's
    grounding), so every pre-existing Phase 14 test below that predates
    Phase 19 and uses a rubric-only case patches `call_model` at this
    exact reference (the one app/evaluation/checks/llm_judge.py itself
    imported — patching app.ai.client.call_model instead would not
    affect it) to simulate "judge unavailable," which deterministically
    reproduces the INCONCLUSIVE outcome these tests were already written
    to expect before Phase 19 existed."""
    raise AIClientError("no judge configured in this test")


@pytest_asyncio.fixture(autouse=True)
async def _background_task_uses_test_database(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncGenerator[None, None]:
    # execute_suite_run() opens its own session via
    # app.services.suite_runner.AsyncSessionLocal (see its own docstring)
    # — point it at the test database, exactly matching
    # tests/test_runs.py's equivalent fixture for the legacy Run system.
    engine = create_async_engine(TEST_DATABASE_URL)
    test_session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(suite_runner_mod, "AsyncSessionLocal", test_session_factory)

    toy_agent.reset_concurrency_state()

    yield

    await engine.dispose()


async def _register_and_login(client: AsyncClient, email: str) -> str:
    await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "correct-horse-battery"},
    )
    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": email, "password": "correct-horse-battery"},
    )
    return str(resp.json()["access_token"])


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _create_project(client: AsyncClient, token: str, name: str = "Project A") -> str:
    resp = await client.post("/api/v1/projects", json={"name": name}, headers=_auth_headers(token))
    return str(resp.json()["id"])


async def _create_agent(
    client: AsyncClient, token: str, project_id: str, name: str = "Support Agent"
) -> str:
    resp = await client.post(
        "/api/v1/agents",
        json={"project_id": project_id, "name": name},
        headers=_auth_headers(token),
    )
    return str(resp.json()["id"])


async def _create_version(
    client: AsyncClient,
    token: str,
    agent_id: str,
    *,
    label: str = "v1",
    callable_name: str = "invoke",
) -> str:
    resp = await client.post(
        f"/api/v1/agents/{agent_id}/versions",
        json={
            "label": label,
            "adapter_type": "local",
            "adapter_config": {
                "module_path": "tests.fixtures.toy_agent",
                "callable_name": callable_name,
            },
            "observability_level": 2,
        },
        headers=_auth_headers(token),
    )
    return str(resp.json()["id"])


async def _create_suite(
    client: AsyncClient, token: str, agent_id: str, name: str = "Suite A"
) -> str:
    resp = await client.post(
        f"/api/v1/agents/{agent_id}/test-suites",
        json={"name": name},
        headers=_auth_headers(token),
    )
    return str(resp.json()["id"])


async def _create_case(client: AsyncClient, token: str, suite_id: str, **fields: object) -> str:
    resp = await client.post(
        f"/api/v1/test-suites/{suite_id}/test-cases",
        json=fields,
        headers=_auth_headers(token),
    )
    return str(resp.json()["id"])


async def _setup_agent_and_suite(
    client: AsyncClient, token: str, *, callable_name: str = "invoke"
) -> tuple[str, str, str]:
    """Returns (agent_id, version_id, suite_id)."""
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    version_id = await _create_version(client, token, agent_id, callable_name=callable_name)
    suite_id = await _create_suite(client, token, agent_id)
    return agent_id, version_id, suite_id


async def _create_suite_run(
    client: AsyncClient,
    token: str,
    suite_id: str,
    agent_version_id: str,
    *,
    max_concurrency: int = 1,
) -> dict[str, object]:
    resp = await client.post(
        f"/api/v1/test-suites/{suite_id}/runs",
        json={"agent_version_id": agent_version_id, "max_concurrency": max_concurrency},
        headers=_auth_headers(token),
    )
    return dict(resp.json())


# ---- SuiteRun creation -------------------------------------------------


async def test_authenticated_suite_run_creation(client: AsyncClient) -> None:
    token = await _register_and_login(client, "run1@example.com")
    _, version_id, suite_id = await _setup_agent_and_suite(client, token)
    await _create_case(
        client, token, suite_id, name="c1", input={"question": "hi"}, expected_output="echo: hi"
    )

    resp = await client.post(
        f"/api/v1/test-suites/{suite_id}/runs",
        json={"agent_version_id": version_id, "max_concurrency": 1},
        headers=_auth_headers(token),
    )

    assert resp.status_code == 201
    body = resp.json()
    assert body["suite_id"] == suite_id
    assert body["agent_version_id"] == version_id
    assert body["max_concurrency"] == 1
    # By the time the response returns, the background task has already
    # run to completion (see this file's own docstring).
    assert body["status"] in ("pending", "running", "completed")


async def test_unauthenticated_suite_run_creation_is_rejected(client: AsyncClient) -> None:
    resp = await client.post(
        f"/api/v1/test-suites/{uuid.uuid4()}/runs",
        json={"agent_version_id": str(uuid.uuid4()), "max_concurrency": 1},
    )
    assert resp.status_code == 401


async def test_cross_user_suite_run_creation_is_403(client: AsyncClient) -> None:
    token_a = await _register_and_login(client, "run2a@example.com")
    token_b = await _register_and_login(client, "run2b@example.com")
    _, version_id, suite_id = await _setup_agent_and_suite(client, token_a)

    resp = await client.post(
        f"/api/v1/test-suites/{suite_id}/runs",
        json={"agent_version_id": version_id, "max_concurrency": 1},
        headers=_auth_headers(token_b),
    )

    assert resp.status_code == 403


async def test_suite_run_on_nonexistent_suite_is_404(client: AsyncClient) -> None:
    token = await _register_and_login(client, "run3@example.com")

    resp = await client.post(
        f"/api/v1/test-suites/{uuid.uuid4()}/runs",
        json={"agent_version_id": str(uuid.uuid4()), "max_concurrency": 1},
        headers=_auth_headers(token),
    )

    assert resp.status_code == 404


async def test_agent_version_from_same_agent_succeeds(client: AsyncClient) -> None:
    token = await _register_and_login(client, "run4@example.com")
    _, version_id, suite_id = await _setup_agent_and_suite(client, token)

    resp = await client.post(
        f"/api/v1/test-suites/{suite_id}/runs",
        json={"agent_version_id": version_id, "max_concurrency": 1},
        headers=_auth_headers(token),
    )

    assert resp.status_code == 201


async def test_agent_version_from_different_agent_is_rejected(client: AsyncClient) -> None:
    token = await _register_and_login(client, "run5@example.com")
    project_id = await _create_project(client, token)
    agent_1 = await _create_agent(client, token, project_id, name="Agent One")
    agent_2 = await _create_agent(client, token, project_id, name="Agent Two")
    version_of_agent_2 = await _create_version(client, token, agent_2)
    suite_of_agent_1 = await _create_suite(client, token, agent_1)

    resp = await client.post(
        f"/api/v1/test-suites/{suite_of_agent_1}/runs",
        json={"agent_version_id": version_of_agent_2, "max_concurrency": 1},
        headers=_auth_headers(token),
    )

    assert resp.status_code == 404


async def test_invalid_max_concurrency_is_rejected(client: AsyncClient) -> None:
    token = await _register_and_login(client, "run6@example.com")
    _, version_id, suite_id = await _setup_agent_and_suite(client, token)

    too_low = await client.post(
        f"/api/v1/test-suites/{suite_id}/runs",
        json={"agent_version_id": version_id, "max_concurrency": 0},
        headers=_auth_headers(token),
    )
    too_high = await client.post(
        f"/api/v1/test-suites/{suite_id}/runs",
        json={"agent_version_id": version_id, "max_concurrency": 999},
        headers=_auth_headers(token),
    )

    assert too_low.status_code == 422
    assert too_high.status_code == 422


# ---- Execution / persistence -------------------------------------------


async def test_suite_executes_all_test_cases_and_persists_one_result_each(
    client: AsyncClient,
) -> None:
    token = await _register_and_login(client, "exec1@example.com")
    _, version_id, suite_id = await _setup_agent_and_suite(client, token)
    await _create_case(
        client,
        token,
        suite_id,
        name="pass case",
        input={"question": "hi"},
        expected_output="echo: hi",
    )
    await _create_case(
        client,
        token,
        suite_id,
        name="fail case",
        input={"question": "hi"},
        expected_output="not what it says",
    )
    await _create_case(
        client,
        token,
        suite_id,
        name="third case",
        input={"question": "bye"},
        expected_output="echo: bye",
    )

    suite_run = await _create_suite_run(client, token, suite_id, version_id)
    suite_run_id = suite_run["id"]

    get_resp = await client.get(f"/api/v1/suite-runs/{suite_run_id}", headers=_auth_headers(token))
    assert get_resp.json()["status"] == "completed"

    results_resp = await client.get(
        f"/api/v1/suite-runs/{suite_run_id}/results", headers=_auth_headers(token)
    )
    results = results_resp.json()
    assert len(results) == 3

    verdicts = {r["verdict"] for r in results}
    assert verdicts == {"PASS", "FAIL"}


async def test_selected_agent_version_adapter_is_actually_used(client: AsyncClient) -> None:
    """Two versions of the same agent, each echoing differently
    ("invoke" vs "invoke_async") — using the wrong one would produce a
    verdict mismatch, proving the *selected* version's adapter is what
    actually ran."""
    token = await _register_and_login(client, "exec2@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    echo_version = await _create_version(
        client, token, agent_id, label="echo", callable_name="invoke"
    )
    suite_id = await _create_suite(client, token, agent_id)
    await _create_case(
        client,
        token,
        suite_id,
        name="c1",
        input={"question": "hello"},
        expected_output="echo: hello",
    )

    suite_run = await _create_suite_run(client, token, suite_id, echo_version)
    results = (
        await client.get(
            f"/api/v1/suite-runs/{suite_run['id']}/results", headers=_auth_headers(token)
        )
    ).json()

    assert results[0]["verdict"] == "PASS"
    assert results[0]["actual_output"] == "echo: hello"


async def test_test_case_input_reaches_the_adapter(client: AsyncClient) -> None:
    token = await _register_and_login(client, "exec3@example.com")
    _, version_id, suite_id = await _setup_agent_and_suite(client, token)
    await _create_case(
        client,
        token,
        suite_id,
        name="c1",
        input={"question": "a very specific question"},
        expected_output="echo: a very specific question",
    )

    suite_run = await _create_suite_run(client, token, suite_id, version_id)
    results = (
        await client.get(
            f"/api/v1/suite-runs/{suite_run['id']}/results", headers=_auth_headers(token)
        )
    ).json()

    assert results[0]["verdict"] == "PASS"


async def test_runner_delegates_to_assertion_engine_not_reimplemented(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Proves the Suite Runner calls app.evaluation.engine.evaluate()
    rather than duplicating its check logic — spies on the real
    function (still calling through to it) and asserts it was actually
    invoked once per case."""
    calls: list[object] = []
    real_evaluate = suite_runner_mod.evaluate

    def _spy_evaluate(test_case: object, execution: object) -> object:
        calls.append((test_case, execution))
        return real_evaluate(test_case, execution)  # type: ignore[arg-type]

    monkeypatch.setattr(suite_runner_mod, "evaluate", _spy_evaluate)

    token = await _register_and_login(client, "exec4@example.com")
    _, version_id, suite_id = await _setup_agent_and_suite(client, token)
    await _create_case(
        client, token, suite_id, name="c1", input={"question": "hi"}, expected_output="echo: hi"
    )
    await _create_case(
        client, token, suite_id, name="c2", input={"question": "yo"}, expected_output="echo: yo"
    )

    await _create_suite_run(client, token, suite_id, version_id)

    assert len(calls) == 2


async def test_checks_are_persisted_from_the_assertion_engine(client: AsyncClient) -> None:
    token = await _register_and_login(client, "persist1@example.com")
    _, version_id, suite_id = await _setup_agent_and_suite(client, token)
    await _create_case(
        client, token, suite_id, name="c1", input={"question": "hi"}, expected_output="echo: hi"
    )

    suite_run = await _create_suite_run(client, token, suite_id, version_id)
    results = (
        await client.get(
            f"/api/v1/suite-runs/{suite_run['id']}/results", headers=_auth_headers(token)
        )
    ).json()

    # Phase 15 note: `checks` also carries Safety/Grounding checks
    # alongside Phase 13's own now (see tests/test_safety_grounding.py) —
    # this test only asserts that the Phase 13 check specifically is
    # present and correct, not that it's the only entry in the array.
    checks = results[0]["checks"]
    expected_output_check = next(c for c in checks if c["check_type"] == "expected_output")
    assert expected_output_check["status"] == "pass"
    assert expected_output_check["determinism"] == "deterministic"
    assert "detail" in expected_output_check


async def test_latency_is_persisted(client: AsyncClient) -> None:
    token = await _register_and_login(client, "persist2@example.com")
    _, version_id, suite_id = await _setup_agent_and_suite(client, token)
    await _create_case(
        client, token, suite_id, name="c1", input={"question": "hi"}, expected_output="echo: hi"
    )

    suite_run = await _create_suite_run(client, token, suite_id, version_id)
    results = (
        await client.get(
            f"/api/v1/suite-runs/{suite_run['id']}/results", headers=_auth_headers(token)
        )
    ).json()

    assert isinstance(results[0]["latency_ms"], int)
    assert results[0]["latency_ms"] >= 0


async def test_errors_are_persisted_for_a_failing_case(client: AsyncClient) -> None:
    token = await _register_and_login(client, "persist3@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    broken_version = await _create_version(
        client, token, agent_id, label="broken", callable_name="invoke_raises"
    )
    suite_id = await _create_suite(client, token, agent_id)
    await _create_case(
        client, token, suite_id, name="c1", input={"question": "hi"}, expected_output="anything"
    )

    suite_run = await _create_suite_run(client, token, suite_id, broken_version)
    results = (
        await client.get(
            f"/api/v1/suite-runs/{suite_run['id']}/results", headers=_auth_headers(token)
        )
    ).json()

    assert results[0]["verdict"] == "FAIL"
    assert "the toy agent broke" in results[0]["error"]
    assert results[0]["actual_output"] is None


async def test_aggregate_counts_are_correct(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Phase 19: "rubric1" below is rubric-only, so the LLM judge is now
    # actually invoked to resolve it — mocked unavailable so it
    # deterministically stays INCONCLUSIVE, preserving this test's
    # original Phase 14 intent (aggregate counts over a mixed suite).
    monkeypatch.setattr(llm_judge_mod, "call_model", _judge_unavailable)

    token = await _register_and_login(client, "aggregate1@example.com")
    _, version_id, suite_id = await _setup_agent_and_suite(client, token)
    await _create_case(
        client, token, suite_id, name="pass1", input={"question": "a"}, expected_output="echo: a"
    )
    await _create_case(
        client, token, suite_id, name="pass2", input={"question": "b"}, expected_output="echo: b"
    )
    await _create_case(
        client, token, suite_id, name="fail1", input={"question": "c"}, expected_output="wrong"
    )
    await _create_case(
        client, token, suite_id, name="rubric1", input={"question": "d"}, rubric="nice?"
    )

    suite_run = await _create_suite_run(client, token, suite_id, version_id)
    final = (
        await client.get(f"/api/v1/suite-runs/{suite_run['id']}", headers=_auth_headers(token))
    ).json()

    assert final["pass_count"] == 2
    assert final["fail_count"] == 1
    assert final["inconclusive_count"] == 1
    assert final["skipped_count"] == 0
    assert final["status"] == "completed"


# ---- Rubric boundary -------------------------------------------------


async def test_rubric_only_case_becomes_inconclusive(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Phase 19: the LLM judge is now actually invoked for this rubric
    # -only case; mocked unavailable so it deterministically stays
    # INCONCLUSIVE (the pre-Phase-19 behavior this test already expects)
    # rather than depending on a real judge call's outcome.
    monkeypatch.setattr(llm_judge_mod, "call_model", _judge_unavailable)

    token = await _register_and_login(client, "rubric1@example.com")
    _, version_id, suite_id = await _setup_agent_and_suite(client, token)
    await _create_case(
        client, token, suite_id, name="c1", input={"question": "hi"}, rubric="Is it kind?"
    )

    suite_run = await _create_suite_run(client, token, suite_id, version_id)
    results = (
        await client.get(
            f"/api/v1/suite-runs/{suite_run['id']}/results", headers=_auth_headers(token)
        )
    ).json()

    assert results[0]["verdict"] == "INCONCLUSIVE"
    # Phase 13's own "rubric" placeholder check is untouched by Phase 19
    # — it remains in checks[] exactly as engine.py always produced it.
    rubric_check = next(c for c in results[0]["checks"] if c["check_type"] == "rubric")
    assert rubric_check["status"] == "pending_llm"
    assert rubric_check["determinism"] == "requires_llm"


async def test_no_llm_call_for_deterministic_only_case(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Phase 19 update: this test previously used a rubric-only case to
    assert "no LLM call occurs during suite execution" — that premise is
    no longer true by design (Phase 19 adds the actual bounded LLM-judge
    path for rubric cases; see tests/test_llm_judge.py for that
    coverage). What remains true, and is what this test now verifies, is
    the narrower, still-real invariant: a case with NO rubric declared
    never invokes the judge at all."""

    async def _fail_if_called(*args: object, **kwargs: object) -> object:
        raise AssertionError("no LLM call should occur for a case with no rubric")

    monkeypatch.setattr(llm_judge_mod, "call_model", _fail_if_called)

    token = await _register_and_login(client, "rubric2@example.com")
    _, version_id, suite_id = await _setup_agent_and_suite(client, token)
    await _create_case(
        client, token, suite_id, name="c1", input={"question": "hi"}, expected_output="echo: hi"
    )

    suite_run = await _create_suite_run(client, token, suite_id, version_id)
    # The create response is serialized from the SuiteRun's state at the
    # moment the handler returned (still "pending") — the background
    # task runs after that, so a fresh GET is needed to observe the
    # terminal state it produced.
    final = (
        await client.get(f"/api/v1/suite-runs/{suite_run['id']}", headers=_auth_headers(token))
    ).json()

    assert final["status"] == "completed"
    assert final["llm_judge_invocation_count"] == 0


async def test_llm_judge_invocation_count_increments_even_when_judge_call_fails(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Phase 19 (§G): an invocation that is attempted but fails still
    counts — "increment invocation count because an invocation actually
    occurred." Renamed/corrected from a pre-Phase-19 test that asserted
    the count stayed zero even for a rubric-only case — that was only
    ever true because Phase 14-18 never implemented the judge path at
    all; now that Phase 19 does, a rubric-only case always attempts
    exactly one invocation per trial, whether or not that attempt
    ultimately succeeds."""
    monkeypatch.setattr(llm_judge_mod, "call_model", _judge_unavailable)

    token = await _register_and_login(client, "rubric4@example.com")
    _, version_id, suite_id = await _setup_agent_and_suite(client, token)
    await _create_case(
        client, token, suite_id, name="c1", input={"question": "hi"}, rubric="Is it kind?"
    )

    suite_run = await _create_suite_run(client, token, suite_id, version_id)
    final = (
        await client.get(f"/api/v1/suite-runs/{suite_run['id']}", headers=_auth_headers(token))
    ).json()

    assert final["llm_judge_invocation_count"] == 1


# ---- Failure isolation -------------------------------------------------


async def test_one_case_failure_does_not_stop_remaining_cases(client: AsyncClient) -> None:
    token = await _register_and_login(client, "fail1@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    broken_version = await _create_version(
        client, token, agent_id, label="broken", callable_name="invoke_raises"
    )
    suite_id = await _create_suite(client, token, agent_id)
    await _create_case(client, token, suite_id, name="c1", input={}, expected_output="x")
    await _create_case(client, token, suite_id, name="c2", input={}, expected_output="y")

    suite_run = await _create_suite_run(client, token, suite_id, broken_version)
    results = (
        await client.get(
            f"/api/v1/suite-runs/{suite_run['id']}/results", headers=_auth_headers(token)
        )
    ).json()

    assert len(results) == 2
    assert all(r["verdict"] == "FAIL" for r in results)
    final = (
        await client.get(f"/api/v1/suite-runs/{suite_run['id']}", headers=_auth_headers(token))
    ).json()
    assert final["status"] == "completed"  # the *suite run* itself still completes


async def test_runner_level_infrastructure_failure_marks_suite_run_failed(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _raise(*args: object, **kwargs: object) -> object:
        raise RuntimeError("simulated infrastructure failure")

    monkeypatch.setattr(suite_runner_mod, "build_adapter", _raise)

    token = await _register_and_login(client, "fail2@example.com")
    _, version_id, suite_id = await _setup_agent_and_suite(client, token)
    await _create_case(client, token, suite_id, name="c1", input={}, expected_output="x")

    suite_run = await _create_suite_run(client, token, suite_id, version_id)
    final = (
        await client.get(f"/api/v1/suite-runs/{suite_run['id']}", headers=_auth_headers(token))
    ).json()

    assert final["status"] == "failed"
    assert final["completed_at"] is not None


# ---- Concurrency -------------------------------------------------


async def test_max_concurrency_is_enforced_and_actually_parallel(client: AsyncClient) -> None:
    token = await _register_and_login(client, "concurrency1@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    version_id = await _create_version(
        client, token, agent_id, callable_name="invoke_track_concurrency"
    )
    suite_id = await _create_suite(client, token, agent_id)
    for i in range(6):
        await _create_case(client, token, suite_id, name=f"c{i}", input={}, expected_output="x")

    await _create_suite_run(client, token, suite_id, version_id, max_concurrency=3)

    peak = toy_agent.get_peak_concurrency()
    assert peak <= 3
    assert peak > 1  # proves real overlap happened, not accidental serialization


async def test_max_concurrency_one_runs_strictly_sequentially(client: AsyncClient) -> None:
    token = await _register_and_login(client, "concurrency2@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    version_id = await _create_version(
        client, token, agent_id, callable_name="invoke_track_concurrency"
    )
    suite_id = await _create_suite(client, token, agent_id)
    for i in range(3):
        await _create_case(client, token, suite_id, name=f"c{i}", input={}, expected_output="x")

    await _create_suite_run(client, token, suite_id, version_id, max_concurrency=1)

    assert toy_agent.get_peak_concurrency() == 1


# ---- Polling / detail / ownership -------------------------------------


async def test_get_suite_run(client: AsyncClient) -> None:
    token = await _register_and_login(client, "poll1@example.com")
    _, version_id, suite_id = await _setup_agent_and_suite(client, token)
    await _create_case(client, token, suite_id, name="c1", input={}, expected_output="x")
    suite_run = await _create_suite_run(client, token, suite_id, version_id)

    resp = await client.get(f"/api/v1/suite-runs/{suite_run['id']}", headers=_auth_headers(token))

    assert resp.status_code == 200
    assert resp.json()["id"] == suite_run["id"]


async def test_get_nonexistent_suite_run_is_404(client: AsyncClient) -> None:
    token = await _register_and_login(client, "poll2@example.com")

    resp = await client.get(f"/api/v1/suite-runs/{uuid.uuid4()}", headers=_auth_headers(token))

    assert resp.status_code == 404


async def test_result_detail_endpoint(client: AsyncClient) -> None:
    token = await _register_and_login(client, "poll3@example.com")
    _, version_id, suite_id = await _setup_agent_and_suite(client, token)
    await _create_case(
        client, token, suite_id, name="c1", input={"question": "hi"}, expected_output="echo: hi"
    )
    suite_run = await _create_suite_run(client, token, suite_id, version_id)
    results = (
        await client.get(
            f"/api/v1/suite-runs/{suite_run['id']}/results", headers=_auth_headers(token)
        )
    ).json()
    result_id = results[0]["id"]

    resp = await client.get(
        f"/api/v1/suite-runs/{suite_run['id']}/results/{result_id}", headers=_auth_headers(token)
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == result_id
    assert body["verdict"] == "PASS"
    assert body["verdict_method"] == "majority"
    assert "trials" in body and len(body["trials"]) == 1
    assert "actual_output" in body
    assert "latency_ms" in body
    assert "error" in body
    assert "suggested_fix" in body
    assert "created_at" in body and "updated_at" in body


async def test_cross_user_suite_run_access_is_403(client: AsyncClient) -> None:
    token_a = await _register_and_login(client, "poll4a@example.com")
    token_b = await _register_and_login(client, "poll4b@example.com")
    _, version_id, suite_id = await _setup_agent_and_suite(client, token_a)
    await _create_case(client, token_a, suite_id, name="c1", input={}, expected_output="x")
    suite_run = await _create_suite_run(client, token_a, suite_id, version_id)

    get_resp = await client.get(
        f"/api/v1/suite-runs/{suite_run['id']}", headers=_auth_headers(token_b)
    )
    results_resp = await client.get(
        f"/api/v1/suite-runs/{suite_run['id']}/results", headers=_auth_headers(token_b)
    )

    assert get_resp.status_code == 403
    assert results_resp.status_code == 403


async def test_cross_suite_result_id_is_not_accessible(client: AsyncClient) -> None:
    token = await _register_and_login(client, "poll5@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    version_id = await _create_version(client, token, agent_id)
    suite_1 = await _create_suite(client, token, agent_id, name="Suite 1")
    suite_2 = await _create_suite(client, token, agent_id, name="Suite 2")
    await _create_case(client, token, suite_1, name="c1", input={}, expected_output="x")
    await _create_case(client, token, suite_2, name="c1", input={}, expected_output="x")

    run_1 = await _create_suite_run(client, token, suite_1, version_id)
    run_2 = await _create_suite_run(client, token, suite_2, version_id)
    result_of_run_2 = (
        await client.get(f"/api/v1/suite-runs/{run_2['id']}/results", headers=_auth_headers(token))
    ).json()[0]

    # Real result, real suite run — but the result belongs to run_2, not
    # run_1: asking for it through run_1's path must 404, not leak it.
    resp = await client.get(
        f"/api/v1/suite-runs/{run_1['id']}/results/{result_of_run_2['id']}",
        headers=_auth_headers(token),
    )

    assert resp.status_code == 404


# ---- Duplicate safety -------------------------------------------------


async def test_retrying_the_runner_does_not_create_duplicate_results(client: AsyncClient) -> None:
    token = await _register_and_login(client, "dup1@example.com")
    _, version_id, suite_id = await _setup_agent_and_suite(client, token)
    await _create_case(
        client, token, suite_id, name="c1", input={"question": "hi"}, expected_output="echo: hi"
    )

    suite_run = await _create_suite_run(client, token, suite_id, version_id)
    suite_run_id = uuid.UUID(str(suite_run["id"]))

    # The run already completed once (see this file's docstring on
    # background-task timing) — explicitly re-invoking the runner
    # simulates an infrastructure-level retry.
    await execute_suite_run(suite_run_id)
    await execute_suite_run(suite_run_id)

    results = (
        await client.get(f"/api/v1/suite-runs/{suite_run_id}/results", headers=_auth_headers(token))
    ).json()

    assert len(results) == 1


async def test_database_unique_constraint_backstops_duplicate_results(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Even bypassing the runner's own idempotency check entirely, the
    database itself refuses a second (suite_run_id, test_case_id) row."""
    token = await _register_and_login(client, "dup2@example.com")
    _, version_id, suite_id = await _setup_agent_and_suite(client, token)
    await _create_case(
        client, token, suite_id, name="c1", input={"question": "hi"}, expected_output="echo: hi"
    )
    suite_run = await _create_suite_run(client, token, suite_id, version_id)

    result = await db_session.execute(
        select(TestCaseResult).where(
            TestCaseResult.suite_run_id == uuid.UUID(str(suite_run["id"]))
        )
    )
    existing = result.scalar_one()

    duplicate = TestCaseResult(
        suite_run_id=existing.suite_run_id,
        test_case_id=existing.test_case_id,
        verdict="PASS",
        checks=[],
    )
    db_session.add(duplicate)
    with pytest.raises(Exception):  # noqa: B017 - a raw IntegrityError from asyncpg
        await db_session.flush()
    await db_session.rollback()


async def test_adapter_config_error_per_case_produces_fail_not_crash(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A per-invocation AdapterConfigError (as opposed to one raised by
    build_adapter() itself, covered by the infra-failure test above) is
    isolated to that one case's FAIL result."""

    async def _raise_config_error(self: object, input: dict[str, object]) -> object:
        raise AdapterConfigError("simulated per-call validation failure")

    from app.adapters.local_adapter import LocalAdapter

    monkeypatch.setattr(LocalAdapter, "invoke", _raise_config_error)

    token = await _register_and_login(client, "adaptererr1@example.com")
    _, version_id, suite_id = await _setup_agent_and_suite(client, token)
    await _create_case(client, token, suite_id, name="c1", input={}, expected_output="x")

    suite_run = await _create_suite_run(client, token, suite_id, version_id)
    results = (
        await client.get(
            f"/api/v1/suite-runs/{suite_run['id']}/results", headers=_auth_headers(token)
        )
    ).json()

    assert results[0]["verdict"] == "FAIL"
    assert "simulated per-call validation failure" in results[0]["error"]
    final = (
        await client.get(f"/api/v1/suite-runs/{suite_run['id']}", headers=_auth_headers(token))
    ).json()
    assert final["status"] == "completed"
