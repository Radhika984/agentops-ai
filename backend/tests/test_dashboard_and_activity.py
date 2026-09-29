"""Home dashboard + Recent Activity — real, owner-scoped aggregation
(app/services/dashboard_service.py) and real, persisted product events
(app/services/activity_service.py). Exercises the full authenticated HTTP
stack, with the background suite-execution task actually running (see
tests/test_suite_runs.py's own docstring for why httpx's ASGITransport
makes this synchronous from a test's point of view) — no fake success
responses, no manually-inserted rows.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.services.suite_runner as suite_runner_mod
from tests.conftest import TEST_DATABASE_URL
from tests.test_suite_runs import (
    _auth_headers,
    _create_case,
    _create_suite_run,
    _register_and_login,
    _setup_agent_and_suite,
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


# ---- Dashboard stats ----------------------------------------------------


async def test_stats_reflect_real_counts(client: AsyncClient) -> None:
    token = await _register_and_login(client, "dash1@example.com")
    agent_id, version_id, suite_id = await _setup_agent_and_suite(client, token)
    await _create_case(
        client, token, suite_id, name="c1", input={"question": "hi"}, expected_output="echo: hi"
    )
    await _create_suite_run(client, token, suite_id, version_id)

    resp = await client.get("/api/v1/dashboard/stats", headers=_auth_headers(token))

    assert resp.status_code == 200
    body = resp.json()
    assert body["total_projects"] == 1
    assert body["total_agents"] == 1
    assert body["total_suite_runs"] == 1
    assert body["release_gate_holds"] == 0


async def test_stats_are_empty_for_a_fresh_account(client: AsyncClient) -> None:
    token = await _register_and_login(client, "dash2@example.com")

    resp = await client.get("/api/v1/dashboard/stats", headers=_auth_headers(token))

    assert resp.status_code == 200
    body = resp.json()
    assert body == {
        "total_projects": 0,
        "total_agents": 0,
        "total_suite_runs": 0,
        "release_gate_holds": 0,
    }


async def test_stats_never_leak_another_users_data(client: AsyncClient) -> None:
    token_a = await _register_and_login(client, "dash3a@example.com")
    token_b = await _register_and_login(client, "dash3b@example.com")
    agent_id, version_id, suite_id = await _setup_agent_and_suite(client, token_a)
    await _create_case(
        client, token_a, suite_id, name="c1", input={"question": "hi"}, expected_output="echo: hi"
    )
    await _create_suite_run(client, token_a, suite_id, version_id)

    resp = await client.get("/api/v1/dashboard/stats", headers=_auth_headers(token_b))

    assert resp.status_code == 200
    assert resp.json()["total_suite_runs"] == 0


async def test_unauthenticated_stats_request_is_rejected(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/dashboard/stats")
    assert resp.status_code == 401


# ---- Recent Suite Runs / account-wide Runs -------------------------------


async def test_recent_suite_runs_reflects_real_run_and_verdict(client: AsyncClient) -> None:
    token = await _register_and_login(client, "dash4@example.com")
    agent_id, version_id, suite_id = await _setup_agent_and_suite(client, token)
    await _create_case(
        client, token, suite_id, name="c1", input={"question": "hi"}, expected_output="echo: hi"
    )
    run = await _create_suite_run(client, token, suite_id, version_id)

    resp = await client.get(
        "/api/v1/dashboard/recent-suite-runs", headers=_auth_headers(token)
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    row = body["items"][0]
    assert row["id"] == run["id"]
    assert row["status"] == "completed"
    assert row["verdict"] == "PASS"
    assert row["pass_count"] == 1
    assert row["fail_count"] == 0
    # Denormalized context resolved server-side — no follow-up request
    # needed to know what this row actually is.
    assert row["suite_name"]
    assert row["agent_name"]
    assert row["project_name"]
    assert row["version_label"]


async def test_account_wide_runs_page_matches_dashboard_widget(client: AsyncClient) -> None:
    """GET /suite-runs (the standalone "Runs" nav page) and
    GET /dashboard/recent-suite-runs are the same real capability — see
    app/api/v1/suite_runs.py's list_all_suite_runs()."""
    token = await _register_and_login(client, "dash5@example.com")
    agent_id, version_id, suite_id = await _setup_agent_and_suite(client, token)
    await _create_case(
        client, token, suite_id, name="c1", input={"question": "hi"}, expected_output="echo: hi"
    )
    await _create_suite_run(client, token, suite_id, version_id)

    resp = await client.get("/api/v1/suite-runs", headers=_auth_headers(token))

    assert resp.status_code == 200
    assert resp.json()["total"] == 1


