"""Phase 20 — Post-release execution evaluation.

Reuses Phase 13's evaluate() and Phase 15's Safety/Grounding UNCHANGED —
this module is the same "composition layer" app/services/suite_runner.py
already is for Suite Runner executions, adapted for a bare, ingested
production execution that has no TestCase of its own.

A production execution has no per-test ground-truth contract (the
ingestion payload never carries expected_output/assertions/rubric — see
app/schemas/production_execution.py). The one contract source that DOES
apply is the owning Agent's own `default_*` evaluation-contract fields
(Phase 11) — exactly what they were added for (models/agent.py: "fields
live as defaults on Agent and overridable per TestCase"). When an Agent
has no defaults configured for a given dimension, that check is simply
never run — never fabricated, matching the locked §4 "do not fabricate
checks when required evidence/contract is absent" rule. Correctness
(expected_output/assertions) has no Agent-level equivalent at all and is
therefore never evaluated for a production execution — only tool
trajectory, schema, latency (from Agent defaults), safety (always, from
observability_level), and grounding (only when reference_context is
supplied) are ever meaningfully computable here.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.adapters.execution import AgentExecution
from app.evaluation.checks.grounding import evaluate_grounding
from app.evaluation.checks.safety import evaluate_output_safety, evaluate_tool_call_safety
from app.evaluation.engine import evaluate
from app.evaluation.models import Check, EvaluationInput, OverallVerdict
from app.models.agent import Agent
from app.models.agent_version import AgentVersion

# Identical mapping to app/services/suite_runner.py's own _VERDICT_MAP —
# not imported (that name is private to suite_runner.py's module scope)
# but the same three-value lookup, for the same reason: REQUIRES_LLM
# means nothing deterministic was applicable (no Agent defaults
# configured for anything relevant) and Phase 20 never invokes the LLM
# judge for production executions (no rubric concept exists for one), so
# it is reported as INCONCLUSIVE, never fabricated as PASS or FAIL.
_VERDICT_MAP: dict[OverallVerdict, str] = {
    OverallVerdict.PASS: "PASS",
    OverallVerdict.FAIL: "FAIL",
    OverallVerdict.REQUIRES_LLM: "INCONCLUSIVE",
}


@dataclass(frozen=True)
class ProductionEvaluationResult:
    verdict: str
    checks: list[Check]


def _evaluation_input_from_agent_defaults(agent: Agent) -> EvaluationInput:
    expected_tool_calls = (
        [{"tool": name, "required": True} for name in agent.default_required_tools]
        if agent.default_required_tools
        else None
    )
    return EvaluationInput(
        expected_output=None,
        assertions=None,
        reference_context=None,  # supplied separately, per-execution, not from Agent defaults
        expected_tool_calls=expected_tool_calls,
        allowed_tools=agent.default_allowed_tools,
        output_schema=agent.default_output_schema,
        latency_threshold_ms=agent.default_latency_threshold_ms,
        rubric=None,
    )


async def evaluate_production_execution(
    *,
    agent: Agent,
    agent_version: AgentVersion,
    execution: AgentExecution,
    reference_context: str | None,
) -> ProductionEvaluationResult:
    """The Phase 20 equivalent of app/services/suite_runner.py's
    `_evaluate_trial()` — same composition, same reused functions, for
    one already-completed production execution instead of a fresh
    adapter invocation. Never invokes an adapter (execution is already
    given) and never invokes the LLM judge (no rubric exists for a
    production execution)."""
    evaluation_input = _evaluation_input_from_agent_defaults(agent)
    eval_result = evaluate(evaluation_input, execution)
    verdict = _VERDICT_MAP[eval_result.verdict]

    safety_checks = await evaluate_tool_call_safety(
        execution.tool_calls, agent_version.observability_level
    )
    output_safety_check = await evaluate_output_safety(execution.output)
    grounding_check = await evaluate_grounding(reference_context, execution.output)

    all_checks: list[Check] = [
        *eval_result.checks,
        *safety_checks,
        output_safety_check,
        grounding_check,
    ]
    return ProductionEvaluationResult(verdict=verdict, checks=all_checks)
