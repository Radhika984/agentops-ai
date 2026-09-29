"""Shared state schema for the Planner -> Evaluation -> Hallucination ->
Verification graph (see agents/graph.py).

Matches the blueprint's AgentState fields (goal, plan, artifacts,
evaluations, status) plus the minimum extra fields required to implement
its own explicit requirements:
- `retry_count` / `verification_passed`: the bounded retry loop ("Retries
  are modeled as self-loops with a bounded counter in state, not infinite
  recursion" — Phase 4).
- `tool_calls`: Phase 5's tool-call log accumulated in state as nodes call
  tools via app/tools/registry.py, persisted to the `tool_calls` table by
  run_service.py once the graph finishes (nodes have no DB access by
  design — see AskService/ask_service.py for the same separation).
- `retrieved_memory`: Phase 6's long-term memory recall, fetched by
  planner_node via app/memory/manager.py before planning and carried in
  state so it's visible in the API response / frontend — the blueprint's
  own Manual Testing Checklist requires retrieved context to be "visibly
  reflected," not just silently used.
- `flags`: Phase 7's Safety/Hallucination findings, accumulated the same
  way tool_calls is (nodes append, run_service.py persists to the `flags`
  table once the graph finishes).
"""

from __future__ import annotations

from typing import Literal, TypedDict

RunStatus = Literal[
    "pending",
    "planning",
    "evaluating",
    "checking_hallucination",
    "verifying",
    "succeeded",
    "failed",
]


class ToolCallRecord(TypedDict):
    tool_name: str
    input: dict[str, object]
    output: str
    duration_ms: int
    ok: bool


class FlagRecord(TypedDict):
    agent: str
    type: str
    severity: str
    details: str


class AgentState(TypedDict):
    goal: str
    plan: list[str]
    artifacts: dict[str, str]
    evaluations: list[dict[str, object]]
    status: RunStatus
    retry_count: int
    verification_passed: bool
    tool_calls: list[ToolCallRecord]
    retrieved_memory: list[str]
    flags: list[FlagRecord]


def initial_state(goal: str) -> AgentState:
    return AgentState(
        goal=goal,
        plan=[],
        artifacts={},
        evaluations=[],
        status="pending",
        retry_count=0,
        verification_passed=False,
        tool_calls=[],
        retrieved_memory=[],
        flags=[],
    )
