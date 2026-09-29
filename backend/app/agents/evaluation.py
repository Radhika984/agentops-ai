"""Evaluation node: scores the current plan against a cheap rubric.

Per the blueprint's stated decision logic ("Rule-based checks first
(cheap), LLM-as-judge only if rules are inconclusive"), this is a pure
rule-based check — no model call. A task counts as substantive if it's
more than a few characters (rules out empty/placeholder strings); the
score is the fraction of substantive tasks in the plan.
"""

from __future__ import annotations

from app.agents.state import AgentState

_MIN_TASK_LENGTH = 3
_PASS_THRESHOLD = 0.8


async def evaluation_node(state: AgentState) -> AgentState:
    plan = state["plan"]
    substantive = [task for task in plan if len(task.strip()) > _MIN_TASK_LENGTH]
    score = len(substantive) / len(plan) if plan else 0.0
    passed = score >= _PASS_THRESHOLD

    new_evaluation: dict[str, object] = {"score": score, "passed": passed}
    evaluations = [*state["evaluations"], new_evaluation]

    return {
        **state,
        "evaluations": evaluations,
        "status": "evaluating",
    }
