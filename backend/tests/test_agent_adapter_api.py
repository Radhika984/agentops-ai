"""Phase 10 — POST /api/v1/agent-adapter/test-invoke.

Exercises the endpoint through the real authenticated HTTP stack (the
same `client`/`db_session` fixtures every other API test file uses),
using LocalAdapter against the toy fixture agent for the success path (no
network involved) and a blocked SSRF target for the HTTP-adapter error
path (also no network involved — validation rejects it before any
request would be attempted).
"""

from __future__ import annotations

from httpx import AsyncClient


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


async def test_test_invoke_requires_authentication(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/agent-adapter/test-invoke",
        json={
            "adapter_type": "local",
            "adapter_config": {"module_path": "tests.fixtures.toy_agent"},
            "input": {"question": "hello"},
        },
    )

    assert resp.status_code == 401


async def test_test_invoke_local_adapter_success(client: AsyncClient) -> None:
    token = await _register_and_login(client, "adapter1@example.com")

    resp = await client.post(
        "/api/v1/agent-adapter/test-invoke",
        json={
            "adapter_type": "local",
            "adapter_config": {
                "module_path": "tests.fixtures.toy_agent",
                "callable_name": "invoke_async",
            },
            "input": {"question": "what is 6*7"},
        },
        headers=_auth_headers(token),
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["output"] == {"answer": "42"}
    assert len(body["tool_calls"]) == 1
    assert body["tool_calls"][0]["tool_name"] == "calculator"
    assert body["trace"] is None
    assert "request_id" in body
    assert body["latency_ms"] >= 0


async def test_test_invoke_rejects_unknown_adapter_type(client: AsyncClient) -> None:
    token = await _register_and_login(client, "adapter2@example.com")

    resp = await client.post(
        "/api/v1/agent-adapter/test-invoke",
        json={"adapter_type": "webhook", "adapter_config": {}, "input": {}},
        headers=_auth_headers(token),
    )

    # Rejected by Pydantic's Literal["http","local"] before the handler
    # even runs.
    assert resp.status_code == 422


async def test_test_invoke_rejects_ssrf_blocked_url(client: AsyncClient) -> None:
    token = await _register_and_login(client, "adapter3@example.com")

    resp = await client.post(
        "/api/v1/agent-adapter/test-invoke",
        json={
            "adapter_type": "http",
            "adapter_config": {"url": "http://169.254.169.254/latest/meta-data/"},
            "input": {"question": "hello"},
        },
        headers=_auth_headers(token),
    )

    assert resp.status_code == 422
    assert "metadata" in resp.json()["detail"]


async def test_test_invoke_rejects_http_config_missing_url(client: AsyncClient) -> None:
    token = await _register_and_login(client, "adapter4@example.com")

    resp = await client.post(
        "/api/v1/agent-adapter/test-invoke",
        json={"adapter_type": "http", "adapter_config": {}, "input": {}},
        headers=_auth_headers(token),
    )

    assert resp.status_code == 422


async def test_test_invoke_local_adapter_bad_module_path_is_422(client: AsyncClient) -> None:
    token = await _register_and_login(client, "adapter5@example.com")

    resp = await client.post(
        "/api/v1/agent-adapter/test-invoke",
        json={
            "adapter_type": "local",
            "adapter_config": {"module_path": "tests.fixtures.does_not_exist"},
            "input": {},
        },
        headers=_auth_headers(token),
    )

    assert resp.status_code == 422


async def test_test_invoke_local_adapter_agent_exception_is_200_with_error_status(
    client: AsyncClient,
) -> None:
    """An agent's own runtime failure is a real, informative result
    (status="error") — not an HTTP failure of the test-invoke call
    itself, which succeeded in reaching and invoking the agent."""
    token = await _register_and_login(client, "adapter6@example.com")

    resp = await client.post(
        "/api/v1/agent-adapter/test-invoke",
        json={
            "adapter_type": "local",
            "adapter_config": {
                "module_path": "tests.fixtures.toy_agent",
                "callable_name": "invoke_raises",
            },
            "input": {},
        },
        headers=_auth_headers(token),
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "error"
    assert "the toy agent broke" in body["error"]
