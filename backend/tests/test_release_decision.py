"""Phase 9 agents/release_decision.py tests.

Pure, deterministic functions — no mocking needed, no DB, no model call.
The required blueprint test lives here: "test that Release Decision hard
-gates correctly override any soft-gate score (e.g., a single Safety
block always holds, regardless of other scores)."
"""

from __future__ import annotations

from app.agents.release_decision import compute_soft_score, decide_release, evaluate_hard_gate
from app.agents.state import FlagRecord


def _flag(agent: str) -> FlagRecord:
    return FlagRecord(agent=agent, type="t", severity="high", details="d")


def test_hard_gate_passes_with_no_flags() -> None:
    assert evaluate_hard_gate([]) is True


def test_hard_gate_fails_on_a_safety_flag() -> None:
    assert evaluate_hard_gate([_flag("safety")]) is False


def test_hard_gate_fails_on_a_hallucination_flag() -> None:
    assert evaluate_hard_gate([_flag("hallucination")]) is False


def test_hard_gate_ignores_unrelated_agents() -> None:
    # A hypothetical flag from some other agent shouldn't trip the gate —
    # only Safety/Hallucination are named in the blueprint's hard-gate rule.
    assert evaluate_hard_gate([_flag("monitoring")]) is True


def test_compute_soft_score_uses_the_latest_evaluation() -> None:
    score = compute_soft_score(
        evaluations=[{"score": 0.5, "passed": False}, {"score": 1.0, "passed": True}],
        retry_count=0,
        auto_fix_applied=False,
    )
    assert score.value == 1.0
    assert score.components == {"base_evaluation_score": 1.0}


def test_compute_soft_score_penalizes_retries_and_auto_fix() -> None:
    score = compute_soft_score(evaluations=[{"score": 1.0}], retry_count=1, auto_fix_applied=True)

    assert score.value == round(1.0 * 0.85 * 0.85, 4)
    assert "retry_penalty" in score.components
    assert "auto_fix_penalty" in score.components


def test_compute_soft_score_with_no_evaluations() -> None:
    score = compute_soft_score(evaluations=[], retry_count=0, auto_fix_applied=False)
    assert score.value == 0.0


def test_decide_release_hard_gate_overrides_a_perfect_soft_score() -> None:
    """The exact scenario the blueprint's required test names: a single
    Safety block always holds, regardless of other scores — even a
    perfect evaluation score with zero retries and no auto-fix."""
    result = decide_release(
        flags=[_flag("safety")],
        evaluations=[{"score": 1.0, "passed": True}],
        retry_count=0,
        auto_fix_applied=False,
    )

    assert result.hard_gate_passed is False
    assert result.proposed_decision == "hold"
    # The soft score is still computed and logged (auditability), it just
    # never overrides the hold.
    assert result.soft_score.value == 1.0


def test_decide_release_proposes_ship_when_hard_gate_passes() -> None:
    result = decide_release(
        flags=[],
        evaluations=[{"score": 0.9, "passed": True}],
        retry_count=0,
        auto_fix_applied=False,
    )

    assert result.hard_gate_passed is True
    assert result.proposed_decision == "ship"


def test_decide_release_holds_even_with_a_low_severity_hallucination_flag() -> None:
    low_severity_flag = FlagRecord(
        agent="hallucination", type="unsupported_claim", severity="low", details="x"
    )
    result = decide_release(
        flags=[low_severity_flag],
        evaluations=[{"score": 1.0, "passed": True}],
        retry_count=0,
        auto_fix_applied=False,
    )

    assert result.proposed_decision == "hold"
