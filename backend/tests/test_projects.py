from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.anyio


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


async def test_authenticated_user_can_create_project(client: AsyncClient) -> None:
    token = await _register_and_login(client, "owner1@example.com")
    resp = await client.post(
        "/api/v1/projects",
        json={"name": "Project A", "description": "desc"},
        headers=_auth_headers(token),
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "Project A"
    assert body["owner_id"]


async def test_unauthenticated_user_cannot_create_project(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/projects", json={"name": "Project A"})
    assert resp.status_code == 401


async def test_owner_id_cannot_be_client_supplied(client: AsyncClient) -> None:
    token = await _register_and_login(client, "owner2@example.com")
    fake_owner = str(uuid.uuid4())
    resp = await client.post(
        "/api/v1/projects",
        json={"name": "Project A", "owner_id": fake_owner},
        headers=_auth_headers(token),
    )
    assert resp.status_code == 201
    assert resp.json()["owner_id"] != fake_owner


async def test_user_can_list_own_projects(client: AsyncClient) -> None:
    token = await _register_and_login(client, "owner3@example.com")
    await client.post("/api/v1/projects", json={"name": "P1"}, headers=_auth_headers(token))
    await client.post("/api/v1/projects", json={"name": "P2"}, headers=_auth_headers(token))
    resp = await client.get("/api/v1/projects", headers=_auth_headers(token))
    assert resp.status_code == 200
    assert len(resp.json()) == 2


async def test_user_only_sees_own_projects(client: AsyncClient) -> None:
    token_a = await _register_and_login(client, "usera@example.com")
    token_b = await _register_and_login(client, "userb@example.com")

    await client.post(
        "/api/v1/projects", json={"name": "A's project"}, headers=_auth_headers(token_a)
    )
    resp = await client.get("/api/v1/projects", headers=_auth_headers(token_b))
    assert resp.status_code == 200
    assert resp.json() == []


async def test_user_can_get_own_project(client: AsyncClient) -> None:
    token = await _register_and_login(client, "owner4@example.com")
    create_resp = await client.post(
        "/api/v1/projects", json={"name": "P"}, headers=_auth_headers(token)
    )
    project_id = create_resp.json()["id"]

    resp = await client.get(f"/api/v1/projects/{project_id}", headers=_auth_headers(token))
    assert resp.status_code == 200
    assert resp.json()["id"] == project_id


async def test_nonexistent_project_returns_404(client: AsyncClient) -> None:
    token = await _register_and_login(client, "owner5@example.com")
    resp = await client.get(f"/api/v1/projects/{uuid.uuid4()}", headers=_auth_headers(token))
    assert resp.status_code == 404


async def test_user_cannot_access_another_users_project(client: AsyncClient) -> None:
    token_a = await _register_and_login(client, "userc@example.com")
    token_b = await _register_and_login(client, "userd@example.com")

    create_resp = await client.post(
        "/api/v1/projects", json={"name": "C's project"}, headers=_auth_headers(token_a)
    )
    project_id = create_resp.json()["id"]

    resp = await client.get(f"/api/v1/projects/{project_id}", headers=_auth_headers(token_b))
    assert resp.status_code == 403


async def test_user_can_update_own_project(client: AsyncClient) -> None:
    token = await _register_and_login(client, "owner6@example.com")
    create_resp = await client.post(
        "/api/v1/projects", json={"name": "Old name"}, headers=_auth_headers(token)
    )
    project_id = create_resp.json()["id"]

    resp = await client.patch(
        f"/api/v1/projects/{project_id}",
        json={"name": "New name"},
        headers=_auth_headers(token),
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "New name"


async def test_user_cannot_update_another_users_project(client: AsyncClient) -> None:
    token_a = await _register_and_login(client, "usere@example.com")
    token_b = await _register_and_login(client, "userf@example.com")

    create_resp = await client.post(
        "/api/v1/projects", json={"name": "E's project"}, headers=_auth_headers(token_a)
    )
    project_id = create_resp.json()["id"]

    resp = await client.patch(
        f"/api/v1/projects/{project_id}",
        json={"name": "Hijacked"},
        headers=_auth_headers(token_b),
    )
    assert resp.status_code == 403


async def test_user_can_delete_own_project(client: AsyncClient) -> None:
    token = await _register_and_login(client, "owner7@example.com")
    create_resp = await client.post(
        "/api/v1/projects", json={"name": "To delete"}, headers=_auth_headers(token)
    )
    project_id = create_resp.json()["id"]

    resp = await client.delete(f"/api/v1/projects/{project_id}", headers=_auth_headers(token))
    assert resp.status_code == 204


async def test_user_cannot_delete_another_users_project(client: AsyncClient) -> None:
    token_a = await _register_and_login(client, "userg@example.com")
    token_b = await _register_and_login(client, "userh@example.com")

    create_resp = await client.post(
        "/api/v1/projects", json={"name": "G's project"}, headers=_auth_headers(token_a)
    )
    project_id = create_resp.json()["id"]

    resp = await client.delete(f"/api/v1/projects/{project_id}", headers=_auth_headers(token_b))
    assert resp.status_code == 403


async def test_deleted_project_no_longer_appears(client: AsyncClient) -> None:
    token = await _register_and_login(client, "owner8@example.com")
    create_resp = await client.post(
        "/api/v1/projects", json={"name": "Ephemeral"}, headers=_auth_headers(token)
    )
    project_id = create_resp.json()["id"]

    await client.delete(f"/api/v1/projects/{project_id}", headers=_auth_headers(token))

    resp = await client.get(f"/api/v1/projects/{project_id}", headers=_auth_headers(token))
    assert resp.status_code == 404
