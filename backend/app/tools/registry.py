"""Maps a tool name to the MCP server that implements it.

This is the one place agent nodes go through to call a tool — per the
blueprint's Definition of Done ("tools are pluggable via the registry
(adding a new tool doesn't require touching agent node code)"), adding a
new tool means adding one line to _TOOL_SERVERS and (if it's a new
server) a new file under tools/servers/, never editing planner.py or
verification.py.

Phase 7: every call is checked by app.agents.safety.check_tool_call()
*before* it reaches app/tools/mcp_client.py. Being the single seam every
tool call already passed through (Phase 5's whole reason for a registry
in the first place) is what makes "no tool call reaches execution without
a Safety check" (the blueprint's Definition of Done) a structural
guarantee rather than a convention every node has to remember to follow.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from app.agents import safety
from app.tools import mcp_client

# tool name -> MCP server name (servers/{name}_server.py)
_TOOL_SERVERS: dict[str, str] = {
    "web_search": "search",
    "run_python": "exec",
}


@dataclass
class ToolCallResult:
    tool_name: str
    input: dict[str, Any]
    output: str
    duration_ms: int
    ok: bool
    blocked_by_safety: bool = False
    safety_type: str | None = None
    safety_severity: str | None = None


async def call_tool(tool_name: str, arguments: dict[str, Any]) -> ToolCallResult:
    """Calls `tool_name` with `arguments`, timing the call for the
    tool_calls audit log (see app/models/tool_call.py). Never raises for a
    failed/blocked tool call — that's reported via `ok=False` so a node can
    decide how to proceed rather than crashing the whole graph run over a
    single bad tool call.
    """
    if tool_name not in _TOOL_SERVERS:
        return ToolCallResult(
            tool_name=tool_name,
            input=arguments,
            output=f"Unknown tool: {tool_name}",
            duration_ms=0,
            ok=False,
        )

    start = time.monotonic()

    safety_result = await safety.check_tool_call(tool_name, arguments)
    if not safety_result.allowed:
        duration_ms = int((time.monotonic() - start) * 1000)
        return ToolCallResult(
            tool_name=tool_name,
            input=arguments,
            output=f"Blocked by Safety: {safety_result.reason}",
            duration_ms=duration_ms,
            ok=False,
            blocked_by_safety=True,
            safety_type=safety_result.type,
            safety_severity=safety_result.severity,
        )

    server_name = _TOOL_SERVERS[tool_name]
    try:
        output = await mcp_client.call_tool(server_name, tool_name, arguments)
        ok = True
    except mcp_client.ToolCallError as exc:
        output = str(exc)
        ok = False
    except Exception as exc:  # noqa: BLE001 - tool failures must not crash the graph
        output = f"Tool call failed: {exc}"
        ok = False
    duration_ms = int((time.monotonic() - start) * 1000)

    return ToolCallResult(
        tool_name=tool_name, input=arguments, output=output, duration_ms=duration_ms, ok=ok
    )
