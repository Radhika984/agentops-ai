"""Compiles the Planner -> Evaluation -> Hallucination -> Verification
graph.

Verification's conditional edge is the retry loop the blueprint requires
("a bounded retry loop from Verification back to Planner on failure"):
- verification passed -> succeed -> END
- verification failed, retries remain -> retry (increments the bounded
  counter in state) -> back to planner
- verification failed, retries exhausted -> fail -> END

The counter lives in state (AgentState.retry_count), checked in the
conditional edge function, exactly matching the blueprint's stated
mechanism for avoiding unbounded loops — never plain recursion.

Phase 7: Hallucination sits between Evaluation and Verification, per "every
generated artifact passes through Hallucination before Verification."
Every node (including the retry/succeed/fail terminal nodes) is wrapped in
an OTel span here, in one place — per Phase 7's own "Common Mistakes"
("tracing added as an afterthought instead of wrapping every node
uniformly"), rather than each node file remembering to instrument itself.
Each wrapper is a literal `async def`, not a generically-typed closure
returned from a helper — LangGraph's `add_node()` type stubs use a complex
generic overload set keyed off a concrete TypedDict signature, which a
`Callable[[AgentState], ...]`-typed value doesn't resolve against cleanly
under mypy, even though it's correct at runtime.
"""

from __future__ import annotations

from typing import Literal

from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.agents.evaluation import evaluation_node
from app.agents.hallucination import hallucination_node
from app.agents.planner import planner_node
from app.agents.state import AgentState
from app.agents.verification import verification_node
from app.observability.tracing import traced_node

MAX_RETRIES = 2


async def _traced_planner(state: AgentState) -> AgentState:
    with traced_node("planner"):
        return await planner_node(state)


async def _traced_evaluation(state: AgentState) -> AgentState:
    with traced_node("evaluation"):
        return await evaluation_node(state)


async def _traced_hallucination(state: AgentState) -> AgentState:
    with traced_node("hallucination"):
        return await hallucination_node(state)


async def _traced_verification(state: AgentState) -> AgentState:
    with traced_node("verification"):
        return await verification_node(state)


async def _retry_node(state: AgentState) -> AgentState:
    with traced_node("retry"):
        return {**state, "retry_count": state["retry_count"] + 1}


async def _succeed_node(state: AgentState) -> AgentState:
    with traced_node("succeed"):
        return {**state, "status": "succeeded"}


async def _fail_node(state: AgentState) -> AgentState:
    with traced_node("fail"):
        return {**state, "status": "failed"}


def _route_after_verification(state: AgentState) -> Literal["succeed", "retry", "fail"]:
    if state["verification_passed"]:
        return "succeed"
    if state["retry_count"] < MAX_RETRIES:
        return "retry"
    return "fail"


def build_graph() -> CompiledStateGraph[AgentState, None, AgentState, AgentState]:
    graph: StateGraph[AgentState, None, AgentState, AgentState] = StateGraph(AgentState)

    graph.add_node("planner", _traced_planner)
    graph.add_node("evaluation", _traced_evaluation)
    graph.add_node("hallucination", _traced_hallucination)
    graph.add_node("verification", _traced_verification)
    graph.add_node("retry", _retry_node)
    graph.add_node("succeed", _succeed_node)
    graph.add_node("fail", _fail_node)

    graph.set_entry_point("planner")
    graph.add_edge("planner", "evaluation")
    graph.add_edge("evaluation", "hallucination")
    graph.add_edge("hallucination", "verification")
    graph.add_conditional_edges(
        "verification",
        _route_after_verification,
        {"succeed": "succeed", "retry": "retry", "fail": "fail"},
    )
    graph.add_edge("retry", "planner")
    graph.add_edge("succeed", END)
    graph.add_edge("fail", END)

    return graph.compile()


# Compiled once at import time — the graph definition is static; only the
# per-run AgentState varies between invocations.
agent_graph = build_graph()
