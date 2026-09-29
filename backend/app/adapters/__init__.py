"""Phase 10 — Agent Adapter layer.

This package is deliberately separate from app/agents/ (AgentOps's own
internal LangGraph-orchestrated nodes: Planner, Evaluation, Hallucination,
Verification, RCA, AutoFix, Release Decision). Per the locked architecture
audit, the two must never be conceptually or architecturally confused:

- app/agents/  -> AgentOps's own internal workflow (the evaluation SYSTEM).
- app/adapters/ -> how AgentOps reaches a real external/local agent that
  the user registers as the System Under Test (SUT).

Nothing in this package calls into app/agents/, and nothing in app/agents/
is modified by this package. LangGraph is not used here — invoking an
external agent and normalizing its response is a single async function
call per adapter, not a multi-step internal workflow.
"""
