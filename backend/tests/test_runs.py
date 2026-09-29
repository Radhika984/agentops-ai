"""Phase 4/5/6/7 /runs endpoint tests.

call_model() is mocked at the same seam test_ask.py uses (app.agents.planner
looks it up via app.ai.client, matching the pattern already established for
app.services.ask_service) — no network access, no real model call. Tool
calls (web_search, run_python) are likewise mocked at the registry seam
each node uses, and memory_manager.recall()/remember() are mocked too — no
real network/subprocess/embedding/DB calls here, matching
tests/test_agents.py's approach; the real MCP round-trip is covered by
tests/test_tools.py, and the real embed+store+retrieve round trip by
tests/test_memory.py. hallucination_node's call_model() is mocked too —
without it, every /runs test would make a real Gemini call.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.agents.schemas import HallucinationCheck, PlanOutput
from app.tools.registry import ToolCallResult
from tests.conftest import TEST_DATABASE_URL

pytestmark = pytest.mark.anyio


async def _fake_call_model_two_tasks(
    prompt: str, schema: type[PlanOutput], **kwargs: object
) -> PlanOutput:
    return PlanOutput(tasks=["task one", "task two"])


async def _fake_hallucination_check(
    prompt: str, schema: type[HallucinationCheck], **kwargs: object
) -> HallucinationCheck:
    return HallucinationCheck(unsupported_claims=[])


async def _fake_call_tool(tool_name: str, arguments: dict[str, object]) -> ToolCallResult:
    if tool_name == "web_search":
        return ToolCallResult(
            tool_name="web_search",
            input=arguments,
            output="No results found.",
            duration_ms=1,
            ok=True,
        )
    return ToolCallResult(
        tool_name="run_python", input=arguments, output="PASS\n", duration_ms=1, ok=True
    )


async def _fake_recall(query: str, *, source_type: str | None = None, top_k: int = 3) -> list[str]:
    return []


async def _fake_remember(
    *, content: str, source_type: str, source_id: uuid.UUID | None = None
) -> None:
    return None


@pytest.fixture(autouse=True)
def _mock_call_model_and_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.agents.hallucination as hallucination_mod
    import app.agents.planner as planner_mod
    import app.agents.verification as verification_mod
    import app.services.run_service as run_service_mod

    monkeypatch.setattr(planner_mod, "call_model", _fake_call_model_two_tasks)
    monkeypatch.setattr(planner_mod, "call_tool", _fake_call_tool)
    monkeypatch.setattr(verification_mod, "call_tool", _fake_call_tool)
    monkeypatch.setattr(planner_mod.memory_manager, "recall", _fake_recall)
    monkeypatch.setattr(run_service_mod.memory_manager, "remember", _fake_remember)
    monkeypatch.setattr(hallucination_mod, "call_model", _fake_hallucination_check)


@pytest_asyncio.fixture(autouse=True)
async def _background_task_uses_test_database(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncGenerator[None, None]:
    # run_graph_and_persist() runs outside any request's dependency-injected
    # session (see its docstring) — it opens its own via
    # app.services.run_service.AsyncSessionLocal, which by default points at
    # the real dev database. Point it at the same test database the `client`
    # fixture uses instead, so the background task's writes are actually
    # visible to this test's subsequent GET /runs/{id} polls.
    import app.services.run_service as run_service_mod

    engine = create_async_engine(TEST_DATABASE_URL)
    test_session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(run_service_mod, "AsyncSessionLocal", test_session_factory)

    yield

    await engine.dispose()


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


async def _poll_until_terminal(
    client: AsyncClient, project_id: str, run_id: str, token: str, attempts: int = 20
) -> dict[str, object]:
    for _ in range(attempts):
        resp = await client.get(
            f"/api/v1/projects/{project_id}/runs/{run_id}", headers=_auth_headers(token)
        )
        body: dict[str, object] = resp.json()
        if body["status"] in ("succeeded", "failed"):
            return body
        await asyncio.sleep(0.05)
    return body


async def test_create_run_returns_201_with_a_run_id(client: AsyncClient) -> None:
    token = await _register_and_login(client, "run1@example.com")
    project_id = await _create_project(client, token)

    resp = await client.post(
        f"/api/v1/projects/{project_id}/runs",
        json={"goal": "Ship a feature"},
        headers=_auth_headers(token),
    )

    assert resp.status_code == 201
    body = resp.json()
    assert body["project_id"] == project_id
    assert body["goal"] == "Ship a feature"
    assert body["status"] in ("pending", "planning", "evaluating", "verifying", "succeeded")
    uuid.UUID(body["id"])  # does not raise


async def test_run_eventually_reaches_a_terminal_status(client: AsyncClient) -> None:
    token = await _register_and_login(client, "run2@example.com")
    project_id = await _create_project(client, token)

    create_resp = await client.post(
        f"/api/v1/projects/{project_id}/runs",
        json={"goal": "Ship a feature"},
        headers=_auth_headers(token),
    )
    run_id = create_resp.json()["id"]

    final = await _poll_until_terminal(client, project_id, run_id, token)

    assert final["status"] == "succeeded"
    state = final["state"]
    assert isinstance(state, dict)
    assert state["plan"] == ["task one", "task two"]
    assert state["retry_count"] == 0
    assert [tc["tool_name"] for tc in state["tool_calls"]] == ["web_search", "run_python"]


async def test_tool_calls_are_persisted_to_the_audit_table(client: AsyncClient) -> None:
    import sqlalchemy as sa

    from app.models.tool_call import ToolCall
    from app.services import run_service as run_service_mod

    token = await _register_and_login(client, "run-toolcalls@example.com")
    project_id = await _create_project(client, token)

    create_resp = await client.post(
        f"/api/v1/projects/{project_id}/runs",
        json={"goal": "Ship a feature"},
        headers=_auth_headers(token),
    )
    run_id = create_resp.json()["id"]

    await _poll_until_terminal(client, project_id, run_id, token)

    async with run_service_mod.AsyncSessionLocal() as session:
        result = await session.execute(
            sa.select(ToolCall).where(ToolCall.run_id == uuid.UUID(run_id))
        )
        rows = result.scalars().all()

    assert {row.tool_name for row in rows} == {"web_search", "run_python"}
    assert all(row.duration_ms >= 0 for row in rows)


async def test_trace_is_persisted_in_run_state(client: AsyncClient) -> None:
    token = await _register_and_login(client, "run-trace@example.com")
    project_id = await _create_project(client, token)

    create_resp = await client.post(
        f"/api/v1/projects/{project_id}/runs",
        json={"goal": "Ship a feature"},
        headers=_auth_headers(token),
    )
    run_id = create_resp.json()["id"]

    final = await _poll_until_terminal(client, project_id, run_id, token)

    # Phase 7: trace is stitched into the persisted state blob by
    # run_repository.update_state()'s `extra` param (see run_service.py) —
    # it's OTel span data, not part of AgentState itself.
    state = final["state"]
    assert isinstance(state, dict)
    assert "trace" in state
    trace = state["trace"]
    assert isinstance(trace, list)
    assert len(trace) > 0
    # Every graph node (planner, evaluation, hallucination, verification,
    # succeed) should have produced a span for a happy-path run.
    span_names = {span["name"] for span in trace}
    assert {"planner", "evaluation", "hallucination", "verification", "succeed"} <= span_names
    assert all(span["duration_ms"] >= 0 for span in trace)


async def test_no_flags_persisted_for_a_clean_happy_path_run(client: AsyncClient) -> None:
    import sqlalchemy as sa

    from app.models.flag import Flag
    from app.services import run_service as run_service_mod

    token = await _register_and_login(client, "run-noflags@example.com")
    project_id = await _create_project(client, token)

    create_resp = await client.post(
        f"/api/v1/projects/{project_id}/runs",
        json={"goal": "Ship a feature"},
        headers=_auth_headers(token),
    )
    run_id = create_resp.json()["id"]

    await _poll_until_terminal(client, project_id, run_id, token)

    # Nothing in this test's mocked path (see _fake_call_tool,
    # _fake_hallucination_check) should trigger a Safety block or a
    # Hallucination finding — the flags table should stay empty for this run.
    async with run_service_mod.AsyncSessionLocal() as session:
        result = await session.execute(
            sa.select(Flag).where(Flag.run_id == uuid.UUID(run_id))
        )
        rows = result.scalars().all()

    assert rows == []


async def test_get_run_requires_authentication(client: AsyncClient) -> None:
    token = await _register_and_login(client, "run3@example.com")
    project_id = await _create_project(client, token)
    create_resp = await client.post(
        f"/api/v1/projects/{project_id}/runs",
        json={"goal": "goal"},
        headers=_auth_headers(token),
    )
    run_id = create_resp.json()["id"]

    resp = await client.get(f"/api/v1/projects/{project_id}/runs/{run_id}")

    assert resp.status_code == 401


async def test_create_run_on_nonexistent_project_returns_404(client: AsyncClient) -> None:
    token = await _register_and_login(client, "run4@example.com")

    resp = await client.post(
        f"/api/v1/projects/{uuid.uuid4()}/runs",
        json={"goal": "goal"},
        headers=_auth_headers(token),
    )

    assert resp.status_code == 404


async def test_user_cannot_create_run_on_another_users_project(client: AsyncClient) -> None:
    token_a = await _register_and_login(client, "run5@example.com")
    token_b = await _register_and_login(client, "run6@example.com")
    project_id = await _create_project(client, token_a, name="A's project")

    resp = await client.post(
        f"/api/v1/projects/{project_id}/runs",
        json={"goal": "goal"},
        headers=_auth_headers(token_b),
    )

    assert resp.status_code == 403


async def test_user_cannot_get_another_users_run(client: AsyncClient) -> None:
    token_a = await _register_and_login(client, "run7@example.com")
    token_b = await _register_and_login(client, "run8@example.com")
    project_id = await _create_project(client, token_a, name="A's project")
    create_resp = await client.post(
        f"/api/v1/projects/{project_id}/runs",
        json={"goal": "goal"},
        headers=_auth_headers(token_a),
    )
    run_id = create_resp.json()["id"]

    resp = await client.get(
        f"/api/v1/projects/{project_id}/runs/{run_id}", headers=_auth_headers(token_b)
    )

    assert resp.status_code == 403


async def test_get_nonexistent_run_returns_404(client: AsyncClient) -> None:
    token = await _register_and_login(client, "run9@example.com")
    project_id = await _create_project(client, token)

    resp = await client.get(
        f"/api/v1/projects/{project_id}/runs/{uuid.uuid4()}", headers=_auth_headers(token)
    )

    assert resp.status_code == 404
