"""Global search — real, owner-scoped substring matches (see
app/services/search_service.py). Every result asserted against here is a
real, already-created entity; no result is ever fabricated.
"""

from __future__ import annotations

from httpx import AsyncClient

from tests.test_suite_runs import (
    _auth_headers,
    _create_agent,
    _create_project,
    _create_suite,
    _register_and_login,
)


async def test_search_finds_a_real_project(client: AsyncClient) -> None:
    token = await _register_and_login(client, "search1@example.com")
    project_id = await _create_project(client, token, name="Refund Support Ops")

    resp = await client.get(
        "/api/v1/search", params={"q": "Refund"}, headers=_auth_headers(token)
    )

    assert resp.status_code == 200
    body = resp.json()
    assert any(r["kind"] == "project" and r["id"] == project_id for r in body["results"])
    match = next(r for r in body["results"] if r["id"] == project_id)
    assert match["href"] == f"/projects/{project_id}/chat"


async def test_search_finds_a_real_agent_and_suite(client: AsyncClient) -> None:
    token = await _register_and_login(client, "search2@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id, name="Escalation Triage Agent")
    suite_id = await _create_suite(client, token, agent_id, name="Escalation Suite")

    resp = await client.get(
        "/api/v1/search", params={"q": "Escalation"}, headers=_auth_headers(token)
    )

    kinds_found = {(r["kind"], r["id"]) for r in resp.json()["results"]}
    assert ("agent", agent_id) in kinds_found
    assert ("test_suite", suite_id) in kinds_found


async def test_search_is_owner_scoped(client: AsyncClient) -> None:
    token_a = await _register_and_login(client, "search3a@example.com")
    token_b = await _register_and_login(client, "search3b@example.com")
    await _create_project(client, token_a, name="Only Visible To A")

    resp = await client.get(
        "/api/v1/search", params={"q": "Only Visible"}, headers=_auth_headers(token_b)
    )

    assert resp.json()["results"] == []


async def test_search_with_no_match_returns_empty(client: AsyncClient) -> None:
    token = await _register_and_login(client, "search4@example.com")
    await _create_project(client, token, name="Something Else Entirely")

    resp = await client.get(
        "/api/v1/search", params={"q": "zzzznonexistentzzzz"}, headers=_auth_headers(token)
    )

    assert resp.json()["results"] == []


async def test_search_with_blank_query_returns_empty(client: AsyncClient) -> None:
    token = await _register_and_login(client, "search5@example.com")

    resp = await client.get("/api/v1/search", params={"q": ""}, headers=_auth_headers(token))

    assert resp.status_code == 200
    assert resp.json()["results"] == []


async def test_unauthenticated_search_is_rejected(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/search", params={"q": "anything"})
    assert resp.status_code == 401
