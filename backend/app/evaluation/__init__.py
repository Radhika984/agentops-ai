"""Phase 13 — the deterministic-first Assertion Engine.

Evaluates one already-produced app.adapters.execution.AgentExecution
against one app.models.test_case.TestCase's stored ground truth. This
package never calls an AgentAdapter (it consumes an AgentExecution that
already exists) and never calls an LLM — see engine.py's module
docstring for the exact deterministic/LLM boundary this phase draws.

    AgentAdapter -> AgentExecution -> [this package] -> EvaluationResult

Later phases (14+) connect this to persisted SuiteRuns/TestCaseResults;
nothing here persists anything.
"""
