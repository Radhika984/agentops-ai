"""Thin MCP client wrapper.

Each server (search_server.py, exec_server.py) runs as its own stdio
subprocess. Spawning a fresh subprocess per tool call would be slow, so
sessions are started lazily on first use and cached for reuse — the same
"one seam, reused" pattern as app/ai/client.py.

Sessions are cached per *event loop*, not just per server name: an
anyio/asyncio ClientSession is bound to the loop it was created on and
cannot be reused from a different one — attempting to do so hangs rather
than raising a clear error. The real app only ever has one event loop for
its whole lifetime, so this is transparent there; it matters for the test
suite, where pytest-asyncio gives each test function its own fresh loop
by default, discovered the hard way when the full suite hung after
individual test files passed on their own.
"""

from __future__ import annotations

import asyncio
import sys
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

_SERVERS_DIR = Path(__file__).resolve().parent / "servers"

# Keyed by id(event loop): each loop gets its own exit stack + session
# cache, since sessions from a dead/different loop can't be reused or
# safely closed from the current one.
_LoopState = tuple[AsyncExitStack, dict[str, ClientSession]]
_state_by_loop: dict[int, _LoopState] = {}


class ToolCallError(Exception):
    """Raised when an MCP tool call fails or the server reports an error."""


def _current_state() -> _LoopState:
    loop_key = id(asyncio.get_running_loop())
    if loop_key not in _state_by_loop:
        _state_by_loop[loop_key] = (AsyncExitStack(), {})
    return _state_by_loop[loop_key]


async def _get_session(server_name: str) -> ClientSession:
    exit_stack, sessions = _current_state()
    if server_name in sessions:
        return sessions[server_name]

    script_path = _SERVERS_DIR / f"{server_name}_server.py"
    params = StdioServerParameters(command=sys.executable, args=[str(script_path)])

    read, write = await exit_stack.enter_async_context(stdio_client(params))
    session = await exit_stack.enter_async_context(ClientSession(read, write))
    await session.initialize()

    sessions[server_name] = session
    return session


async def call_tool(server_name: str, tool_name: str, arguments: dict[str, Any]) -> str:
    """Call `tool_name` on the given MCP server and return its text result."""
    session = await _get_session(server_name)
    result = await session.call_tool(tool_name, arguments)

    text_parts = [block.text for block in result.content if hasattr(block, "text")]
    output = "\n".join(text_parts)

    if result.isError:
        raise ToolCallError(output or f"{tool_name} reported an error")

    return output


async def shutdown() -> None:
    """Closes all cached MCP sessions/subprocesses for the *current* event
    loop. Call on app shutdown."""
    loop_key = id(asyncio.get_running_loop())
    state = _state_by_loop.pop(loop_key, None)
    if state is not None:
        exit_stack, _sessions = state
        await exit_stack.aclose()
