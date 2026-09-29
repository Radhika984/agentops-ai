"""Phase 18 — Release Gate response schemas.

Computed on read by app/services/release_gate_service.py — nothing here
is a ReleaseDecision/GateResult table; the response is fully
reconstructable from persisted SuiteRun/TestCaseResult evidence on every
request (§23, §36).
"""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel

ReleaseDecisionValue = Literal["pass", "hold"]


class HardGateReasonRead(BaseModel):
    category: str
    test_case_id: uuid.UUID
    check_type: str
    detail: str


class RegressionSoftInput(BaseModel):
    available: bool
    regression_count: int | None = None
    improvement_count: int | None = None
    pass_rate_delta: float | None = None


class ReleaseDecisionResponse(BaseModel):
    suite_run_id: uuid.UUID
    decision: ReleaseDecisionValue
    hard_gate_passed: bool
    hard_gate_reasons: list[HardGateReasonRead]
    approval_required: bool

    total_cases: int
    pass_count: int
    fail_count: int
    inconclusive_count: int
    pass_rate: float | None
    inconclusive_rate: float | None

    safety_flag_count: int
    forbidden_tool_count: int
    missing_required_tool_count: int
    schema_failure_count: int
    rubric_case_count: int

    regression: RegressionSoftInput

    soft_score: float
    soft_score_components: dict[str, float]

    reason: str
