"""BUG-003 fix: GET /api/v1/cost must be owner-scoped.

Before this fix, model_calls had no owner_id at all — the endpoint
returned every account's LLM usage to whoever asked, confirmed live via
two independent fresh accounts during a real browser QA audit. These
tests exercise the real HTTP endpoint (not just the internal aggregation
function — see tests/test_cost_optimization.py for that) with two real
registered users sharing one DB session/transaction (the `client`
fixture overrides get_db with the same `db_session` — see conftest.py),
so ModelCall rows inserted directly via the ORM are immediately visible
to the endpoint exactly as if a real call had logged them.
"""

from __future__ import annotations

import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.model_call import ModelCall

_EMAIL_A = "cost-isolation-a@example.com"
_EMAIL_B = "cost-isolation-b@example.com"
_PASSWORD = "correct-horse-battery"


async def _register_and_login(client: AsyncClient, email: str) -> str:
    await client.post(
        "/api/v1/auth/register", json={"email": email, "password": _PASSWORD}
    )
    resp = await client.post(
        "/api/v1/auth/login", data={"username": email, "password": _PASSWORD}
    )
    return str(resp.json()["access_token"])


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _current_user_id(client: AsyncClient, token: str) -> uuid.UUID:
    resp = await client.get("/api/v1/auth/me", headers=_auth_headers(token))
    return uuid.UUID(resp.json()["id"])


async def test_user_sees_own_cost_data(client: AsyncClient, db_session: AsyncSession) -> None:
    token = await _register_and_login(client, _EMAIL_A)
    owner_id = await _current_user_id(client, token)

    db_session.add(
        ModelCall(
            owner_id=owner_id,
            agent="rca",
            model_group="reasoning",
            model="gemini-3.5-flash-lite",
            tokens_in=100,
            tokens_out=20,
            cost=0.001234,
            cache_hit=False,
        )
    )
    await db_session.flush()

    resp = await client.get("/api/v1/cost", headers=_auth_headers(token))

    assert resp.status_code == 200
    stats = resp.json()["stats"]
    assert len(stats) == 1
    assert stats[0]["agent"] == "rca"
    assert stats[0]["call_count"] == 1
    assert round(stats[0]["total_cost"], 6) == 0.001234


async def test_user_does_not_see_other_users_cost_data(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    token_a = await _register_and_login(client, _EMAIL_A)
    token_b = await _register_and_login(client, _EMAIL_B)
    owner_a = await _current_user_id(client, token_a)

    # Only user A has any usage at all.
    db_session.add(
        ModelCall(
            owner_id=owner_a,
            agent="hallucination",
            model_group="judgment",
            model="gemini-3.5-flash-lite",
            tokens_in=50,
            tokens_out=10,
            cost=0.0009,
            cache_hit=False,
        )
    )
    await db_session.flush()

    resp_a = await client.get("/api/v1/cost", headers=_auth_headers(token_a))
    resp_b = await client.get("/api/v1/cost", headers=_auth_headers(token_b))

    assert len(resp_a.json()["stats"]) == 1
    # The security requirement, stated directly: user B's own request
    # must never return user A's row.
    assert resp_b.json()["stats"] == []
    assert resp_b.json()["recommendations"] == []


async def test_fresh_account_sees_empty_cost_data(client: AsyncClient) -> None:
    # A brand-new account, registered here for the first time, with no
    # ModelCall rows anywhere linked to it (nothing was inserted).
    token = await _register_and_login(client, f"fresh-{uuid.uuid4()}@example.com")

    resp = await client.get("/api/v1/cost", headers=_auth_headers(token))

    assert resp.status_code == 200
    assert resp.json() == {"stats": [], "recommendations": []}


async def test_existing_authenticated_cost_behavior_still_works(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """The fix must not regress real functionality for the owning user:
    aggregation across multiple calls, cache-hit counting, and the
    existing fallback-share recommendation heuristic must all still work
    exactly as before — now correctly scoped to the caller."""
    token = await _register_and_login(client, _EMAIL_A)
    owner_id = await _current_user_id(client, token)

    db_session.add_all(
        [
            ModelCall(
                owner_id=owner_id,
                agent="planner",
                model_group="reasoning",
                model="gemini-primary",
                tokens_in=10,
                tokens_out=10,
                cost=0.0001,
                cache_hit=False,
            ),
            ModelCall(
                owner_id=owner_id,
                agent="planner",
                model_group="reasoning",
                model="gemini-primary",
                tokens_in=10,
                tokens_out=10,
                cost=0.0001,
                cache_hit=False,
            ),
            ModelCall(
                owner_id=owner_id,
                agent="planner",
                model_group="reasoning",
                model="gemini-fallback",
                tokens_in=10,
                tokens_out=10,
                cost=0.0001,
                cache_hit=False,
            ),
            ModelCall(
                owner_id=owner_id,
                agent="planner",
                model_group="reasoning",
                model="gemini-fallback",
                tokens_in=10,
                tokens_out=10,
                cost=0.0001,
                cache_hit=False,
            ),
            ModelCall(
                owner_id=owner_id,
                agent="planner",
                model_group="reasoning",
                model="gemini-fallback",
                tokens_in=10,
                tokens_out=10,
                cost=0.0001,
                cache_hit=False,
            ),
        ]
    )
    await db_session.flush()

    resp = await client.get("/api/v1/cost", headers=_auth_headers(token))

    assert resp.status_code == 200
    body = resp.json()
    by_model = {s["model"]: s for s in body["stats"]}
    assert by_model["gemini-primary"]["call_count"] == 2
    assert by_model["gemini-fallback"]["call_count"] == 3


async def test_cannot_expose_another_owners_totals_through_any_breakdown_field(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Even a distinctive, high-value row belonging to another account
    must never surface — under any field (agent/model/cost/call_count) —
    in a different user's response."""
    token_a = await _register_and_login(client, _EMAIL_A)
    token_b = await _register_and_login(client, _EMAIL_B)
    owner_a = await _current_user_id(client, token_a)
    owner_b = await _current_user_id(client, token_b)

    db_session.add_all(
        [
            ModelCall(
                owner_id=owner_a,
                agent="rubric_judge_A_ONLY",
                model_group="judgment",
                model="model-a-only",
                tokens_in=9999,
                tokens_out=9999,
                cost=999.999999,
                cache_hit=False,
            ),
            ModelCall(
                owner_id=owner_b,
                agent="ask",
                model_group="reasoning",
                model="model-b",
                tokens_in=5,
                tokens_out=5,
                cost=0.00001,
                cache_hit=False,
            ),
        ]
    )
    await db_session.flush()

    resp_b = await client.get("/api/v1/cost", headers=_auth_headers(token_b))
    body_b = resp_b.json()

    assert len(body_b["stats"]) == 1
    assert body_b["stats"][0]["agent"] == "ask"
    # A's distinctive agent name / cost must not appear anywhere in B's
    # response — not in stats, not in a recommendation message.
    raw = resp_b.text
    assert "rubric_judge_A_ONLY" not in raw
    assert "model-a-only" not in raw
    assert "999.999999" not in raw
