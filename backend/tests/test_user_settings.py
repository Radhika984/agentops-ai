"""Settings > Profile / Security / Notification Preferences — real,
persisted, authenticated account mutations (see
app/services/auth_service.py's update_profile()/change_password()/
update_notification_preferences()).
"""

from __future__ import annotations

from httpx import AsyncClient

from tests.test_suite_runs import _auth_headers, _register_and_login


async def test_read_current_user_includes_notification_defaults(client: AsyncClient) -> None:
    token = await _register_and_login(client, "settings1@example.com")

    resp = await client.get("/api/v1/auth/me", headers=_auth_headers(token))

    assert resp.status_code == 200
    body = resp.json()
    assert body["notify_on_suite_run_complete"] is True
    assert body["notify_on_release_gate"] is True
    assert body["notify_on_autofix_proposed"] is True
    assert body["notify_on_approval_decided"] is True


async def test_update_profile_persists_full_name(client: AsyncClient) -> None:
    token = await _register_and_login(client, "settings2@example.com")

    resp = await client.patch(
        "/api/v1/auth/me", json={"full_name": "Radhika Sharma"}, headers=_auth_headers(token)
    )

    assert resp.status_code == 200
    assert resp.json()["full_name"] == "Radhika Sharma"

    read_resp = await client.get("/api/v1/auth/me", headers=_auth_headers(token))
    assert read_resp.json()["full_name"] == "Radhika Sharma"


async def test_change_password_requires_correct_current_password(client: AsyncClient) -> None:
    email = "settings3@example.com"
    token = await _register_and_login(client, email)

    resp = await client.patch(
        "/api/v1/auth/me/password",
        json={"current_password": "wrong-password", "new_password": "a-new-password-123"},
        headers=_auth_headers(token),
    )

    assert resp.status_code == 401


async def test_change_password_actually_changes_login(client: AsyncClient) -> None:
    email = "settings4@example.com"
    token = await _register_and_login(client, email)

    change_resp = await client.patch(
        "/api/v1/auth/me/password",
        json={
            "current_password": "correct-horse-battery",
            "new_password": "a-new-password-123",
        },
        headers=_auth_headers(token),
    )
    assert change_resp.status_code == 204

    old_login = await client.post(
        "/api/v1/auth/login", data={"username": email, "password": "correct-horse-battery"}
    )
    assert old_login.status_code == 401

    new_login = await client.post(
        "/api/v1/auth/login", data={"username": email, "password": "a-new-password-123"}
    )
    assert new_login.status_code == 200


async def test_update_notification_preferences_persists(client: AsyncClient) -> None:
    token = await _register_and_login(client, "settings5@example.com")

    resp = await client.patch(
        "/api/v1/auth/me/notifications",
        json={
            "notify_on_suite_run_complete": False,
            "notify_on_release_gate": False,
            "notify_on_autofix_proposed": True,
            "notify_on_approval_decided": True,
        },
        headers=_auth_headers(token),
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["notify_on_suite_run_complete"] is False
    assert body["notify_on_release_gate"] is False

    read_resp = await client.get("/api/v1/auth/me/notifications", headers=_auth_headers(token))
    assert read_resp.json()["notify_on_suite_run_complete"] is False


async def test_unauthenticated_profile_requests_are_rejected(client: AsyncClient) -> None:
    assert (await client.patch("/api/v1/auth/me", json={"full_name": "x"})).status_code == 401
    assert (
        await client.patch(
            "/api/v1/auth/me/password",
            json={"current_password": "a", "new_password": "bbbbbbbb"},
        )
    ).status_code == 401
    assert (await client.get("/api/v1/auth/me/notifications")).status_code == 401
