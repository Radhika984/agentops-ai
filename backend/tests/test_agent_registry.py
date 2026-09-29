"""Phase 11 — Agent Registry tests.

Exercises the full authenticated HTTP stack (register/login -> create
project -> create agent -> create version -> ...), using LocalAdapter
against the Phase 10 toy fixture agent (tests/fixtures/toy_agent.py) for
the real test-invoke path — no network, no fake success responses.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.run import Run
from app.services import agent_service


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


_LOCAL_CONFIG = {
    "adapter_type": "local",
    "adapter_config": {
        "module_path": "tests.fixtures.toy_agent",
        "callable_name": "invoke_async",
    },
    "observability_level": 2,
}


async def _create_version(
    client: AsyncClient, token: str, agent_id: str, label: str = "v1", **overrides: object
) -> dict[str, object]:
    body = {"label": label, **_LOCAL_CONFIG, **overrides}
    resp = await client.post(
        f"/api/v1/agents/{agent_id}/versions", json=body, headers=_auth_headers(token)
    )
    return dict(resp.json())


# ---- Agent CRUD ----------------------------------------------------


async def test_authenticated_agent_creation(client: AsyncClient) -> None:
    token = await _register_and_login(client, "reg1@example.com")
    project_id = await _create_project(client, token)

    resp = await client.post(
        "/api/v1/agents",
        json={"project_id": project_id, "name": "Support Agent", "description": "handles refunds"},
        headers=_auth_headers(token),
    )

    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "Support Agent"
    assert body["description"] == "handles refunds"
    assert body["project_id"] == project_id
    assert body["is_enabled"] is True
    assert body["min_call_interval_ms"] == 0
    assert body["default_timeout_ms"] == 30000
    assert body["default_expected_behavior"] is None


async def test_unauthenticated_agent_creation_is_rejected(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/agents", json={"project_id": str(uuid.uuid4()), "name": "x"})
    assert resp.status_code == 401


async def test_agent_creation_under_nonexistent_project_is_404(client: AsyncClient) -> None:
    token = await _register_and_login(client, "reg2@example.com")

    resp = await client.post(
        "/api/v1/agents",
        json={"project_id": str(uuid.uuid4()), "name": "x"},
        headers=_auth_headers(token),
    )

    assert resp.status_code == 404


async def test_agent_creation_under_another_users_project_is_403(client: AsyncClient) -> None:
    token_a = await _register_and_login(client, "reg3a@example.com")
    token_b = await _register_and_login(client, "reg3b@example.com")
    project_id = await _create_project(client, token_a)

    resp = await client.post(
        "/api/v1/agents",
        json={"project_id": project_id, "name": "x"},
        headers=_auth_headers(token_b),
    )

    assert resp.status_code == 403


async def test_list_agents_requires_project_id(client: AsyncClient) -> None:
    token = await _register_and_login(client, "reg4@example.com")
    project_id = await _create_project(client, token)
    await _create_agent(client, token, project_id)

    resp = await client.get(
        "/api/v1/agents", params={"project_id": project_id}, headers=_auth_headers(token)
    )

    assert resp.status_code == 200
    assert len(resp.json()) == 1


async def test_get_agent(client: AsyncClient) -> None:
    token = await _register_and_login(client, "reg5@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)

    resp = await client.get(f"/api/v1/agents/{agent_id}", headers=_auth_headers(token))

    assert resp.status_code == 200
    assert resp.json()["id"] == agent_id


async def test_get_nonexistent_agent_is_404(client: AsyncClient) -> None:
    token = await _register_and_login(client, "reg6@example.com")

    resp = await client.get(f"/api/v1/agents/{uuid.uuid4()}", headers=_auth_headers(token))

    assert resp.status_code == 404


async def test_cross_user_agent_access_is_403(client: AsyncClient) -> None:
    token_a = await _register_and_login(client, "reg7a@example.com")
    token_b = await _register_and_login(client, "reg7b@example.com")
    project_id = await _create_project(client, token_a)
    agent_id = await _create_agent(client, token_a, project_id)

    resp = await client.get(f"/api/v1/agents/{agent_id}", headers=_auth_headers(token_b))

    assert resp.status_code == 403


async def test_update_agent(client: AsyncClient) -> None:
    token = await _register_and_login(client, "reg8@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)

    resp = await client.patch(
        f"/api/v1/agents/{agent_id}",
        json={
            "description": "updated description",
            "default_expected_behavior": ["ask for order id"],
            "default_timeout_ms": 5000,
        },
        headers=_auth_headers(token),
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["description"] == "updated description"
    assert body["default_expected_behavior"] == ["ask for order id"]
    assert body["default_timeout_ms"] == 5000
    assert body["name"] == "Support Agent"  # untouched field preserved


async def test_cross_user_agent_update_is_403(client: AsyncClient) -> None:
    token_a = await _register_and_login(client, "reg9a@example.com")
    token_b = await _register_and_login(client, "reg9b@example.com")
    project_id = await _create_project(client, token_a)
    agent_id = await _create_agent(client, token_a, project_id)

    resp = await client.patch(
        f"/api/v1/agents/{agent_id}",
        json={"name": "hijacked"},
        headers=_auth_headers(token_b),
    )

    assert resp.status_code == 403


# ---- AgentVersion ----------------------------------------------------


async def test_version_creation(client: AsyncClient) -> None:
    token = await _register_and_login(client, "ver1@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)

    body = await _create_version(client, token, agent_id, label="v1")

    assert body["label"] == "v1"
    assert body["adapter_type"] == "local"
    assert body["observability_level"] == 2
    assert body["is_baseline"] is False
    assert body["adapter_config"] == _LOCAL_CONFIG["adapter_config"]


async def test_unauthenticated_version_creation_is_rejected(client: AsyncClient) -> None:
    resp = await client.post(
        f"/api/v1/agents/{uuid.uuid4()}/versions",
        json={"label": "v1", **_LOCAL_CONFIG},
    )
    assert resp.status_code == 401


async def test_invalid_adapter_type_is_422(client: AsyncClient) -> None:
    token = await _register_and_login(client, "ver2@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)

    resp = await client.post(
        f"/api/v1/agents/{agent_id}/versions",
        json={
            "label": "v1",
            "adapter_type": "webhook",
            "adapter_config": {},
            "observability_level": 1,
        },
        headers=_auth_headers(token),
    )

    assert resp.status_code == 422


async def test_invalid_observability_level_is_422(client: AsyncClient) -> None:
    token = await _register_and_login(client, "ver3@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)

    resp = await client.post(
        f"/api/v1/agents/{agent_id}/versions",
        json={
            "label": "v1",
            "adapter_type": "local",
            "adapter_config": {"module_path": "tests.fixtures.toy_agent"},
            "observability_level": 5,
        },
        headers=_auth_headers(token),
    )

    assert resp.status_code == 422


async def test_malformed_http_adapter_config_is_422(client: AsyncClient) -> None:
    """Proves adapter_config shape is validated by reusing the real Phase
    10 HTTPAdapterConfig schema — a missing `url` is rejected at
    registration, not only discovered later at test-invoke time."""
    token = await _register_and_login(client, "ver4@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)

    resp = await client.post(
        f"/api/v1/agents/{agent_id}/versions",
        json={
            "label": "v1",
            "adapter_type": "http",
            "adapter_config": {"method": "POST"},  # missing required "url"
            "observability_level": 1,
        },
        headers=_auth_headers(token),
    )

    assert resp.status_code == 422


async def test_duplicate_version_label_is_409(client: AsyncClient) -> None:
    token = await _register_and_login(client, "ver5@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    await _create_version(client, token, agent_id, label="v1")

    resp = await client.post(
        f"/api/v1/agents/{agent_id}/versions",
        json={"label": "v1", **_LOCAL_CONFIG},
        headers=_auth_headers(token),
    )

    assert resp.status_code == 409


async def test_list_versions(client: AsyncClient) -> None:
    token = await _register_and_login(client, "ver6@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    await _create_version(client, token, agent_id, label="v1")
    await _create_version(client, token, agent_id, label="v2")

    resp = await client.get(
        f"/api/v1/agents/{agent_id}/versions", headers=_auth_headers(token)
    )

    assert resp.status_code == 200
    labels = {v["label"] for v in resp.json()}
    assert labels == {"v1", "v2"}


async def test_cross_user_version_access_is_403(client: AsyncClient) -> None:
    token_a = await _register_and_login(client, "ver7a@example.com")
    token_b = await _register_and_login(client, "ver7b@example.com")
    project_id = await _create_project(client, token_a)
    agent_id = await _create_agent(client, token_a, project_id)
    await _create_version(client, token_a, agent_id, label="v1")

    resp = await client.get(
        f"/api/v1/agents/{agent_id}/versions", headers=_auth_headers(token_b)
    )

    assert resp.status_code == 403


async def test_version_id_from_a_different_agent_is_404(client: AsyncClient) -> None:
    """A version that exists, but not under *this* agent_id, must not be
    reachable through the wrong agent's path — proves the ownership
    check ties version_id to agent_id, not just to the user."""
    token = await _register_and_login(client, "ver8@example.com")
    project_id = await _create_project(client, token)
    agent_1 = await _create_agent(client, token, project_id, name="Agent One")
    agent_2 = await _create_agent(client, token, project_id, name="Agent Two")
    version = await _create_version(client, token, agent_1, label="v1")

    resp = await client.post(
        f"/api/v1/agents/{agent_2}/versions/{version['id']}/baseline",
        headers=_auth_headers(token),
    )

    assert resp.status_code == 404


# ---- Baseline ----------------------------------------------------


async def test_promoting_a_version_sets_baseline(client: AsyncClient) -> None:
    token = await _register_and_login(client, "base1@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    version = await _create_version(client, token, agent_id, label="v1")

    resp = await client.post(
        f"/api/v1/agents/{agent_id}/versions/{version['id']}/baseline",
        headers=_auth_headers(token),
    )

    assert resp.status_code == 200
    assert resp.json()["is_baseline"] is True


async def test_only_one_baseline_per_agent(client: AsyncClient) -> None:
    token = await _register_and_login(client, "base2@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    v1 = await _create_version(client, token, agent_id, label="v1")
    v2 = await _create_version(client, token, agent_id, label="v2")

    await client.post(
        f"/api/v1/agents/{agent_id}/versions/{v1['id']}/baseline", headers=_auth_headers(token)
    )
    resp = await client.post(
        f"/api/v1/agents/{agent_id}/versions/{v2['id']}/baseline", headers=_auth_headers(token)
    )
    assert resp.status_code == 200
    assert resp.json()["is_baseline"] is True

    versions = await client.get(
        f"/api/v1/agents/{agent_id}/versions", headers=_auth_headers(token)
    )
    baseline_flags = {v["label"]: v["is_baseline"] for v in versions.json()}
    assert baseline_flags == {"v1": False, "v2": True}


async def test_promoting_the_current_baseline_again_is_idempotent(client: AsyncClient) -> None:
    token = await _register_and_login(client, "base3@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    v1 = await _create_version(client, token, agent_id, label="v1")

    await client.post(
        f"/api/v1/agents/{agent_id}/versions/{v1['id']}/baseline", headers=_auth_headers(token)
    )
    resp = await client.post(
        f"/api/v1/agents/{agent_id}/versions/{v1['id']}/baseline", headers=_auth_headers(token)
    )

    assert resp.status_code == 200
    assert resp.json()["is_baseline"] is True


async def test_cross_user_baseline_promotion_is_403(client: AsyncClient) -> None:
    token_a = await _register_and_login(client, "base4a@example.com")
    token_b = await _register_and_login(client, "base4b@example.com")
    project_id = await _create_project(client, token_a)
    agent_id = await _create_agent(client, token_a, project_id)
    version = await _create_version(client, token_a, agent_id, label="v1")

    resp = await client.post(
        f"/api/v1/agents/{agent_id}/versions/{version['id']}/baseline",
        headers=_auth_headers(token_b),
    )

    assert resp.status_code == 403


# ---- Immutability ----------------------------------------------------


async def test_no_route_exists_to_mutate_a_version(client: AsyncClient) -> None:
    """Immutability is enforced structurally: there is no PATCH/PUT route
    for an AgentVersion at all, so adapter_type/adapter_config/
    observability_level/label can never be changed after creation."""
    token = await _register_and_login(client, "immut1@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    version = await _create_version(client, token, agent_id, label="v1")

    resp = await client.patch(
        f"/api/v1/agents/{agent_id}/versions/{version['id']}",
        json={"label": "renamed"},
        headers=_auth_headers(token),
    )

    assert resp.status_code in (404, 405)


async def test_adapter_config_is_unchanged_after_baseline_promotion(
    client: AsyncClient,
) -> None:
    token = await _register_and_login(client, "immut2@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    version = await _create_version(client, token, agent_id, label="v1")
    original_config = version["adapter_config"]

    await client.post(
        f"/api/v1/agents/{agent_id}/versions/{version['id']}/baseline",
        headers=_auth_headers(token),
    )

    resp = await client.get(
        f"/api/v1/agents/{agent_id}/versions", headers=_auth_headers(token)
    )
    refetched = next(v for v in resp.json() if v["id"] == version["id"])
    assert refetched["adapter_config"] == original_config
    assert refetched["adapter_type"] == "local"
    assert refetched["observability_level"] == 2


# ---- test-invoke ----------------------------------------------------


async def test_test_invoke_uses_persisted_version_and_returns_agent_execution(
    client: AsyncClient,
) -> None:
    token = await _register_and_login(client, "invoke1@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    version = await _create_version(client, token, agent_id, label="v1")

    resp = await client.post(
        f"/api/v1/agents/{agent_id}/versions/{version['id']}/test-invoke",
        json={"input": {"question": "what is 6*7"}},
        headers=_auth_headers(token),
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["output"] == {"answer": "42"}
    assert len(body["tool_calls"]) == 1
    assert body["tool_calls"][0]["tool_name"] == "calculator"
    assert "request_id" in body
    assert body["latency_ms"] >= 0


async def test_test_invoke_calls_the_phase_10_adapter_factory(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Proves the registry layer reuses build_adapter() rather than
    duplicating adapter-invocation logic — asserts it is called with
    exactly the persisted version's adapter_type/adapter_config."""
    token = await _register_and_login(client, "invoke2@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    version = await _create_version(client, token, agent_id, label="v1")

    calls: list[tuple[str, dict[str, object]]] = []
    real_build_adapter = agent_service.build_adapter

    def _spy_build_adapter(adapter_type: str, adapter_config: dict[str, object]) -> object:
        calls.append((adapter_type, adapter_config))
        return real_build_adapter(adapter_type, adapter_config)

    monkeypatch.setattr(agent_service, "build_adapter", _spy_build_adapter)

    resp = await client.post(
        f"/api/v1/agents/{agent_id}/versions/{version['id']}/test-invoke",
        json={"input": {"question": "hi"}},
        headers=_auth_headers(token),
    )

    assert resp.status_code == 200
    assert calls == [("local", _LOCAL_CONFIG["adapter_config"])]


async def test_test_invoke_does_not_create_a_legacy_run(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    token = await _register_and_login(client, "invoke3@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    version = await _create_version(client, token, agent_id, label="v1")

    await client.post(
        f"/api/v1/agents/{agent_id}/versions/{version['id']}/test-invoke",
        json={"input": {"question": "hi"}},
        headers=_auth_headers(token),
    )

    result = await db_session.execute(select(Run))
    assert result.scalars().all() == []


async def test_test_invoke_agent_exception_is_200_with_error_status(client: AsyncClient) -> None:
    token = await _register_and_login(client, "invoke4@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    version = await _create_version(
        client,
        token,
        agent_id,
        label="v1",
        adapter_config={
            "module_path": "tests.fixtures.toy_agent",
            "callable_name": "invoke_raises",
        },
    )

    resp = await client.post(
        f"/api/v1/agents/{agent_id}/versions/{version['id']}/test-invoke",
        json={"input": {}},
        headers=_auth_headers(token),
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "error"
    assert "the toy agent broke" in body["error"]


async def test_unauthenticated_test_invoke_is_rejected(client: AsyncClient) -> None:
    resp = await client.post(
        f"/api/v1/agents/{uuid.uuid4()}/versions/{uuid.uuid4()}/test-invoke",
        json={"input": {}},
    )
    assert resp.status_code == 401


async def test_cross_user_test_invoke_is_403(client: AsyncClient) -> None:
    token_a = await _register_and_login(client, "invoke5a@example.com")
    token_b = await _register_and_login(client, "invoke5b@example.com")
    project_id = await _create_project(client, token_a)
    agent_id = await _create_agent(client, token_a, project_id)
    version = await _create_version(client, token_a, agent_id, label="v1")

    resp = await client.post(
        f"/api/v1/agents/{agent_id}/versions/{version['id']}/test-invoke",
        json={"input": {}},
        headers=_auth_headers(token_b),
    )

    assert resp.status_code == 403


async def test_test_invoke_nonexistent_version_is_404(client: AsyncClient) -> None:
    token = await _register_and_login(client, "invoke6@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)

    resp = await client.post(
        f"/api/v1/agents/{agent_id}/versions/{uuid.uuid4()}/test-invoke",
        json={"input": {}},
        headers=_auth_headers(token),
    )

    assert resp.status_code == 404
