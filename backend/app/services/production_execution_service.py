"""Phase 20 — Post-release execution ingestion, monitoring, and the
production-failure -> regression-candidate feedback loop.

    External/released agent runs somewhere else
        -> caller POSTs the execution evidence here (never re-executed
           by AgentOps — see ingest()'s own docstring)
        -> app.evaluation.production.evaluate_production_execution()
           (Phase 13 evaluate() + Phase 15 Safety/Grounding, reused
           unchanged)
        -> persisted as one ProductionExecution row
        -> monitoring metrics computed on read from persisted rows
        -> a meaningful failure may become a "candidate" TestCase
           (app.services.test_suite_service.TestSuiteService, reused
           unchanged) — never active until a human accepts it

No second evaluator, no second RCA system (app.rca.evidence's own
classify_deterministic() is reused verbatim for the RCA categories
exposed on a failed execution), no second approval system (a candidate
TestCase's own `status` field, plus the accept endpoint, is the entire
human-control mechanism — see app/models/test_case.py).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.execution import AgentExecution
from app.ai.client import owner_call_context
from app.core.exceptions import NotFoundError
from app.evaluation.production import evaluate_production_execution
from app.models.agent_version import AgentVersion
from app.models.production_execution import ProductionExecution
from app.models.test_case import TestCase
from app.rca.evidence import (
    classify_deterministic,
    find_forbidden_tool_called,
    find_missing_required_tool_calls,
    find_safety_flags,
    find_schema_failures,
)
from app.repositories.agent_version_repository import AgentVersionRepository
from app.repositories.production_execution_repository import ProductionExecutionRepository
from app.schemas.production_execution import (
    ProductionExecutionCreate,
    ProductionMonitoringSummary,
    RegressionCandidateCreate,
)
from app.services.agent_service import AgentService
from app.services.test_suite_service import TestSuiteService


class ProductionExecutionService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._agents = AgentService(session)
        self._versions = AgentVersionRepository(session)
        self._executions = ProductionExecutionRepository(session)
        self._suites = TestSuiteService(session)

    async def _get_owned_version(
        self, *, version_id: uuid.UUID, owner_id: uuid.UUID
    ) -> tuple[Any, AgentVersion]:
        # Deliberately not AgentService.get_version() — that requires
        # agent_id up front, which the Phase 20 route (matching the
        # locked API sketch, /agent-versions/{version_id}/...) never
        # has. Ownership is still verified exactly the same way, via the
        # same real AgentService.get_agent() (Phase 11, unmodified).
        version = await self._versions.get_by_id(version_id)
        if version is None:
            raise NotFoundError(f"Agent version not found: {version_id}")
        agent = await self._agents.get_agent(agent_id=version.agent_id, owner_id=owner_id)
        return agent, version

    async def ingest(
        self, *, version_id: uuid.UUID, owner_id: uuid.UUID, payload: ProductionExecutionCreate
    ) -> ProductionExecution:
        """Persists (idempotently) and evaluates one piece of post
        -release execution evidence. Never invokes an AgentAdapter —
        `payload` already describes a completed execution that happened
        somewhere else; this only ever reads and records it."""
        agent, version = await self._get_owned_version(version_id=version_id, owner_id=owner_id)

        existing = await self._executions.get_by_agent_version_and_external_id(
            agent_version_id=version_id, external_execution_id=payload.external_execution_id
        )
        if existing is not None:
            # Idempotent (§3): the same evidence was already ingested
            # and evaluated — return that row as-is, never re-evaluate,
            # never create a second one.
            return existing

        now = datetime.now(UTC)
        execution = AgentExecution(
            request_id=uuid.uuid4(),
            input=payload.input,
            output=payload.actual_output,
            status="error" if payload.error else "ok",
            error=payload.error,
            latency_ms=payload.latency_ms,
            started_at=now,
            finished_at=now,
            tool_calls=payload.tool_calls,
            trace=payload.trace,
        )
        with owner_call_context(owner_id):
            result = await evaluate_production_execution(
                agent=agent,
                agent_version=version,
                execution=execution,
                reference_context=payload.reference_context,
            )

        row = await self._executions.create(
            agent_version_id=version_id,
            external_execution_id=payload.external_execution_id,
            input=payload.input,
            actual_output=payload.actual_output,
            tool_calls=[tc.model_dump(mode="json") for tc in payload.tool_calls],
            latency_ms=payload.latency_ms,
            error=payload.error,
            reference_context=payload.reference_context,
            trace=[span.model_dump(mode="json") for span in payload.trace]
            if payload.trace is not None
            else None,
            execution_metadata=payload.metadata,
            verdict=result.verdict,
            checks=[check.model_dump(mode="json") for check in result.checks],
        )
        await self._session.commit()
        return row

    async def get_execution(
        self, *, version_id: uuid.UUID, execution_id: uuid.UUID, owner_id: uuid.UUID
    ) -> ProductionExecution:
        await self._get_owned_version(version_id=version_id, owner_id=owner_id)
        execution = await self._executions.get_by_id(execution_id)
        if execution is None or execution.agent_version_id != version_id:
            raise NotFoundError(f"Production execution not found: {execution_id}")
        return execution

    async def list_executions(
        self, *, version_id: uuid.UUID, owner_id: uuid.UUID
    ) -> list[ProductionExecution]:
        await self._get_owned_version(version_id=version_id, owner_id=owner_id)
        return await self._executions.list_by_agent_version(version_id)

    async def get_monitoring_summary(
        self, *, version_id: uuid.UUID, owner_id: uuid.UUID
    ) -> ProductionMonitoringSummary:
        """Every field computed from persisted ProductionExecution rows
        only — no fabricated metric (§5). Matches the same "fetch and
        aggregate in memory" pattern app/services/release_gate_service.py
        and app/services/regression_service.py already use, over the
        (in this system's scale) modest per-agent-version execution
        history."""
        await self._get_owned_version(version_id=version_id, owner_id=owner_id)
        executions = await self._executions.list_by_agent_version(version_id, limit=10_000)

        total = len(executions)
        pass_count = sum(1 for e in executions if e.verdict == "PASS")
        fail_count = sum(1 for e in executions if e.verdict == "FAIL")
        inconclusive_count = sum(1 for e in executions if e.verdict == "INCONCLUSIVE")

        latencies = [e.latency_ms for e in executions if e.latency_ms is not None]
        average_latency_ms = sum(latencies) / len(latencies) if latencies else None

        latency_violations = 0
        safety_failures = 0
        forbidden_tool = 0
        missing_tool = 0
        schema_failures = 0
        grounding_evaluated = 0
        grounding_failures = 0
        for e in executions:
            checks = e.checks
            if any(c.get("check_type") == "latency" and c.get("status") == "fail" for c in checks):
                latency_violations += 1
            safety_failures += len(find_safety_flags(checks))
            forbidden_tool += len(find_forbidden_tool_called(checks))
            missing_tool += len(find_missing_required_tool_calls(checks))
            schema_failures += len(find_schema_failures(checks))
            grounding_check = next((c for c in checks if c.get("check_type") == "grounding"), None)
            if grounding_check is not None and grounding_check.get("status") != "skipped":
                grounding_evaluated += 1
                if grounding_check.get("status") == "fail":
                    grounding_failures += 1

        return ProductionMonitoringSummary(
            agent_version_id=version_id,
            total_executions=total,
            pass_count=pass_count,
            fail_count=fail_count,
            inconclusive_count=inconclusive_count,
            failure_rate=(fail_count / total) if total else None,
            average_latency_ms=average_latency_ms,
            latency_threshold_violations=latency_violations,
            safety_failure_count=safety_failures,
            forbidden_tool_count=forbidden_tool,
            missing_required_tool_count=missing_tool,
            schema_failure_count=schema_failures,
            grounding_evaluated_count=grounding_evaluated,
            grounding_failure_count=grounding_failures,
        )

    async def get_rca_categories(
        self, *, version_id: uuid.UUID, execution_id: uuid.UUID, owner_id: uuid.UUID
    ) -> list[dict[str, Any]]:
        """The deterministic RCA whitelist (app/rca/evidence.py, Phase
        18, reused verbatim) applied to one execution's own persisted
        checks — no LLM hypothesis tier for production executions (no
        rubric concept exists for one; §16 "primarily deterministic")."""
        execution = await self.get_execution(
            version_id=version_id, execution_id=execution_id, owner_id=owner_id
        )
        findings = classify_deterministic(execution.checks)
        return [
            {"category": f.category, "check_type": f.check_type, "detail": f.detail}
            for f in findings
        ]

    async def create_regression_candidate(
        self, *, execution_id: uuid.UUID, owner_id: uuid.UUID, payload: RegressionCandidateCreate
    ) -> TestCase:
        """§7/§8: proposes a candidate regression TestCase from a real
        production execution's evidence — never auto-applied, never
        capable of touching Agent/AgentVersion/credentials (this method
        only ever calls TestSuiteService.create_candidate_case(), which
        only ever writes a plain TestCase row)."""
        execution = await self._executions.get_by_id(execution_id)
        if execution is None:
            raise NotFoundError(f"Production execution not found: {execution_id}")
        # Ownership via the execution's own AgentVersion -> Agent -> Project.
        await self._get_owned_version(version_id=execution.agent_version_id, owner_id=owner_id)

        fields: dict[str, Any] = {
            "name": payload.name
            or f"Regression candidate from execution {execution.external_execution_id}",
            "input": payload.input if payload.input is not None else execution.input,
            "reference_context": payload.reference_context,
            "expected_output": payload.expected_output,
            "assertions": payload.assertions,
            "expected_tool_calls": payload.expected_tool_calls,
            "rubric": payload.rubric,
            "expected_behavior": payload.expected_behavior,
            "forbidden_behavior": payload.forbidden_behavior,
            "allowed_tools": payload.allowed_tools,
            "output_schema": payload.output_schema,
            "latency_threshold_ms": payload.latency_threshold_ms,
        }

        return await self._suites.create_candidate_case(
            suite_id=payload.suite_id,
            owner_id=owner_id,
            fields=fields,
            source_execution_id=execution.id,
        )
