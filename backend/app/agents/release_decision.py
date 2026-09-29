"""Release Decision: the go/no-go call for a completed run.

Per the blueprint ("Hard gates (any Safety block or unresolved
Hallucination flag = automatic Hold); soft gates weighted otherwise...
implemented as a weighted gate function, not a single LLM call,
specifically so the 'why did it ship/not ship' answer is always
reconstructable from logged inputs rather than opaque model reasoning"):
both evaluate_hard_gate() and compute_soft_score() are pure, deterministic
functions over already-persisted run data — no model call anywhere in
this module. That's deliberate, not a missing feature: the blueprint's
own "Common Mistakes" for this phase names "making the Release Decision a
single opaque LLM call" as the mistake to avoid, and its Definition of
Done requires "every Ship/Rollback decision is reconstructable from
logged gate inputs" — an LLM call is neither deterministic nor
reconstructable in that sense.

Every hallucination flag counts toward the hard gate, not just
high-severity ones: this project has no separate "resolved" workflow for
a flag (Phase 7 only ever records/surfaces them), so every flag in
state["flags"] is, by construction, unresolved — matching the blueprint's
exact phrase.

Ship is always a *proposal*: per the per-agent table, Release Decision
requires human approval "Yes, always, for Ship and Rollback" — this
module only ever proposes "ship" when the hard gate passes; the actual
Ship/Rollback outcome is decided by a human via
app/approvals/service.py's decide(), never autonomously here. Hold does
not require approval (it isn't listed in "Yes, always" for Ship/Rollback)
so it's a genuine terminal decision this module can reach on its own.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, cast

from app.agents.state import FlagRecord

# Soft-gate weight multipliers. Kept as named module constants (not
# inlined magic numbers) specifically because the Definition of Done
# requires every decision to be reconstructable — these are what a human
# auditing a past decision would need to see alongside the score itself.
_RETRY_PENALTY = 0.85
_AUTO_FIX_PENALTY = 0.85


@dataclass
class SoftScore:
    value: float
    components: dict[str, float] = field(default_factory=dict)


@dataclass
class ReleaseDecisionResult:
    hard_gate_passed: bool
    proposed_decision: Literal["hold", "ship"]
    soft_score: SoftScore
    reason: str


def evaluate_hard_gate(flags: list[FlagRecord]) -> bool:
    """Returns True if the hard gate PASSES (no Safety block, no
    Hallucination flag present) — False means an automatic Hold,
    regardless of anything else. This is the one function the blueprint's
    required test targets directly: "Release Decision hard-gates
    correctly override any soft-gate score.\""""
    return not any(f["agent"] in ("safety", "hallucination") for f in flags)


def compute_soft_score(
    *, evaluations: list[dict[str, object]], retry_count: int, auto_fix_applied: bool
) -> SoftScore:
    """A deterministic, weighted, auditable confidence score attached to
    a Ship proposal for the human reviewer — it never decides Ship vs.
    Hold on its own (only the hard gate does that); it's informational,
    per the blueprint's "soft gates weighted otherwise" applying only
    once the hard gate has already passed.
    """
    base = float(cast(float, evaluations[-1]["score"])) if evaluations else 0.0
    components = {"base_evaluation_score": base}

    score = base
    if retry_count > 0:
        score *= _RETRY_PENALTY
        components["retry_penalty"] = _RETRY_PENALTY
    if auto_fix_applied:
        score *= _AUTO_FIX_PENALTY
        components["auto_fix_penalty"] = _AUTO_FIX_PENALTY

    return SoftScore(value=round(score, 4), components=components)


def decide_release(
    *,
    flags: list[FlagRecord],
    evaluations: list[dict[str, object]],
    retry_count: int,
    auto_fix_applied: bool,
) -> ReleaseDecisionResult:
    hard_gate_passed = evaluate_hard_gate(flags)
    soft_score = compute_soft_score(
        evaluations=evaluations, retry_count=retry_count, auto_fix_applied=auto_fix_applied
    )

    if not hard_gate_passed:
        blocking = sorted({f["agent"] for f in flags if f["agent"] in ("safety", "hallucination")})
        return ReleaseDecisionResult(
            hard_gate_passed=False,
            proposed_decision="hold",
            soft_score=soft_score,
            reason=f"Hard gate failed: unresolved flag(s) from {', '.join(blocking)}.",
        )

    return ReleaseDecisionResult(
        hard_gate_passed=True,
        proposed_decision="ship",
        soft_score=soft_score,
        reason=f"Hard gate passed; soft score {soft_score.value:.2f}. Awaiting human approval.",
    )