# ---- Verdict Distribution / Performance Overview -------------------------


async def test_verdict_distribution_is_a_real_aggregate(client: AsyncClient) -> None:
    token = await _register_and_login(client, "dash6@example.com")
    agent_id, version_id, suite_id = await _setup_agent_and_suite(client, token)
    await _create_case(
        client, token, suite_id, name="pass1", input={"question": "hi"}, expected_output="echo: hi"
    )
    await _create_case(
        client, token, suite_id, name="fail1", input={"question": "hi"}, expected_output="nope"
    )
    await _create_suite_run(client, token, suite_id, version_id)

    resp = await client.get(
        "/api/v1/dashboard/verdict-distribution", headers=_auth_headers(token)
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["pass_count"] == 1
    assert body["fail_count"] == 1
    assert body["inconclusive_count"] == 0
    assert body["total"] == 2


async def test_performance_overview_has_no_fabricated_points_for_fresh_account(
    client: AsyncClient,
) -> None:
    token = await _register_and_login(client, "dash7@example.com")

    resp = await client.get("/api/v1/dashboard/performance", headers=_auth_headers(token))

    assert resp.status_code == 200
    body = resp.json()
    # Zero real history -> zero points. Never a padded/invented series.
    assert body["points"] == []
    assert body["range_days"] == 7


async def test_performance_overview_reflects_a_real_completed_run(client: AsyncClient) -> None:
    token = await _register_and_login(client, "dash8@example.com")
    agent_id, version_id, suite_id = await _setup_agent_and_suite(client, token)
    await _create_case(
        client, token, suite_id, name="c1", input={"question": "hi"}, expected_output="echo: hi"
    )
    await _create_suite_run(client, token, suite_id, version_id)

    resp = await client.get("/api/v1/dashboard/performance", headers=_auth_headers(token))

    assert resp.status_code == 200
    points = resp.json()["points"]
    assert len(points) == 1
    assert points[0]["pass_rate"] == 1.0
    assert points[0]["total_results"] == 1


# ---- Recent Activity ------------------------------------------------------


async def test_suite_run_completion_records_a_real_activity_event(client: AsyncClient) -> None:
    token = await _register_and_login(client, "act1@example.com")
    agent_id, version_id, suite_id = await _setup_agent_and_suite(client, token)
    await _create_case(
        client, token, suite_id, name="c1", input={"question": "hi"}, expected_output="echo: hi"
    )
    run = await _create_suite_run(client, token, suite_id, version_id)

    resp = await client.get("/api/v1/activity", headers=_auth_headers(token))

    assert resp.status_code == 200
    events = resp.json()
    # Also contains the agent_version_created event from
    # _setup_agent_and_suite() (see test_agent_version_events_are_recorded
    # below for that one specifically) — isolate the one this test is
    # actually about.
    run_events = [e for e in events if e["event_type"] == "suite_run_completed"]
    assert len(run_events) == 1
    assert run_events[0]["entity_id"] == run["id"]
    assert "1/1 passed" in run_events[0]["description"]


async def test_agent_version_events_are_recorded(client: AsyncClient) -> None:
    token = await _register_and_login(client, "act2@example.com")
    agent_id, version_id, suite_id = await _setup_agent_and_suite(client, token)
    v2_resp = await client.post(
        f"/api/v1/agents/{agent_id}/versions",
        json={
            "label": "v2",
            "adapter_type": "local",
            "adapter_config": {
                "module_path": "tests.fixtures.toy_agent",
                "callable_name": "invoke",
            },
            "observability_level": 2,
        },
        headers=_auth_headers(token),
    )
    v2_id = v2_resp.json()["id"]
    await client.post(
        f"/api/v1/agents/{agent_id}/versions/{v2_id}/baseline", headers=_auth_headers(token)
    )

    resp = await client.get("/api/v1/activity", headers=_auth_headers(token))

    event_types = [e["event_type"] for e in resp.json()]
    # v1 (via _setup_agent_and_suite) + v2, then v2 promoted — 3 events,
    # newest first.
    assert event_types.count("agent_version_created") == 2
    assert event_types.count("agent_version_promoted") == 1


async def test_release_gate_hold_records_and_dedupes_activity(client: AsyncClient) -> None:
    token = await _register_and_login(client, "act3@example.com")
    agent_id, version_id, suite_id = await _setup_agent_and_suite(
        client, token, callable_name="invoke_with_unsafe_tool_call"
    )
    await _create_case(
        client, token, suite_id, name="c1", input={"question": "hi"}, expected_output="done"
    )
    run = await _create_suite_run(client, token, suite_id, version_id)

    resp1 = await client.post(
        f"/api/v1/suite-runs/{run['id']}/release", headers=_auth_headers(token)
    )
    assert resp1.status_code == 200
    assert resp1.json()["decision"] == "hold"

    # Re-checking the identical decision must not duplicate the event.
    resp2 = await client.post(
        f"/api/v1/suite-runs/{run['id']}/release", headers=_auth_headers(token)
    )
    assert resp2.json()["decision"] == "hold"

    activity_resp = await client.get("/api/v1/activity", headers=_auth_headers(token))
    hold_events = [
        e for e in activity_resp.json() if e["event_type"] == "release_gate_evaluated"
    ]
    assert len(hold_events) == 1
    assert hold_events[0]["title"] == "Release Gate Held"

    stats_resp = await client.get("/api/v1/dashboard/stats", headers=_auth_headers(token))
    assert stats_resp.json()["release_gate_holds"] == 1

    # The "Release Gate" nav page's own filtered view of this same log.
    filtered_resp = await client.get(
        "/api/v1/activity",
        params={"event_type": "release_gate_evaluated"},
        headers=_auth_headers(token),
    )
    assert len(filtered_resp.json()) == 1
    filtered_out_resp = await client.get(
        "/api/v1/activity",
        params={"event_type": "autofix_proposed"},
        headers=_auth_headers(token),
    )
    assert filtered_out_resp.json() == []


async def test_autofix_proposal_records_activity(client: AsyncClient) -> None:
    token = await _register_and_login(client, "act4@example.com")
    agent_id, version_id, suite_id = await _setup_agent_and_suite(client, token)
    await _create_case(
        client,
        token,
        suite_id,
        name="c1",
        input={"question": "hi"},
        expected_output="echo: hi",
        expected_tool_calls=[{"tool": "search", "required": True}],
    )
    run = await _create_suite_run(client, token, suite_id, version_id)
    results = (
        await client.get(f"/api/v1/suite-runs/{run['id']}/results", headers=_auth_headers(token))
    ).json()
    result_id = results[0]["id"]

    resp = await client.post(
        f"/api/v1/suite-runs/{run['id']}/results/{result_id}/autofix",
        headers=_auth_headers(token),
    )
    assert resp.status_code == 201

    activity_resp = await client.get("/api/v1/activity", headers=_auth_headers(token))
    autofix_events = [e for e in activity_resp.json() if e["event_type"] == "autofix_proposed"]
    assert len(autofix_events) == 1


async def test_notification_preference_suppresses_that_events_activity_entry(
    client: AsyncClient,
) -> None:
    token = await _register_and_login(client, "act5@example.com")
    off = await client.patch(
        "/api/v1/auth/me/notifications",
        json={
            "notify_on_suite_run_complete": False,
            "notify_on_release_gate": True,
            "notify_on_autofix_proposed": True,
            "notify_on_approval_decided": True,
        },
        headers=_auth_headers(token),
    )
    assert off.status_code == 200
    assert off.json()["notify_on_suite_run_complete"] is False

    agent_id, version_id, suite_id = await _setup_agent_and_suite(client, token)
    await _create_case(
        client, token, suite_id, name="c1", input={"question": "hi"}, expected_output="echo: hi"
    )
    await _create_suite_run(client, token, suite_id, version_id)

    activity_resp = await client.get("/api/v1/activity", headers=_auth_headers(token))
    events = activity_resp.json()
    # agent_version_created still fires (it has no preference toggle —
    # see app/services/activity_service.py's _PREFERENCE_FIELD map); only
    # suite_run_completed is suppressed by this specific preference.
    assert all(e["event_type"] != "suite_run_completed" for e in events)
    assert any(e["event_type"] == "agent_version_created" for e in events)


async def test_activity_never_leaks_another_users_events(client: AsyncClient) -> None:
    token_a = await _register_and_login(client, "act6a@example.com")
    token_b = await _register_and_login(client, "act6b@example.com")
    agent_id, version_id, suite_id = await _setup_agent_and_suite(client, token_a)
    await _create_case(
        client, token_a, suite_id, name="c1", input={"question": "hi"}, expected_output="echo: hi"
    )
    await _create_suite_run(client, token_a, suite_id, version_id)

    resp = await client.get("/api/v1/activity", headers=_auth_headers(token_b))

    assert resp.status_code == 200
    assert resp.json() == []
