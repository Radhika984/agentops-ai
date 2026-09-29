"""Phase 2.5 / 2.6 authenticated /ask endpoint tests.

The OpenAI boundary is mocked at call_model() — no OPENAI_API_KEY, no
network access, no real model call. These tests verify the complete
authenticated flow (register/login -> create project -> POST /ask ->
mocked call_model() -> Interaction persisted -> response contains the
expected answer/confidence), plus the authentication and project
ownership boundaries.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.schemas import AnswerResponse
from app.models.interaction import Interaction
from app.services import ask_service

pytestmark = pytest.mark.anyio


async def _fake_call_model(
    prompt: str, schema: type[AnswerResponse], **kwargs: object
) -> AnswerResponse:
    assert "What is the capital of France?" in prompt
    return schema(answer="Paris is the capital of France.", confidence=0.95)


@pytest.fixture(autouse=True)
def _mock_call_model(monkeypatch: pytest.MonkeyPatch) -> None:
    # Patches the name inside app.services.ask_service (where it is looked up
    # at call time), not app.ai.client — the real call_model()/retry logic
    # from Phase 2.3 is untouched and still covered by tests/test_ai_client.py.
    monkeypatch.setattr(ask_service, "call_model", _fake_call_model)


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


async def test_authenticated_ask_returns_answer_and_confidence(client: AsyncClient) -> None:
    token = await _register_and_login(client, "asker1@example.com")
    project_id = await _create_project(client, token)

    resp = await client.post(
        f"/api/v1/projects/{project_id}/ask",
        json={"question": "What is the capital of France?"},
        headers=_auth_headers(token),
    )

    assert resp.status_code == 201
    body = resp.json()
    assert body["answer"] == "Paris is the capital of France."
    assert body["confidence"] == 0.95
    assert body["project_id"] == project_id
    assert body["question"] == "What is the capital of France?"


async def test_ask_persists_an_interaction(client: AsyncClient, db_session: AsyncSession) -> None:
    token = await _register_and_login(client, "asker2@example.com")
    project_id = await _create_project(client, token)

    resp = await client.post(
        f"/api/v1/projects/{project_id}/ask",
        json={"question": "What is the capital of France?"},
        headers=_auth_headers(token),
    )
    interaction_id = resp.json()["id"]

    result = await db_session.execute(
        select(Interaction).where(Interaction.id == uuid.UUID(interaction_id))
    )
    interaction = result.scalar_one_or_none()

    assert interaction is not None
    assert str(interaction.project_id) == project_id
    assert interaction.prompt == "What is the capital of France?"
    assert interaction.response == "Paris is the capital of France."
    assert interaction.created_at is not None


async def test_unauthenticated_ask_is_rejected(client: AsyncClient) -> None:
    token = await _register_and_login(client, "asker3@example.com")
    project_id = await _create_project(client, token)

    resp = await client.post(
        f"/api/v1/projects/{project_id}/ask",
        json={"question": "What is the capital of France?"},
    )

    assert resp.status_code == 401


async def test_ask_on_nonexistent_project_returns_404(client: AsyncClient) -> None:
    token = await _register_and_login(client, "asker4@example.com")

    resp = await client.post(
        f"/api/v1/projects/{uuid.uuid4()}/ask",
        json={"question": "What is the capital of France?"},
        headers=_auth_headers(token),
    )

    assert resp.status_code == 404


async def test_user_cannot_ask_against_another_users_project(client: AsyncClient) -> None:
    token_a = await _register_and_login(client, "asker5@example.com")
    token_b = await _register_and_login(client, "asker6@example.com")
    project_id = await _create_project(client, token_a, name="A's project")

    resp = await client.post(
        f"/api/v1/projects/{project_id}/ask",
        json={"question": "What is the capital of France?"},
        headers=_auth_headers(token_b),
    )

    assert resp.status_code == 403


async def test_ask_is_not_persisted_when_project_ownership_fails(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    token_a = await _register_and_login(client, "asker7@example.com")
    token_b = await _register_and_login(client, "asker8@example.com")
    project_id = await _create_project(client, token_a, name="A's project")

    await client.post(
        f"/api/v1/projects/{project_id}/ask",
        json={"question": "What is the capital of France?"},
        headers=_auth_headers(token_b),
    )

    result = await db_session.execute(select(Interaction))
    assert result.scalars().all() == []


async def test_history_is_empty_for_a_new_project(client: AsyncClient) -> None:
    token = await _register_and_login(client, "history1@example.com")
    project_id = await _create_project(client, token)

    resp = await client.get(
        f"/api/v1/projects/{project_id}/ask",
        headers=_auth_headers(token),
    )

    assert resp.status_code == 200
    assert resp.json() == []


async def test_history_returns_past_interactions_in_order(client: AsyncClient) -> None:
    token = await _register_and_login(client, "history2@example.com")
    project_id = await _create_project(client, token)

    await client.post(
        f"/api/v1/projects/{project_id}/ask",
        json={"question": "What is the capital of France?"},
        headers=_auth_headers(token),
    )

    resp = await client.get(
        f"/api/v1/projects/{project_id}/ask",
        headers=_auth_headers(token),
    )

    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["question"] == "What is the capital of France?"
    assert body[0]["answer"] == "Paris is the capital of France."
    assert body[0]["project_id"] == project_id
    assert "confidence" not in body[0]


async def test_history_requires_authentication(client: AsyncClient) -> None:
    token = await _register_and_login(client, "history3@example.com")
    project_id = await _create_project(client, token)

    resp = await client.get(f"/api/v1/projects/{project_id}/ask")

    assert resp.status_code == 401


async def test_history_on_nonexistent_project_returns_404(client: AsyncClient) -> None:
    token = await _register_and_login(client, "history4@example.com")

    resp = await client.get(
        f"/api/v1/projects/{uuid.uuid4()}/ask",
        headers=_auth_headers(token),
    )

    assert resp.status_code == 404


async def test_user_cannot_see_another_users_project_history(client: AsyncClient) -> None:
    token_a = await _register_and_login(client, "history5@example.com")
    token_b = await _register_and_login(client, "history6@example.com")
    project_id = await _create_project(client, token_a, name="A's project")

    resp = await client.get(
        f"/api/v1/projects/{project_id}/ask",
        headers=_auth_headers(token_b),
    )

    assert resp.status_code == 403
