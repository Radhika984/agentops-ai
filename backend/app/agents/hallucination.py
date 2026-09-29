"""Hallucination: detects unsupported claims in the plan.

Per the blueprint ("Compares claims against retrieved context (NLI-style
entailment check); flags anything unsupported"): checks the Planner's
generated task list against the same source context that was available
when it was produced (the goal, Phase 5's search result, Phase 6's
retrieved memory) — a grounding check against what was actually given,
not the model re-reviewing its own output's confidence.

Runs between Evaluation and Verification in the graph (see graph.py), per
"every generated artifact passes through Hallucination before
Verification." Flags are recorded but — per the blueprint's Part 1 agent
table ("No, but flags block Release Decision") — do not themselves fail
verification here: Release Decision is a Phase 9 agent that doesn't exist
yet, so for now flags are surfaced (state + the flags table) rather than
enforced. Verification's own check (agents/verification.py) is unrelated
and unaffected.
"""

from __future__ import annotations

from pathlib import Path

from app.agents.schemas import HallucinationCheck
from app.agents.state import AgentState, FlagRecord
from app.ai.client import AIClientError, call_model

_PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "hallucination_check.txt"


async def hallucination_node(state: AgentState) -> AgentState:
    plan = state["plan"]
    if not plan:
        return {**state, "status": "checking_hallucination"}

    context_parts = [f"Goal: {state['goal']}"]
    for tc in state["tool_calls"]:
        if tc["tool_name"] == "web_search" and tc["ok"]:
            context_parts.append(f"Search result: {tc['output']}")
    context_parts.extend(f"Similar past run: {m}" for m in state["retrieved_memory"])
    source_context = "\n".join(context_parts)

    prompt = _PROMPT_PATH.read_text(encoding="utf-8").format(
        source_context=source_context,
        plan="\n".join(f"- {task}" for task in plan),
    )

    try:
        # Phase 8: "judgment" group (a claims-vs-context check, not
        # open-ended generation) and cacheable=True — the same plan
        # checked against the same source context deserves the same
        # verdict every time (see app/ai/cache.py's docstring).
        result = await call_model(
            prompt, HallucinationCheck, agent="hallucination", model_group="judgment",
            cacheable=True,
        )
    except AIClientError:
        # Fails open (no flags), not closed — an unreviewable check must
        # not itself block verification, since it doesn't gate anything
        # yet (see module docstring); it would only ever suppress a flag
        # that a human/Release Decision agent might have wanted to see.
        return {**state, "status": "checking_hallucination"}

    new_flags: list[FlagRecord] = [
        FlagRecord(
            agent="hallucination",
            type="unsupported_claim",
            severity="medium",
            details=claim,
        )
        for claim in result.unsupported_claims
    ]

    return {
        **state,
        "status": "checking_hallucination",
        "flags": [*state["flags"], *new_flags],
    }
