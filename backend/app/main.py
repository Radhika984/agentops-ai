"""Application entrypoint.

Wires together the FastAPI app and registers the v1 routers.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.ai import cache as ai_cache
from app.api.v1.activity import router as activity_router
from app.api.v1.agent_adapter import router as agent_adapter_router
from app.api.v1.agents import router as agents_router
from app.api.v1.api_keys import router as api_keys_router
from app.api.v1.approvals import router as approvals_router
from app.api.v1.ask import router as ask_router
from app.api.v1.auth import router as auth_router
from app.api.v1.autofix import router as autofix_router
from app.api.v1.cost import router as cost_router
from app.api.v1.dashboard import router as dashboard_router
from app.api.v1.health import router as health_router
from app.api.v1.production_executions import router as production_executions_router
from app.api.v1.projects import router as projects_router
from app.api.v1.rca import router as rca_router
from app.api.v1.regression import router as regression_router
from app.api.v1.release import router as release_router
from app.api.v1.results import router as results_router
from app.api.v1.runs import router as runs_router
from app.api.v1.search import router as search_router
from app.api.v1.suite_runs import router as suite_runs_router
from app.api.v1.test_suites import router as test_suites_router
from app.tools import mcp_client


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None]:
    yield
    # Phase 5's MCP servers are spawned as subprocesses and cached for
    # reuse (see tools/mcp_client.py); closing them explicitly on shutdown
    # avoids leaving orphaned subprocesses behind, and avoids their async
    # cleanup running with no event loop left to run it in.
    await mcp_client.shutdown()
    # Phase 8: same reasoning for the cached Redis client (see
    # ai/cache.py's close()).
    await ai_cache.close()


app = FastAPI(title="AgentOps AI Platform", lifespan=_lifespan)

# Phase 0: the frontend calls the backend from the browser (client-side
# fetch), a different origin, so CORS must allow it explicitly.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router, prefix="/api/v1")
app.include_router(auth_router, prefix="/api/v1")
app.include_router(projects_router, prefix="/api/v1")
app.include_router(ask_router, prefix="/api/v1")
app.include_router(runs_router, prefix="/api/v1")
app.include_router(cost_router, prefix="/api/v1")
app.include_router(approvals_router, prefix="/api/v1")
# Phase 10: the Agent Adapter layer's test-invoke endpoint — see
# app/api/v1/agent_adapter.py's module docstring for why it is stateless
# (no Agent Registry exists yet; that's Phase 11).
app.include_router(agent_adapter_router, prefix="/api/v1")
# Phase 11: the Agent Registry (Agent, AgentVersion, baseline promotion,
# and the persisted-AgentVersion test-invoke endpoint).
app.include_router(agents_router, prefix="/api/v1")
# Phase 12: the Evaluation Contract + Test Cases (TestSuite, TestCase) —
# storage/validation only, no evaluation execution.
app.include_router(test_suites_router, prefix="/api/v1")
# Phase 14: the Suite Runner — SuiteRun creation/polling + the
# background execution that connects the adapter (Phase 10) to the
# Assertion Engine (Phase 13) and persists TestCaseResults.
app.include_router(suite_runs_router, prefix="/api/v1")
# Phase 17: Regression Comparison — baseline SuiteRun vs. candidate
# SuiteRun of the same TestSuite, computed entirely on read (nothing
# here is persisted; see app/services/regression_service.py).
app.include_router(regression_router, prefix="/api/v1")
# Phase 18: Root Cause Analysis (per TestCaseResult, computed on read) and
# the deterministic Release Gate (per SuiteRun) — see
# app/services/rca_service.py and app/services/release_gate_service.py.
app.include_router(rca_router, prefix="/api/v1")
app.include_router(release_router, prefix="/api/v1")
# Phase 19: AutoFix proposal creation — approving/applying reuses the
# existing Approval system (POST /approvals/{id}/decide), not a new
# endpoint; see app/services/autofix_service.py.
app.include_router(autofix_router, prefix="/api/v1")
# Phase 20: post-release execution ingestion + monitoring — evaluates
# already-completed external executions using the existing Phase 13/15
# mechanisms (see app/services/production_execution_service.py); never
# executes an adapter itself.
app.include_router(production_executions_router, prefix="/api/v1")
# Home dashboard: real, owner-scoped aggregation reads only (no writes) —
# see app/services/dashboard_service.py.
app.include_router(dashboard_router, prefix="/api/v1")
# Recent Activity: real, persisted product events — see
# app/services/activity_service.py.
app.include_router(activity_router, prefix="/api/v1")
# Settings > API Keys: issue/list/revoke programmatic API keys — see
# app/services/api_key_service.py. Using one to authenticate a request is
# handled by app/api/v1/deps.py's get_current_user_or_api_key(), wired
# into app/api/v1/suite_runs.py's create/poll/results routes.
app.include_router(api_keys_router, prefix="/api/v1")
# Global search across a user's own Projects/Agents/TestSuites/TestCases/
# AgentVersions — see app/services/search_service.py.
app.include_router(search_router, prefix="/api/v1")
# Account-wide "Evaluation"/"RCA" nav pages' TestCaseResult listing — see
# app/services/suite_run_service.py's list_all_results_for_owner().
app.include_router(results_router, prefix="/api/v1")
