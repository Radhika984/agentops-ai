"""Phase 18 — Root Cause Analysis response schemas.

Computed on read by app/rca/service.py — nothing here is persisted (no
RCAResult table; see that module's own docstring). No confidence field:
the existing RCA mechanism (app/agents/root_cause_analysis.py's
`RCAResult` / `RootCauseHypothesis`) has never defined one, and the
locked Phase 18 brief explicitly forbids inventing one.
"""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel

RCATier = Literal["deterministic", "llm_hypothesis", "insufficient_evidence", "not_applicable"]


class RCAEvidenceItem(BaseModel):
    check_type: str
    status: str | None = None
    detail: str


class RCARegressionEvidence(BaseModel):
    baseline_verdict: str
    candidate_verdict: str
    classification: str
    output_changed: bool
    tool_changed: bool
    safety_changed: bool
    grounding_changed: bool


class RCAResponse(BaseModel):
    test_case_id: uuid.UUID
    suite_run_id: uuid.UUID
    verdict: str
    tier: RCATier
    root_cause_category: str | None
    all_matched_categories: list[str]
    explanation: str
    evidence_references: list[RCAEvidenceItem]
    related_check_types: list[str]
    trace_span_ids: list[str]
    regression: RCARegressionEvidence | None
