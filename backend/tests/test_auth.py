from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.anyio


async def test_register_succeeds(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": "alice@example.com", "password": "correct-horse-battery"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["email"] == "alice@example.com"
    assert "password" not in body
    assert "hashed_password" not in body


async def test_duplicate_email_rejected(client: AsyncClient) -> None:
    payload = {"email": "bob@example.com", "password": "correct-horse-battery"}
    first = await client.post("/api/v1/auth/register", json=payload)
    assert first.status_code == 201

    second = await client.post("/api/v1/auth/register", json=payload)
    assert second.status_code == 409


async def test_login_succeeds(client: AsyncClient) -> None:
    await client.post(
        "/api/v1/auth/register",
        json={"email": "carol@example.com", "password": "correct-horse-battery"},
    )
    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": "carol@example.com", "password": "correct-horse-battery"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]


async def test_login_fails_wrong_password(client: AsyncClient) -> None:
    await client.post(
        "/api/v1/auth/register",
        json={"email": "dave@example.com", "password": "correct-horse-battery"},
    )
    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": "dave@example.com", "password": "wrong-password"},
    )
    assert resp.status_code == 401


async def test_login_fails_nonexistent_user(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": "nobody@example.com", "password": "whatever123"},
    )
    assert resp.status_code == 401


async def test_me_requires_auth_header(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 401


async def test_me_rejects_malformed_token(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/auth/me", headers={"Authorization": "Bearer not-a-real-token"})
    assert resp.status_code == 401


async def test_me_succeeds_with_valid_token(client: AsyncClient) -> None:
    await client.post(
        "/api/v1/auth/register",
        json={"email": "erin@example.com", "password": "correct-horse-battery"},
    )
    login_resp = await client.post(
        "/api/v1/auth/login",
        data={"username": "erin@example.com", "password": "correct-horse-battery"},
    )
    token = login_resp.json()["access_token"]

    resp = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["email"] == "erin@example.com"
