"""Settings > API Keys — real create/list/revoke, one-time raw-key
reveal, and using an issued key to authenticate a real request (see
app/services/api_key_service.py and app/api/v1/deps.py's
get_current_user_or_api_key()).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.services.suite_runner as suite_runner_mod
from tests.conftest import TEST_DATABASE_URL
from tests.test_suite_runs import (
    _auth_headers,
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


async def test_create_api_key_returns_raw_key_exactly_once(client: AsyncClient) -> None:
    token = await _register_and_login(client, "key1@example.com")

    resp = await client.post(
        "/api/v1/api-keys", json={"name": "CI key"}, headers=_auth_headers(token)
    )

    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "CI key"
    assert body["api_key"].startswith("aops_")
    assert body["key_prefix"] == body["api_key"][:12]


async def test_list_api_keys_never_includes_the_raw_key(client: AsyncClient) -> None:
    token = await _register_and_login(client, "key2@example.com")
    await client.post("/api/v1/api-keys", json={"name": "CI key"}, headers=_auth_headers(token))

    resp = await client.get("/api/v1/api-keys", headers=_auth_headers(token))

    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert "api_key" not in body[0]
    assert "hashed_key" not in body[0]
    assert body[0]["key_prefix"]


async def test_api_key_authenticates_a_real_request(client: AsyncClient) -> None:
    token = await _register_and_login(client, "key3@example.com")
    _, version_id, suite_id = await _setup_agent_and_suite(client, token)
    run = await _create_suite_run(client, token, suite_id, version_id)
    create_resp = await client.post(
        "/api/v1/api-keys", json={"name": "CI key"}, headers=_auth_headers(token)
    )
    raw_key = create_resp.json()["api_key"]

    # GET /suite-runs/{id} (get_current_user_or_api_key) accepts the raw
    # key as a bearer token, exactly like it accepts a JWT — the real
    # "poll a run from CI" use case an API key is actually for.
    resp = await client.get(
        f"/api/v1/suite-runs/{run['id']}", headers={"Authorization": f"Bearer {raw_key}"}
    )

    assert resp.status_code == 200
    assert resp.json()["id"] == run["id"]


async def test_revoked_api_key_no_longer_authenticates(client: AsyncClient) -> None:
    token = await _register_and_login(client, "key4@example.com")
    _, version_id, suite_id = await _setup_agent_and_suite(client, token)
    run = await _create_suite_run(client, token, suite_id, version_id)
    create_resp = await client.post(
        "/api/v1/api-keys", json={"name": "CI key"}, headers=_auth_headers(token)
    )
    key_id = create_resp.json()["id"]
    raw_key = create_resp.json()["api_key"]

    revoke_resp = await client.delete(
        f"/api/v1/api-keys/{key_id}", headers=_auth_headers(token)
    )
    assert revoke_resp.status_code == 204

    resp = await client.get(
        f"/api/v1/suite-runs/{run['id']}", headers={"Authorization": f"Bearer {raw_key}"}
    )
    assert resp.status_code == 401


async def test_invalid_api_key_is_rejected(client: AsyncClient) -> None:
    resp = await client.get(
        f"/api/v1/suite-runs/{uuid.uuid4()}",
        headers={"Authorization": "Bearer aops_not-a-real-key"},
    )
    assert resp.status_code == 401


async def test_cross_user_api_key_revoke_is_rejected(client: AsyncClient) -> None:
    token_a = await _register_and_login(client, "key5a@example.com")
    token_b = await _register_and_login(client, "key5b@example.com")
    create_resp = await client.post(
        "/api/v1/api-keys", json={"name": "CI key"}, headers=_auth_headers(token_a)
    )
    key_id = create_resp.json()["id"]

    resp = await client.delete(f"/api/v1/api-keys/{key_id}", headers=_auth_headers(token_b))

    assert resp.status_code == 403


async def test_revoke_nonexistent_api_key_is_404(client: AsyncClient) -> None:
    token = await _register_and_login(client, "key6@example.com")

    resp = await client.delete(
        f"/api/v1/api-keys/{uuid.uuid4()}", headers=_auth_headers(token)
    )

    assert resp.status_code == 404


async def test_unauthenticated_api_key_creation_is_rejected(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/api-keys", json={"name": "x"})
    assert resp.status_code == 401
