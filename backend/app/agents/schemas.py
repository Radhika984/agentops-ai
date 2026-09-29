from __future__ import annotations

from pydantic import BaseModel, Field


class PlanOutput(BaseModel):
    tasks: list[str] = Field(min_length=1)


class SafetyClassification(BaseModel):
    """Phase 7: Safety's LLM-fallback classifier output — only used for
    review_patterns matches the deterministic policy engine can't decide
    on its own (see agents/safety.py)."""

    allowed: bool
    reason: str


class HallucinationCheck(BaseModel):
    """Phase 7: Hallucination's entailment-check output. Each entry in
    `unsupported_claims` is a task from the plan that the source context
    does not actually support — see agents/hallucination.py."""

    unsupported_claims: list[str] = Field(default_factory=list)


class RootCauseHypothesis(BaseModel):
    """Phase 9: Root Cause Analysis's LLM-fallback output — only produced
    when the failure doesn't match Auto Fix's deterministic whitelist
    (see agents/root_cause_analysis.py). One short, human-readable
    hypothesis; RCA never acts on this itself, it only feeds a human's
    review, so there is nothing else to validate here."""

    hypothesis: str = Field(min_length=1, max_length=500)


class AutoFixPatch(BaseModel):
    """Phase 9: Auto Fix's constrained patch-generation output — only
    called after the deterministic whitelist has already decided a fix
    applies (see agents/auto_fix.py). Constrained to exactly the one
    whitelisted transformation (append one short task to a too-short
    plan); the model phrases the task, it doesn't decide whether to
    patch at all."""

    additional_task: str = Field(min_length=1, max_length=200)
