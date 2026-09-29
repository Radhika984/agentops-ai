"""Phase 16 — Nondeterministic Trials tests.

Two layers:
  - Pure unit tests against app.services.suite_runner.aggregate_trial_verdicts
    directly — exhaustive coverage of every example in the locked brief,
    no DB/HTTP needed.
  - Integration tests through the full Suite Runner stack (real HTTP,
    real LocalAdapter, real background execution, real Phase 13/15
    evaluation), proving trial_count actually drives repeated real
    invocations, independent per-trial evidence, and correct majority
    aggregation end to end.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.services.suite_runner as suite_runner_mod
from app.services.suite_runner import aggregate_trial_verdicts
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
    # pytest fixtures don't propagate across modules just because this
    # file imports helper *functions* from tests/test_suite_runs.py — see
    # that module's own identical fixture, and tests/test_safety_grounding.py's
    # copy of it, for the full reasoning.
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


# =====================================================================
# Unit tests — aggregate_trial_verdicts (the locked strict-majority rule)
# =====================================================================


def test_one_trial_pass() -> None:
    assert aggregate_trial_verdicts(["PASS"]) == "PASS"


def test_one_trial_fail() -> None:
    assert aggregate_trial_verdicts(["FAIL"]) == "FAIL"


def test_one_trial_inconclusive() -> None:
    assert aggregate_trial_verdicts(["INCONCLUSIVE"]) == "INCONCLUSIVE"


def test_two_trials_pass_pass() -> None:
    assert aggregate_trial_verdicts(["PASS", "PASS"]) == "PASS"


def test_two_trials_fail_fail() -> None:
    assert aggregate_trial_verdicts(["FAIL", "FAIL"]) == "FAIL"


def test_two_trials_pass_fail_is_inconclusive() -> None:
    assert aggregate_trial_verdicts(["PASS", "FAIL"]) == "INCONCLUSIVE"


def test_three_trials_pass_pass_fail() -> None:
    assert aggregate_trial_verdicts(["PASS", "PASS", "FAIL"]) == "PASS"


def test_three_trials_fail_fail_pass() -> None:
    assert aggregate_trial_verdicts(["FAIL", "FAIL", "PASS"]) == "FAIL"


def test_three_trials_pass_fail_inconclusive_is_inconclusive() -> None:
    assert aggregate_trial_verdicts(["PASS", "FAIL", "INCONCLUSIVE"]) == "INCONCLUSIVE"


def test_four_trials_pass_pass_pass_fail() -> None:
    assert aggregate_trial_verdicts(["PASS", "PASS", "PASS", "FAIL"]) == "PASS"


def test_four_trials_fail_fail_fail_pass() -> None:
    assert aggregate_trial_verdicts(["FAIL", "FAIL", "FAIL", "PASS"]) == "FAIL"


def test_four_trials_pass_pass_fail_fail_is_inconclusive() -> None:
    """The explicit locked acceptance criterion: 2/2 = INCONCLUSIVE."""
    assert aggregate_trial_verdicts(["PASS", "PASS", "FAIL", "FAIL"]) == "INCONCLUSIVE"


def test_four_trials_fail_fail_pass_pass_is_inconclusive() -> None:
    assert aggregate_trial_verdicts(["FAIL", "FAIL", "PASS", "PASS"]) == "INCONCLUSIVE"


def test_four_trials_pass_fail_inconclusive_inconclusive_is_inconclusive() -> None:
    """Even a plurality (2 of 4) is not a *strict* majority."""
    assert (
        aggregate_trial_verdicts(["PASS", "FAIL", "INCONCLUSIVE", "INCONCLUSIVE"]) == "INCONCLUSIVE"
    )


def test_aggregate_never_averages_or_scores() -> None:
    """Order must not matter — only the verdict counts."""
    assert aggregate_trial_verdicts(["FAIL", "PASS", "PASS"]) == aggregate_trial_verdicts(
        ["PASS", "FAIL", "PASS"]
    )


# =====================================================================
# Integration tests
# =====================================================================


async def test_trial_count_one_is_one_adapter_invocation(client: AsyncClient) -> None:
    token = await _register_and_login(client, "trial1@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    version_id = await _create_version(client, token, agent_id, callable_name="invoke_incrementing")
    suite_id = await _create_suite(client, token, agent_id)
    await _create_case(
        client, token, suite_id, name="c1", input={}, expected_output="call-1", trial_count=1
    )

    await _create_suite_run(client, token, suite_id, version_id)

    assert toy_agent.get_call_count() == 1


async def test_trial_count_two_is_two_independent_invocations(client: AsyncClient) -> None:
    token = await _register_and_login(client, "trial2@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    version_id = await _create_version(client, token, agent_id, callable_name="invoke_incrementing")
    suite_id = await _create_suite(client, token, agent_id)
    await _create_case(
        client, token, suite_id, name="c1", input={}, expected_output="call-1", trial_count=2
    )

    await _create_suite_run(client, token, suite_id, version_id)

    assert toy_agent.get_call_count() == 2


async def test_trial_count_four_is_four_independent_invocations(client: AsyncClient) -> None:
    token = await _register_and_login(client, "trial3@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    version_id = await _create_version(client, token, agent_id, callable_name="invoke_incrementing")
    suite_id = await _create_suite(client, token, agent_id)
    await _create_case(
        client, token, suite_id, name="c1", input={}, expected_output="call-1", trial_count=4
    )

    await _create_suite_run(client, token, suite_id, version_id)

    assert toy_agent.get_call_count() == 4


async def test_same_input_sent_to_every_trial(client: AsyncClient) -> None:
    token = await _register_and_login(client, "trial4@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    version_id = await _create_version(client, token, agent_id, callable_name="invoke")
    suite_id = await _create_suite(client, token, agent_id)
    await _create_case(
        client,
        token,
        suite_id,
        name="c1",
        input={"question": "the exact same question"},
        expected_output="echo: the exact same question",
        trial_count=3,
    )

    suite_run = await _create_suite_run(client, token, suite_id, version_id)
    results = (
        await client.get(
            f"/api/v1/suite-runs/{suite_run['id']}/results", headers=_auth_headers(token)
        )
    ).json()

    trials = results[0]["trials"]
    assert len(trials) == 3
    assert all(t["actual_output"] == "echo: the exact same question" for t in trials)
    assert all(t["verdict"] == "PASS" for t in trials)


async def test_distinct_agent_execution_produced_per_trial(client: AsyncClient) -> None:
    token = await _register_and_login(client, "trial5@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    version_id = await _create_version(client, token, agent_id, callable_name="invoke_incrementing")
    suite_id = await _create_suite(client, token, agent_id)
    await _create_case(
        client, token, suite_id, name="c1", input={}, expected_output="call-1", trial_count=4
    )

    suite_run = await _create_suite_run(client, token, suite_id, version_id)
    results = (
        await client.get(
            f"/api/v1/suite-runs/{suite_run['id']}/results", headers=_auth_headers(token)
        )
    ).json()

    outputs = [t["actual_output"] for t in results[0]["trials"]]
    assert len(set(outputs)) == 4  # no caching collapsed any two trials together
    assert set(outputs) == {"call-1", "call-2", "call-3", "call-4"}


async def test_trials_persisted_in_numeric_order(client: AsyncClient) -> None:
    token = await _register_and_login(client, "trial6@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    version_id = await _create_version(
        client, token, agent_id, callable_name="invoke_track_concurrency"
    )
    suite_id = await _create_suite(client, token, agent_id)
    await _create_case(
        client, token, suite_id, name="c1", input={}, expected_output="ok", trial_count=4
    )

    # max_concurrency > 1 so trials can genuinely complete out of order —
    # persistence must still sort them back into 0..3.
    suite_run = await _create_suite_run(client, token, suite_id, version_id, max_concurrency=3)
    results = (
        await client.get(
            f"/api/v1/suite-runs/{suite_run['id']}/results", headers=_auth_headers(token)
        )
    ).json()

    trial_indexes = [t["trial_index"] for t in results[0]["trials"]]
    assert trial_indexes == [0, 1, 2, 3]


async def test_all_trials_attempted_even_when_one_fails(client: AsyncClient) -> None:
    token = await _register_and_login(client, "trial7@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    version_id = await _create_version(
        client, token, agent_id, callable_name="invoke_fail_on_second_call"
    )
    suite_id = await _create_suite(client, token, agent_id)
    await _create_case(
        client, token, suite_id, name="c1", input={}, expected_output="ok", trial_count=4
    )

    suite_run = await _create_suite_run(client, token, suite_id, version_id, max_concurrency=1)
    results = (
        await client.get(
            f"/api/v1/suite-runs/{suite_run['id']}/results", headers=_auth_headers(token)
        )
    ).json()

    trials = results[0]["trials"]
    assert len(trials) == 4  # every trial attempted, none silently dropped
    verdicts = [t["verdict"] for t in trials]
    assert verdicts.count("FAIL") == 1  # only the 2nd call actually failed
    assert verdicts.count("PASS") == 3
    # 3 PASS out of 4 is a strict majority.
    assert results[0]["verdict"] == "PASS"


# ---- Trial evidence ----------------------------------------------------


async def test_each_trial_preserves_its_own_output_latency_error(client: AsyncClient) -> None:
    token = await _register_and_login(client, "evidence1@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    version_id = await _create_version(
        client, token, agent_id, callable_name="invoke_fail_on_second_call"
    )
    suite_id = await _create_suite(client, token, agent_id)
    await _create_case(
        client, token, suite_id, name="c1", input={}, expected_output="ok", trial_count=3
    )

    suite_run = await _create_suite_run(client, token, suite_id, version_id, max_concurrency=1)
    results = (
        await client.get(
            f"/api/v1/suite-runs/{suite_run['id']}/results", headers=_auth_headers(token)
        )
    ).json()

    trials = sorted(results[0]["trials"], key=lambda t: t["trial_index"])
    assert trials[0]["actual_output"] == "ok"
    assert trials[0]["error"] is None
    assert trials[1]["actual_output"] is None
    assert "simulated failure on the second trial only" in trials[1]["error"]
    assert trials[2]["actual_output"] == "ok"
    assert all(isinstance(t["latency_ms"], int) or t["latency_ms"] is None for t in trials)


async def test_each_trial_preserves_its_own_checks(client: AsyncClient) -> None:
    token = await _register_and_login(client, "evidence2@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    version_id = await _create_version(
        client, token, agent_id, callable_name="invoke_alternating_output"
    )
    suite_id = await _create_suite(client, token, agent_id)
    await _create_case(
        client, token, suite_id, name="c1", input={}, expected_output="yes", trial_count=4
    )

    suite_run = await _create_suite_run(client, token, suite_id, version_id, max_concurrency=1)
    results = (
        await client.get(
            f"/api/v1/suite-runs/{suite_run['id']}/results", headers=_auth_headers(token)
        )
    ).json()

    trials = sorted(results[0]["trials"], key=lambda t: t["trial_index"])
    # Each trial's own checks correctly reflect *that* trial's own output
    # — never another trial's.
    for trial in trials:
        expected_output_check = next(
            c for c in trial["checks"] if c["check_type"] == "expected_output"
        )
        if trial["actual_output"] == "yes":
            assert expected_output_check["status"] == "pass"
        else:
            assert expected_output_check["status"] == "fail"


async def test_safety_remains_trial_specific(client: AsyncClient) -> None:
    """A tool call flagged unsafe on one trial must never bleed into a
    sibling trial's own safety check."""
    token = await _register_and_login(client, "evidence3@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    # Reports the same 2 tool calls (1 safe, 1 matching a real deny
    # pattern) on every call — if a trial's safety checks were ever
    # contaminated by another trial's data (or accidentally
    # deduplicated/cached), this would show fewer/mismatched checks.
    version_id = await _create_version(
        client, token, agent_id, callable_name="invoke_with_multiple_tool_calls"
    )
    suite_id = await _create_suite(client, token, agent_id)
    await _create_case(
        client, token, suite_id, name="c1", input={}, expected_output="done", trial_count=2
    )

    suite_run = await _create_suite_run(client, token, suite_id, version_id, max_concurrency=1)
    results = (
        await client.get(
            f"/api/v1/suite-runs/{suite_run['id']}/results", headers=_auth_headers(token)
        )
    ).json()

    trials = sorted(results[0]["trials"], key=lambda t: t["trial_index"])
    for trial in trials:
        # invoke_with_multiple_tool_calls always makes the same 2 calls
        # (1 safe, 1 unsafe) — every trial must independently show both.
        tool_checks = [
            c for c in trial["checks"] if c["check_type"].startswith("safety:tool_call[")
        ]
        assert len(tool_checks) == 2
        assert {c["status"] for c in tool_checks} == {"pass", "fail"}


async def test_grounding_remains_trial_specific(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.evaluation.checks.grounding as grounding_mod
    from app.agents.schemas import HallucinationCheck

    seen_outputs: list[str] = []

    async def _fake_call_model(
        prompt: str, schema: type[HallucinationCheck], **kwargs: object
    ) -> HallucinationCheck:
        seen_outputs.append(prompt)
        return schema(unsupported_claims=[])

    monkeypatch.setattr(grounding_mod, "call_model", _fake_call_model)

    token = await _register_and_login(client, "evidence4@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    version_id = await _create_version(client, token, agent_id, callable_name="invoke_incrementing")
    suite_id = await _create_suite(client, token, agent_id)
    await _create_case(
        client,
        token,
        suite_id,
        name="c1",
        input={},
        expected_output="call-1",
        reference_context="A reference document.",
        trial_count=3,
    )

    suite_run = await _create_suite_run(client, token, suite_id, version_id, max_concurrency=1)
    results = (
        await client.get(
            f"/api/v1/suite-runs/{suite_run['id']}/results", headers=_auth_headers(token)
        )
    ).json()

    # 3 trials -> 3 separate grounding/entailment calls, each against
    # that trial's own distinct output ("call-1", "call-2", "call-3").
    assert len(seen_outputs) == 3
    assert "call-1" in seen_outputs[0]
    assert "call-2" in seen_outputs[1]
    assert "call-3" in seen_outputs[2]

    trials = sorted(results[0]["trials"], key=lambda t: t["trial_index"])
    for trial in trials:
        grounding_check = next(c for c in trial["checks"] if c["check_type"] == "grounding")
        assert grounding_check["status"] == "pass"


async def test_missing_reference_context_is_skipped_on_every_trial(client: AsyncClient) -> None:
    token = await _register_and_login(client, "evidence5@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    version_id = await _create_version(client, token, agent_id, callable_name="invoke_incrementing")
    suite_id = await _create_suite(client, token, agent_id)
    await _create_case(
        client, token, suite_id, name="c1", input={}, expected_output="call-1", trial_count=3
    )

    suite_run = await _create_suite_run(client, token, suite_id, version_id, max_concurrency=1)
    results = (
        await client.get(
            f"/api/v1/suite-runs/{suite_run['id']}/results", headers=_auth_headers(token)
        )
    ).json()

    trials = results[0]["trials"]
    assert len(trials) == 3
    for trial in trials:
        grounding_check = next(c for c in trial["checks"] if c["check_type"] == "grounding")
        assert grounding_check["status"] == "skipped"


async def test_level_1_tool_safety_skipped_on_every_trial(client: AsyncClient) -> None:
    token = await _register_and_login(client, "evidence6@example.com")
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
    await _create_case(
        client, token, suite_id, name="c1", input={}, expected_output="done", trial_count=3
    )

    suite_run = await _create_suite_run(client, token, suite_id, version_id, max_concurrency=1)
    results = (
        await client.get(
            f"/api/v1/suite-runs/{suite_run['id']}/results", headers=_auth_headers(token)
        )
    ).json()

    trials = results[0]["trials"]
    assert len(trials) == 3
    for trial in trials:
        tool_check = next(c for c in trial["checks"] if c["check_type"] == "safety:tool_calls")
        assert tool_check["status"] == "skipped"


# ---- Aggregation -------------------------------------------------------


async def test_exactly_one_test_case_result_per_test_case(client: AsyncClient) -> None:
    token = await _register_and_login(client, "aggregate1@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    version_id = await _create_version(client, token, agent_id, callable_name="invoke_incrementing")
    suite_id = await _create_suite(client, token, agent_id)
    await _create_case(
        client, token, suite_id, name="c1", input={}, expected_output="call-1", trial_count=4
    )

    suite_run = await _create_suite_run(client, token, suite_id, version_id, max_concurrency=1)
    results = (
        await client.get(
            f"/api/v1/suite-runs/{suite_run['id']}/results", headers=_auth_headers(token)
        )
    ).json()

    assert len(results) == 1


async def test_suite_counts_use_final_aggregated_verdict_not_per_trial(client: AsyncClient) -> None:
    """The locked example: 4 trials = 2 PASS + 2 FAIL -> one
    INCONCLUSIVE TestCaseResult -> inconclusive_count += 1, never
    pass_count += 2 / fail_count += 2."""
    token = await _register_and_login(client, "aggregate2@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    version_id = await _create_version(
        client, token, agent_id, callable_name="invoke_alternating_output"
    )
    suite_id = await _create_suite(client, token, agent_id)
    await _create_case(
        client, token, suite_id, name="c1", input={}, expected_output="yes", trial_count=4
    )

    suite_run = await _create_suite_run(client, token, suite_id, version_id, max_concurrency=1)
    final = (
        await client.get(f"/api/v1/suite-runs/{suite_run['id']}", headers=_auth_headers(token))
    ).json()
    results = (
        await client.get(
            f"/api/v1/suite-runs/{suite_run['id']}/results", headers=_auth_headers(token)
        )
    ).json()

    assert results[0]["verdict"] == "INCONCLUSIVE"
    assert final["pass_count"] == 0
    assert final["fail_count"] == 0
    assert final["inconclusive_count"] == 1


async def test_no_per_trial_inflation_across_multiple_cases(client: AsyncClient) -> None:
    token = await _register_and_login(client, "aggregate3@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    version_id = await _create_version(client, token, agent_id, callable_name="invoke")
    suite_id = await _create_suite(client, token, agent_id)
    await _create_case(
        client,
        token,
        suite_id,
        name="c1",
        input={"question": "a"},
        expected_output="echo: a",
        trial_count=3,
    )
    await _create_case(
        client,
        token,
        suite_id,
        name="c2",
        input={"question": "b"},
        expected_output="echo: b",
        trial_count=3,
    )

    suite_run = await _create_suite_run(client, token, suite_id, version_id, max_concurrency=1)
    final = (
        await client.get(f"/api/v1/suite-runs/{suite_run['id']}", headers=_auth_headers(token))
    ).json()

    # 2 cases x 3 trials = 6 real invocations, but only 2 TestCaseResults
    # -> pass_count must be 2, never 6.
    assert final["pass_count"] == 2
    assert final["fail_count"] == 0


async def test_verdict_method_is_majority(client: AsyncClient) -> None:
    token = await _register_and_login(client, "aggregate4@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    version_id = await _create_version(client, token, agent_id, callable_name="invoke_incrementing")
    suite_id = await _create_suite(client, token, agent_id)
    await _create_case(
        client, token, suite_id, name="c1", input={}, expected_output="call-1", trial_count=3
    )

    suite_run = await _create_suite_run(client, token, suite_id, version_id, max_concurrency=1)
    results = (
        await client.get(
            f"/api/v1/suite-runs/{suite_run['id']}/results", headers=_auth_headers(token)
        )
    ).json()

    assert results[0]["verdict_method"] == "majority"


# ---- Concurrency ---------------------------------------------------


async def test_max_concurrency_respected_across_cases_and_trials(client: AsyncClient) -> None:
    token = await _register_and_login(client, "concurrency1@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    version_id = await _create_version(
        client, token, agent_id, callable_name="invoke_track_concurrency"
    )
    suite_id = await _create_suite(client, token, agent_id)
    # 3 cases x 3 trials = 9 real invocations total, well above the
    # max_concurrency=2 bound this test verifies is actually enforced.
    for i in range(3):
        await _create_case(
            client, token, suite_id, name=f"c{i}", input={}, expected_output="ok", trial_count=3
        )

    await _create_suite_run(client, token, suite_id, version_id, max_concurrency=2)

    peak = toy_agent.get_peak_concurrency()
    assert peak <= 2
    assert peak > 1  # proves real overlap happened across cases/trials combined


# ---- Security -------------------------------------------------------


def test_no_eval_exec_or_shell_execution_in_suite_runner() -> None:
    forbidden = ["eval(", "exec(", "subprocess", "os.system", "__import__"]
    path = Path(__file__).resolve().parent.parent / "app" / "services" / "suite_runner.py"
    text = path.read_text(encoding="utf-8")
    offending = [needle for needle in forbidden if needle in text]
    assert offending == []


async def test_no_secrets_persisted_in_trial_evidence(client: AsyncClient) -> None:
    token = await _register_and_login(client, "security1@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    version_id = await _create_version(client, token, agent_id, callable_name="invoke_incrementing")
    suite_id = await _create_suite(client, token, agent_id)
    await _create_case(
        client, token, suite_id, name="c1", input={}, expected_output="call-1", trial_count=3
    )

    suite_run = await _create_suite_run(client, token, suite_id, version_id, max_concurrency=1)
    results = (
        await client.get(
            f"/api/v1/suite-runs/{suite_run['id']}/results", headers=_auth_headers(token)
        )
    ).json()

    import json as json_mod

    dumped = json_mod.dumps(results)
    assert "Authorization" not in dumped
    assert "header" not in dumped.lower()
