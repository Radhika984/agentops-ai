"""Account-wide "Test Suites" and "Evaluation"/"RCA" nav pages — real
listing endpoints that did not exist before this work (see
TestSuiteRepository.list_for_owner() and
SuiteRunService.list_all_results_for_owner()). GET /suite-runs (the
"Runs" nav page) is covered in tests/test_dashboard_and_activity.py
alongside the dashboard widget it shares its implementation with.
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


async def test_account_wide_test_suites_lists_every_real_suite(client: AsyncClient) -> None:
    token = await _register_and_login(client, "listing1@example.com")
    _, _, suite_id = await _setup_agent_and_suite(client, token)

    resp = await client.get("/api/v1/test-suites", headers=_auth_headers(token))

    assert resp.status_code == 200
    ids = [s["id"] for s in resp.json()]
    assert suite_id in ids


async def test_account_wide_test_suites_is_owner_scoped(client: AsyncClient) -> None:
    token_a = await _register_and_login(client, "listing2a@example.com")
    token_b = await _register_and_login(client, "listing2b@example.com")
    await _setup_agent_and_suite(client, token_a)

    resp = await client.get("/api/v1/test-suites", headers=_auth_headers(token_b))

    assert resp.json() == []


async def test_account_wide_results_lists_real_results(client: AsyncClient) -> None:
    token = await _register_and_login(client, "listing3@example.com")
    _, version_id, suite_id = await _setup_agent_and_suite(client, token)
    await _create_case(
        client, token, suite_id, name="pass1", input={"question": "hi"}, expected_output="echo: hi"
    )
    await _create_case(
        client, token, suite_id, name="fail1", input={"question": "hi"}, expected_output="nope"
    )
    await _create_suite_run(client, token, suite_id, version_id)

    resp = await client.get("/api/v1/results", headers=_auth_headers(token))

    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2
    verdicts = {item["verdict"] for item in body["items"]}
    assert verdicts == {"PASS", "FAIL"}
    # Denormalized context, resolved server-side.
    assert all(item["test_case_name"] for item in body["items"])
    assert all(item["suite_name"] for item in body["items"])
    assert all(item["agent_name"] for item in body["items"])


async def test_account_wide_results_verdict_filter_powers_the_rca_page(
    client: AsyncClient,
) -> None:
    token = await _register_and_login(client, "listing4@example.com")
    _, version_id, suite_id = await _setup_agent_and_suite(client, token)
    await _create_case(
        client, token, suite_id, name="pass1", input={"question": "hi"}, expected_output="echo: hi"
    )
    await _create_case(
        client, token, suite_id, name="fail1", input={"question": "hi"}, expected_output="nope"
    )
    await _create_suite_run(client, token, suite_id, version_id)

    resp = await client.get(
        "/api/v1/results",
        params={"verdicts": "FAIL,INCONCLUSIVE"},
        headers=_auth_headers(token),
    )

    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["verdict"] == "FAIL"


async def test_account_wide_results_is_owner_scoped(client: AsyncClient) -> None:
    token_a = await _register_and_login(client, "listing5a@example.com")
    token_b = await _register_and_login(client, "listing5b@example.com")
    _, version_id, suite_id = await _setup_agent_and_suite(client, token_a)
    await _create_case(
        client, token_a, suite_id, name="c1", input={"question": "hi"}, expected_output="echo: hi"
    )
    await _create_suite_run(client, token_a, suite_id, version_id)

    resp = await client.get("/api/v1/results", headers=_auth_headers(token_b))

    assert resp.json() == {"items": [], "total": 0}


async def test_unauthenticated_account_wide_listings_are_rejected(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/test-suites")).status_code == 401
    assert (await client.get("/api/v1/results")).status_code == 401
