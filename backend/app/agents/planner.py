"""Planner node: goal -> ordered task list.

Reuses the existing Phase 2 model-call seam (app.ai.client.call_model) —
same provider, same schema-validated structured output, same
exactly-one-retry-on-invalid-JSON semantics — rather than inventing a
second way to talk to the model.

Phase 5: calls the `web_search` tool via the registry first and includes
whatever it finds as optional context in the prompt — real "tool result
grounding" per the blueprint, not just pure reasoning. The free DuckDuckGo
API this tool uses often returns nothing for conversational, task-style
goals (see tools/servers/search_server.py's docstring) — the prompt is
written to treat search context as optional, so an empty result never
degrades the plan, it just means the model plans from the goal alone.

Phase 6: also queries app/memory/manager.py for similar past *runs*
(source_type="run") before planning — real RAG, not just search grounding.
Retrieved memory is carried in state.retrieved_memory so it's visible in
the API response, per the blueprint's Manual Testing Checklist ("Retrieved
context is visibly reflected in the Planner's output/reasoning").
"""

from __future__ import annotations

from pathlib import Path

from app.agents.schemas import PlanOutput
from app.agents.state import AgentState, FlagRecord, ToolCallRecord
from app.ai.client import call_model
from app.memory import manager as memory_manager
from app.tools.registry import call_tool

_PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "planner.txt"


async def planner_node(state: AgentState) -> AgentState:
    goal = state["goal"]

    search_result = await call_tool("web_search", {"query": goal})
    tool_call_record: ToolCallRecord = {
        "tool_name": search_result.tool_name,
        "input": search_result.input,
        "output": search_result.output,
        "duration_ms": search_result.duration_ms,
        "ok": search_result.ok,
    }
    # Phase 7: a Safety block is also recorded as a flag (in addition to
    # the tool_calls log every call gets) — the flags table is what the
    # blueprint's Manual Testing Checklist ("A destructive tool call
    # attempt is blocked by Safety") and the Run Trace view actually
    # surface, not the tool_calls log.
    new_flags: list[FlagRecord] = []
    if search_result.blocked_by_safety:
        new_flags.append(
            FlagRecord(
                agent="safety",
                type=search_result.safety_type or "blocked",
                severity=search_result.safety_severity or "medium",
                details=search_result.output,
            )
        )
    search_context = search_result.output if search_result.ok else "No results found."

    retrieved_memory = await memory_manager.recall(goal, source_type="run", top_k=3)
    memory_context = (
        "\n".join(f"- {m}" for m in retrieved_memory)
        if retrieved_memory
        else "No similar past runs found."
    )

    prompt = _PROMPT_PATH.read_text(encoding="utf-8").format(
        goal=goal, context=search_context, memory=memory_context
    )
    # Phase 8: "reasoning" group (default), agent="planner" for cost
    # dashboard attribution. Not cacheable — plan generation is
    # intentionally generative, not idempotent classification (see
    # app/ai/cache.py's docstring on what is/isn't safe to cache).
    result = await call_model(prompt, PlanOutput, agent="planner")

    return {
        **state,
        "plan": result.tasks,
        "status": "planning",
        "tool_calls": [*state["tool_calls"], tool_call_record],
        "retrieved_memory": retrieved_memory,
        "flags": [*state["flags"], *new_flags],
    }
