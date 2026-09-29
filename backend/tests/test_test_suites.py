"""Phase 12 — Evaluation Contract + Test Cases tests.

No evaluation logic exists yet (Phase 13+) — these tests only exercise
storage, ownership, and the ground-truth validation rule.
"""

from __future__ import annotations

import uuid

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.run import Run


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


async def _create_suite(
    client: AsyncClient, token: str, agent_id: str, name: str = "Refunds suite"
) -> str:
    resp = await client.post(
        f"/api/v1/agents/{agent_id}/test-suites",
        json={"name": name},
        headers=_auth_headers(token),
    )
    return str(resp.json()["id"])


async def _agent_and_suite(client: AsyncClient, token: str) -> tuple[str, str]:
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    suite_id = await _create_suite(client, token, agent_id)
    return agent_id, suite_id


BASE_INPUT = {"question": "I want to return my order"}


# ---- TestSuite ----------------------------------------------------


async def test_authenticated_suite_creation(client: AsyncClient) -> None:
    token = await _register_and_login(client, "suite1@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)

    resp = await client.post(
        f"/api/v1/agents/{agent_id}/test-suites",
        json={"name": "Refunds suite"},
        headers=_auth_headers(token),
    )

    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "Refunds suite"
    assert body["agent_id"] == agent_id


async def test_unauthenticated_suite_creation_is_rejected(client: AsyncClient) -> None:
    resp = await client.post(
        f"/api/v1/agents/{uuid.uuid4()}/test-suites", json={"name": "x"}
    )
    assert resp.status_code == 401


async def test_suite_creation_under_nonexistent_agent_is_404(client: AsyncClient) -> None:
    token = await _register_and_login(client, "suite2@example.com")

    resp = await client.post(
        f"/api/v1/agents/{uuid.uuid4()}/test-suites",
        json={"name": "x"},
        headers=_auth_headers(token),
    )

    assert resp.status_code == 404


async def test_suite_creation_under_another_users_agent_is_403(client: AsyncClient) -> None:
    token_a = await _register_and_login(client, "suite3a@example.com")
    token_b = await _register_and_login(client, "suite3b@example.com")
    project_id = await _create_project(client, token_a)
    agent_id = await _create_agent(client, token_a, project_id)

    resp = await client.post(
        f"/api/v1/agents/{agent_id}/test-suites",
        json={"name": "x"},
        headers=_auth_headers(token_b),
    )

    assert resp.status_code == 403


async def test_list_suites(client: AsyncClient) -> None:
    token = await _register_and_login(client, "suite4@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    await _create_suite(client, token, agent_id, name="Suite A")
    await _create_suite(client, token, agent_id, name="Suite B")

    resp = await client.get(
        f"/api/v1/agents/{agent_id}/test-suites", headers=_auth_headers(token)
    )

    assert resp.status_code == 200
    names = {s["name"] for s in resp.json()}
    assert names == {"Suite A", "Suite B"}


async def test_cross_user_suite_listing_is_403(client: AsyncClient) -> None:
    token_a = await _register_and_login(client, "suite5a@example.com")
    token_b = await _register_and_login(client, "suite5b@example.com")
    project_id = await _create_project(client, token_a)
    agent_id = await _create_agent(client, token_a, project_id)
    await _create_suite(client, token_a, agent_id)

    resp = await client.get(
        f"/api/v1/agents/{agent_id}/test-suites", headers=_auth_headers(token_b)
    )

    assert resp.status_code == 403


# ---- TestCase creation — one per ground-truth mechanism -----------


async def test_create_case_with_expected_output(client: AsyncClient) -> None:
    token = await _register_and_login(client, "case1@example.com")
    _, suite_id = await _agent_and_suite(client, token)

    resp = await client.post(
        f"/api/v1/test-suites/{suite_id}/test-cases",
        json={"name": "eligible refund", "input": BASE_INPUT, "expected_output": "Refund approved"},
        headers=_auth_headers(token),
    )

    assert resp.status_code == 201
    body = resp.json()
    assert body["expected_output"] == "Refund approved"
    assert body["rubric_threshold"] == 0.7
    assert body["trial_count"] == 1
    assert body["tags"] == []
    assert body["metadata"] == {}


async def test_create_case_with_assertions(client: AsyncClient) -> None:
    token = await _register_and_login(client, "case2@example.com")
    _, suite_id = await _agent_and_suite(client, token)

    resp = await client.post(
        f"/api/v1/test-suites/{suite_id}/test-cases",
        json={
            "name": "top 5 customers",
            "input": {"question": "top 5 customers by revenue"},
            "assertions": [{"type": "json_path", "path": "$.rows", "op": "length_eq", "value": 5}],
        },
        headers=_auth_headers(token),
    )

    assert resp.status_code == 201
    assert resp.json()["assertions"] == [
        {"type": "json_path", "path": "$.rows", "op": "length_eq", "value": 5}
    ]


async def test_create_case_with_reference_context(client: AsyncClient) -> None:
    token = await _register_and_login(client, "case3@example.com")
    _, suite_id = await _agent_and_suite(client, token)

    resp = await client.post(
        f"/api/v1/test-suites/{suite_id}/test-cases",
        json={
            "name": "cancellation policy",
            "input": {"question": "what is the cancellation policy?"},
            "reference_context": "Cancellations are free within 24 hours.",
        },
        headers=_auth_headers(token),
    )

    assert resp.status_code == 201
    assert resp.json()["reference_context"] == "Cancellations are free within 24 hours."


async def test_create_case_with_expected_tool_calls(client: AsyncClient) -> None:
    token = await _register_and_login(client, "case4@example.com")
    _, suite_id = await _agent_and_suite(client, token)

    resp = await client.post(
        f"/api/v1/test-suites/{suite_id}/test-cases",
        json={
            "name": "checks eligibility before refund",
            "input": BASE_INPUT,
            "expected_tool_calls": [
                {"tool": "check_order_eligibility", "args_constraints": None, "order_index": 0}
            ],
        },
        headers=_auth_headers(token),
    )

    assert resp.status_code == 201
    assert resp.json()["expected_tool_calls"] == [
        {"tool": "check_order_eligibility", "args_constraints": None, "order_index": 0}
    ]


async def test_create_case_with_rubric(client: AsyncClient) -> None:
    token = await _register_and_login(client, "case5@example.com")
    _, suite_id = await _agent_and_suite(client, token)

    resp = await client.post(
        f"/api/v1/test-suites/{suite_id}/test-cases",
        json={
            "name": "empathetic tone",
            "input": BASE_INPUT,
            "rubric": "The response should be empathetic and professional.",
            "rubric_threshold": 0.8,
        },
        headers=_auth_headers(token),
    )

    assert resp.status_code == 201
    body = resp.json()
    assert body["rubric"] == "The response should be empathetic and professional."
    assert body["rubric_threshold"] == 0.8


async def test_create_case_with_output_schema_only(client: AsyncClient) -> None:
    """output_schema is a real, independently-executed evaluation check
    (Phase 13's output_schema check) and must qualify as ground truth on
    its own, without any other ground-truth field present."""
    token = await _register_and_login(client, "case13@example.com")
    _, suite_id = await _agent_and_suite(client, token)

    schema = {
        "type": "object",
        "required": ["refund_id"],
        "properties": {"refund_id": {"type": "string"}},
    }
    resp = await client.post(
        f"/api/v1/test-suites/{suite_id}/test-cases",
        json={"name": "schema only", "input": BASE_INPUT, "output_schema": schema},
        headers=_auth_headers(token),
    )

    assert resp.status_code == 201
    assert resp.json()["output_schema"] == schema


async def test_create_case_with_no_ground_truth_is_422(client: AsyncClient) -> None:
    token = await _register_and_login(client, "case6@example.com")
    _, suite_id = await _agent_and_suite(client, token)

    resp = await client.post(
        f"/api/v1/test-suites/{suite_id}/test-cases",
        json={"name": "no ground truth", "input": BASE_INPUT},
        headers=_auth_headers(token),
    )

    assert resp.status_code == 422


async def test_create_case_with_only_empty_ground_truth_values_is_422(client: AsyncClient) -> None:
    """Empty containers must not satisfy the ground-truth rule — an
    empty assertions list is not a real deterministic check."""
    token = await _register_and_login(client, "case7@example.com")
    _, suite_id = await _agent_and_suite(client, token)

    resp = await client.post(
        f"/api/v1/test-suites/{suite_id}/test-cases",
        json={
            "name": "empty ground truth",
            "input": BASE_INPUT,
            "assertions": [],
            "expected_tool_calls": [],
            "expected_output": "",
            "reference_context": "",
            "output_schema": {},
            "rubric": "",
        },
        headers=_auth_headers(token),
    )

    assert resp.status_code == 422


async def test_unauthenticated_case_creation_is_rejected(client: AsyncClient) -> None:
    resp = await client.post(
        f"/api/v1/test-suites/{uuid.uuid4()}/test-cases",
        json={"name": "x", "input": {}, "expected_output": "y"},
    )
    assert resp.status_code == 401


# ---- TestCase listing / patch / delete -----------------------------


async def test_list_cases(client: AsyncClient) -> None:
    token = await _register_and_login(client, "case8@example.com")
    _, suite_id = await _agent_and_suite(client, token)
    await client.post(
        f"/api/v1/test-suites/{suite_id}/test-cases",
        json={"name": "case A", "input": BASE_INPUT, "expected_output": "A"},
        headers=_auth_headers(token),
    )
    await client.post(
        f"/api/v1/test-suites/{suite_id}/test-cases",
        json={"name": "case B", "input": BASE_INPUT, "expected_output": "B"},
        headers=_auth_headers(token),
    )

    resp = await client.get(
        f"/api/v1/test-suites/{suite_id}/test-cases", headers=_auth_headers(token)
    )

    assert resp.status_code == 200
    names = {c["name"] for c in resp.json()}
    assert names == {"case A", "case B"}


async def test_patch_case_updates_fields(client: AsyncClient) -> None:
    token = await _register_and_login(client, "case9@example.com")
    _, suite_id = await _agent_and_suite(client, token)
    create_resp = await client.post(
        f"/api/v1/test-suites/{suite_id}/test-cases",
        json={"name": "original", "input": BASE_INPUT, "expected_output": "original answer"},
        headers=_auth_headers(token),
    )
    case_id = create_resp.json()["id"]

    resp = await client.patch(
        f"/api/v1/test-cases/{case_id}",
        json={"name": "renamed", "tags": ["refunds", "priority"]},
        headers=_auth_headers(token),
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "renamed"
    assert body["tags"] == ["refunds", "priority"]
    assert body["expected_output"] == "original answer"  # untouched field preserved


async def test_patch_removing_only_ground_truth_field_is_422(client: AsyncClient) -> None:
    token = await _register_and_login(client, "case10@example.com")
    _, suite_id = await _agent_and_suite(client, token)
    create_resp = await client.post(
        f"/api/v1/test-suites/{suite_id}/test-cases",
        json={"name": "only expected_output", "input": BASE_INPUT, "expected_output": "answer"},
        headers=_auth_headers(token),
    )
    case_id = create_resp.json()["id"]

    resp = await client.patch(
        f"/api/v1/test-cases/{case_id}",
        json={"expected_output": None},
        headers=_auth_headers(token),
    )

    assert resp.status_code == 422

    # And the case must be unchanged in the DB — the rejected patch must
    # not have partially applied.
    get_resp = await client.get(
        f"/api/v1/test-suites/{suite_id}/test-cases", headers=_auth_headers(token)
    )
    assert get_resp.json()[0]["expected_output"] == "answer"


async def test_patch_to_output_schema_only_is_allowed(client: AsyncClient) -> None:
    """Patching a case down to output_schema as its sole ground-truth
    field must succeed — output_schema counts exactly like the other
    five mechanisms."""
    token = await _register_and_login(client, "case14@example.com")
    _, suite_id = await _agent_and_suite(client, token)
    create_resp = await client.post(
        f"/api/v1/test-suites/{suite_id}/test-cases",
        json={"name": "original", "input": BASE_INPUT, "expected_output": "original answer"},
        headers=_auth_headers(token),
    )
    case_id = create_resp.json()["id"]

    schema = {
        "type": "object",
        "required": ["status"],
        "properties": {"status": {"type": "string"}},
    }
    resp = await client.patch(
        f"/api/v1/test-cases/{case_id}",
        json={"expected_output": None, "output_schema": schema},
        headers=_auth_headers(token),
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["expected_output"] is None
    assert body["output_schema"] == schema


async def test_patch_removing_only_output_schema_ground_truth_is_422(client: AsyncClient) -> None:
    token = await _register_and_login(client, "case15@example.com")
    _, suite_id = await _agent_and_suite(client, token)
    schema = {"type": "object", "required": ["status"]}
    create_resp = await client.post(
        f"/api/v1/test-suites/{suite_id}/test-cases",
        json={"name": "only output_schema", "input": BASE_INPUT, "output_schema": schema},
        headers=_auth_headers(token),
    )
    case_id = create_resp.json()["id"]

    resp = await client.patch(
        f"/api/v1/test-cases/{case_id}",
        json={"output_schema": None},
        headers=_auth_headers(token),
    )

    assert resp.status_code == 422

    get_resp = await client.get(
        f"/api/v1/test-suites/{suite_id}/test-cases", headers=_auth_headers(token)
    )
    assert get_resp.json()[0]["output_schema"] == schema


async def test_patch_swapping_ground_truth_field_is_allowed(client: AsyncClient) -> None:
    """Clearing one ground-truth field is fine as long as another one is
    set in the same patch — the rule is about the resulting case, not
    about which specific field carries the truth."""
    token = await _register_and_login(client, "case11@example.com")
    _, suite_id = await _agent_and_suite(client, token)
    create_resp = await client.post(
        f"/api/v1/test-suites/{suite_id}/test-cases",
        json={"name": "swap", "input": BASE_INPUT, "expected_output": "answer"},
        headers=_auth_headers(token),
    )
    case_id = create_resp.json()["id"]

    resp = await client.patch(
        f"/api/v1/test-cases/{case_id}",
        json={"expected_output": None, "rubric": "Was it helpful?"},
        headers=_auth_headers(token),
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["expected_output"] is None
    assert body["rubric"] == "Was it helpful?"


async def test_delete_case(client: AsyncClient) -> None:
    token = await _register_and_login(client, "case12@example.com")
    _, suite_id = await _agent_and_suite(client, token)
    create_resp = await client.post(
        f"/api/v1/test-suites/{suite_id}/test-cases",
        json={"name": "to delete", "input": BASE_INPUT, "expected_output": "x"},
        headers=_auth_headers(token),
    )
    case_id = create_resp.json()["id"]

    resp = await client.delete(f"/api/v1/test-cases/{case_id}", headers=_auth_headers(token))
    assert resp.status_code == 204

    list_resp = await client.get(
        f"/api/v1/test-suites/{suite_id}/test-cases", headers=_auth_headers(token)
    )
    assert list_resp.json() == []


async def test_cross_user_case_access_is_403(client: AsyncClient) -> None:
    token_a = await _register_and_login(client, "case13a@example.com")
    token_b = await _register_and_login(client, "case13b@example.com")
    _, suite_id = await _agent_and_suite(client, token_a)
    create_resp = await client.post(
        f"/api/v1/test-suites/{suite_id}/test-cases",
        json={"name": "private", "input": BASE_INPUT, "expected_output": "x"},
        headers=_auth_headers(token_a),
    )
    case_id = create_resp.json()["id"]

    patch_resp = await client.patch(
        f"/api/v1/test-cases/{case_id}",
        json={"name": "hijacked"},
        headers=_auth_headers(token_b),
    )
    delete_resp = await client.delete(
        f"/api/v1/test-cases/{case_id}", headers=_auth_headers(token_b)
    )
    list_resp = await client.get(
        f"/api/v1/test-suites/{suite_id}/test-cases", headers=_auth_headers(token_b)
    )

    assert patch_resp.status_code == 403
    assert delete_resp.status_code == 403
    assert list_resp.status_code == 403


async def test_case_from_another_suite_is_not_returned_in_listing(client: AsyncClient) -> None:
    token = await _register_and_login(client, "case14@example.com")
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    suite_1 = await _create_suite(client, token, agent_id, name="Suite 1")
    suite_2 = await _create_suite(client, token, agent_id, name="Suite 2")

    await client.post(
        f"/api/v1/test-suites/{suite_1}/test-cases",
        json={"name": "in suite 1", "input": BASE_INPUT, "expected_output": "x"},
        headers=_auth_headers(token),
    )

    resp = await client.get(
        f"/api/v1/test-suites/{suite_2}/test-cases", headers=_auth_headers(token)
    )

    assert resp.status_code == 200
    assert resp.json() == []


async def test_patch_nonexistent_case_is_404(client: AsyncClient) -> None:
    token = await _register_and_login(client, "case15@example.com")

    resp = await client.patch(
        f"/api/v1/test-cases/{uuid.uuid4()}",
        json={"name": "x"},
        headers=_auth_headers(token),
    )

    assert resp.status_code == 404


# ---- Field validation -----------------------------------------------


async def test_invalid_trial_count_is_422(client: AsyncClient) -> None:
    token = await _register_and_login(client, "field1@example.com")
    _, suite_id = await _agent_and_suite(client, token)

    resp = await client.post(
        f"/api/v1/test-suites/{suite_id}/test-cases",
        json={
            "name": "bad trial count",
            "input": BASE_INPUT,
            "expected_output": "x",
            "trial_count": 0,
        },
        headers=_auth_headers(token),
    )

    assert resp.status_code == 422


async def test_invalid_rubric_threshold_is_422(client: AsyncClient) -> None:
    token = await _register_and_login(client, "field2@example.com")
    _, suite_id = await _agent_and_suite(client, token)

    resp = await client.post(
        f"/api/v1/test-suites/{suite_id}/test-cases",
        json={
            "name": "bad rubric threshold",
            "input": BASE_INPUT,
            "rubric": "be nice",
            "rubric_threshold": 1.5,
        },
        headers=_auth_headers(token),
    )

    assert resp.status_code == 422


async def test_invalid_latency_threshold_is_422(client: AsyncClient) -> None:
    token = await _register_and_login(client, "field3@example.com")
    _, suite_id = await _agent_and_suite(client, token)

    resp = await client.post(
        f"/api/v1/test-suites/{suite_id}/test-cases",
        json={
            "name": "bad latency",
            "input": BASE_INPUT,
            "expected_output": "x",
            "latency_threshold_ms": 0,
        },
        headers=_auth_headers(token),
    )

    assert resp.status_code == 422


async def test_assertions_must_be_a_list_of_objects(client: AsyncClient) -> None:
    token = await _register_and_login(client, "field4@example.com")
    _, suite_id = await _agent_and_suite(client, token)

    resp = await client.post(
        f"/api/v1/test-suites/{suite_id}/test-cases",
        json={
            "name": "bad assertions shape",
            "input": BASE_INPUT,
            "assertions": "not a list",
        },
        headers=_auth_headers(token),
    )

    assert resp.status_code == 422


async def test_missing_name_is_422(client: AsyncClient) -> None:
    token = await _register_and_login(client, "field5@example.com")
    _, suite_id = await _agent_and_suite(client, token)

    resp = await client.post(
        f"/api/v1/test-suites/{suite_id}/test-cases",
        json={"input": BASE_INPUT, "expected_output": "x"},
        headers=_auth_headers(token),
    )

    assert resp.status_code == 422


async def test_missing_input_is_422(client: AsyncClient) -> None:
    token = await _register_and_login(client, "field6@example.com")
    _, suite_id = await _agent_and_suite(client, token)

    resp = await client.post(
        f"/api/v1/test-suites/{suite_id}/test-cases",
        json={"name": "no input", "expected_output": "x"},
        headers=_auth_headers(token),
    )

    assert resp.status_code == 422


# ---- No evaluation side effects ----------------------------------


async def test_case_creation_does_not_create_a_legacy_run(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Sanity proxy for "no SuiteRun/TestCaseResult is created" — those
    tables don't exist yet in this phase, so there is nothing to query
    for directly; this confirms Phase 12 has no side effect on the one
    execution-shaped table that does exist (the legacy Run table)."""
    token = await _register_and_login(client, "sideeffect1@example.com")
    _, suite_id = await _agent_and_suite(client, token)

    await client.post(
        f"/api/v1/test-suites/{suite_id}/test-cases",
        json={"name": "no side effects", "input": BASE_INPUT, "expected_output": "x"},
        headers=_auth_headers(token),
    )

    result = await db_session.execute(select(Run))
    assert result.scalars().all() == []
