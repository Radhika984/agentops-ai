"""Phase 17 — Regression Comparison response schemas.

Nothing here is backed by an ORM model (no `from_attributes`) and none of
it is ever persisted: every field is computed on read by
app/services/regression_service.py from two already-persisted SuiteRuns'
TestCaseResults, per the locked Phase 17 brief's explicit "computed on
read, never stored" requirement. See app/regression/diff.py for the pure
functions that build these.
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel

VerdictClassification = Literal["regression", "improvement", "unchanged", "changed"]


class OutputDiff(BaseModel):
    baseline_output: Any = None
    candidate_output: Any = None
    output_changed: bool


class ToolTrajectoryDiff(BaseModel):
    baseline_tools: list[str]
    candidate_tools: list[str]
    added_tools: list[str]
    removed_tools: list[str]
    order_changed: bool
    # check_types (from Phase 13's tool_trajectory.py `tool_call[i]:tool`
    # checks) whose PASS/FAIL status flipped between baseline and
    # candidate — the deterministic signal that the same tool was called
    # with differently-satisfying arguments (see diff.py's own docstring
    # for why raw argument values are not part of the persisted evidence).
    argument_changes: list[str]
    changed: bool


class LatencyDiff(BaseModel):
    baseline_latency_ms: int | None
    candidate_latency_ms: int | None
    delta_ms: int | None
    available: bool
    changed: bool


class SafetyDiff(BaseModel):
    baseline_status: str
    candidate_status: str
    newly_unsafe: list[str]
    resolved: list[str]
    changed: bool


class GroundingDiff(BaseModel):
    baseline_status: str | None
    candidate_status: str | None
    changed: bool


class TrialSummary(BaseModel):
    baseline_trial_verdicts: list[str]
    candidate_trial_verdicts: list[str]


class CaseComparison(BaseModel):
    test_case_id: uuid.UUID
    classification: VerdictClassification
    baseline_verdict: str
    candidate_verdict: str
    output_diff: OutputDiff
    tool_trajectory_diff: ToolTrajectoryDiff
    latency_diff: LatencyDiff
    safety_diff: SafetyDiff
    grounding_diff: GroundingDiff
    trial_summary: TrialSummary


class RegressionSummary(BaseModel):
    total_matched_cases: int
    regressions: int
    improvements: int
    unchanged: int
    # Verdict differs but is not classified as a regression or
    # improvement per the locked §8/§9 definitions (FAIL<->INCONCLUSIVE)
    # — exposed as its own factual bucket rather than being silently
    # folded into "unchanged" (the verdict did change) or "regressions"/
    # "improvements" (the locked brief explicitly forbids both).
    changed: int
    new_cases: int
    missing_cases: int

    baseline_pass_count: int
    candidate_pass_count: int
    baseline_fail_count: int
    candidate_fail_count: int
    baseline_inconclusive_count: int
    candidate_inconclusive_count: int
    baseline_skipped_count: int
    candidate_skipped_count: int

    baseline_pass_rate: float | None
    candidate_pass_rate: float | None
    pass_rate_delta: float | None

    baseline_inconclusive_rate: float | None
    candidate_inconclusive_rate: float | None
    inconclusive_rate_delta: float | None

    safety_changes: int
    grounding_changes: int
    latency_changes: int
    tool_changes: int


class RegressionResponse(BaseModel):
    suite_id: uuid.UUID
    baseline_suite_run_id: uuid.UUID
    baseline_agent_version_id: uuid.UUID
    candidate_suite_run_id: uuid.UUID
    candidate_agent_version_id: uuid.UUID
    summary: RegressionSummary
    cases: list[CaseComparison]
    new_test_case_ids: list[uuid.UUID]
    missing_test_case_ids: list[uuid.UUID]
