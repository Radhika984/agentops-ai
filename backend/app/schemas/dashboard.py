from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel


class DashboardStats(BaseModel):
    """The dashboard's real, backend-computed stat tiles. Every field is
    a live count/aggregate at read time — nothing here is cached,
    denormalized, or precomputed, so the dashboard is always correct as
    underlying data changes (see app/services/dashboard_service.py)."""

    total_projects: int
    total_agents: int
    total_suite_runs: int
    release_gate_holds: int


class SuiteRunSummary(BaseModel):
    """One row of the "Recent Suite Runs" table / the account-wide
    "Runs" nav page — denormalized (suite/agent/project/version names
    resolved server-side) so the frontend never has to issue N follow-up
    requests just to render one table."""

    id: uuid.UUID
    suite_id: uuid.UUID
    suite_name: str
    agent_id: uuid.UUID
    agent_name: str
    project_id: uuid.UUID
    project_name: str
    agent_version_id: uuid.UUID
    version_label: str
    status: str
    verdict: str | None
    """A single-word summary verdict for the run as a whole — FAIL if any
    case failed, else INCONCLUSIVE if any case was inconclusive, else
    PASS if the run completed with at least one case, else None (still
    running, or completed with zero cases). Derived from the SuiteRun's
    own already-persisted pass/fail/inconclusive counters — never a new
    computation over TestCaseResults."""
    pass_count: int
    fail_count: int
    inconclusive_count: int
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime


class SuiteRunListResponse(BaseModel):
    items: list[SuiteRunSummary]
    total: int


class VerdictDistribution(BaseModel):
    pass_count: int
    fail_count: int
    inconclusive_count: int
    total: int


class PerformancePoint(BaseModel):
    """One real day's aggregate across every SuiteRun that completed
    that day — computed from SuiteRun's own persisted pass_count/
    fail_count/inconclusive_count columns, grouped by completed_at's
    date. A day with zero completed runs simply is not a point (never a
    fabricated 0%/0 entry — see
    app/services/dashboard_service.py.get_performance_overview())."""

    date: date
    pass_rate: float
    fail_rate: float
    inconclusive_rate: float
    total_results: int


class PerformanceOverview(BaseModel):
    points: list[PerformancePoint]
    range_days: int
    """How many real, available points make up `points` — may be fewer
    than the requested window if the account has less history than
    that; the frontend must render exactly this range honestly, never
    padding with invented dates."""


class TestCaseResultSummary(BaseModel):
    """One row of the account-wide "Evaluation" / "RCA" nav pages —
    denormalized (test case/suite/agent names resolved server-side, same
    reasoning as SuiteRunSummary above) so a list of results never needs
    N follow-up requests just to render."""

    id: uuid.UUID
    suite_run_id: uuid.UUID
    test_case_id: uuid.UUID
    test_case_name: str
    suite_id: uuid.UUID
    suite_name: str
    agent_id: uuid.UUID
    agent_name: str
    verdict: str
    latency_ms: int | None
    error: str | None
    created_at: datetime


class TestCaseResultListResponse(BaseModel):
    items: list[TestCaseResultSummary]
    total: int
