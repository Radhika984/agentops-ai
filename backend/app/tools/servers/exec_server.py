"""MCP server exposing sandboxed Python code execution.

Sandboxing mechanism (honest about what this is and isn't — see Phase 5's
"Common Mistakes": "giving code-execution tools unrestricted
filesystem/network access"):

1. Static AST validation before anything runs: rejects all import
   statements (blocks os/sys/subprocess/socket/etc. in one pass, rather
   than maintaining a denylist of "dangerous" modules) and rejects dunder
   name/attribute access (blocks the standard `().__class__.__bases__...`
   -style sandbox-escape tricks) and the eval/exec/compile/open/input/
   __import__ builtins by name.
2. Process isolation: the validated code runs in a *separate* subprocess,
   not in this server's own process — spawned with a minimal environment
   (no DATABASE_URL, no API keys) and a fresh working directory.
3. A hard wall-clock timeout kills runaway code (e.g. infinite loops).
4. Output is captured and truncated, never allowed to grow unbounded.

This is real, layered sandboxing appropriate for this project's scope —
it is deliberately NOT claimed to be a production-grade isolation
boundary for genuinely adversarial code (that would need OS/VM-level
isolation such as gVisor, Firecracker, or a container per execution,
which the blueprint offers as an alternative but which requires
Docker-socket access this backend does not have and should not be given).
"""

from __future__ import annotations

import ast
import asyncio
import subprocess
import sys
import tempfile
from pathlib import Path

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("exec")

_TIMEOUT_SECONDS = 5
_MAX_OUTPUT_CHARS = 4000
_FORBIDDEN_CALL_NAMES = {"eval", "exec", "compile", "open", "input", "__import__"}


class SandboxViolation(Exception):
    pass


def _validate(code: str) -> None:
    try:
        tree = ast.parse(code, mode="exec")
    except SyntaxError as exc:
        raise SandboxViolation(f"Syntax error: {exc}") from exc

    for node in ast.walk(tree):
        if isinstance(node, ast.Import | ast.ImportFrom):
            raise SandboxViolation("Imports are not allowed in the sandbox.")
        if isinstance(node, ast.Name) and node.id.startswith("__") and node.id.endswith("__"):
            raise SandboxViolation(f"Access to '{node.id}' is not allowed in the sandbox.")
        if isinstance(node, ast.Attribute) and node.attr.startswith("__") and node.attr.endswith(
            "__"
        ):
            raise SandboxViolation(f"Access to '.{node.attr}' is not allowed in the sandbox.")
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in _FORBIDDEN_CALL_NAMES
        ):
            raise SandboxViolation(f"Calling '{node.func.id}' is not allowed in the sandbox.")


def _run_in_subprocess(code: str) -> str:
    """Blocking; run via asyncio.to_thread so it never blocks this server's
    own event loop (which the MCP stdio transport needs to stay responsive
    on). stdin=DEVNULL so the child never inherits this process's own
    stdio pipes — those are actively in use for the MCP JSON-RPC protocol
    with the caller, and letting a child hold handles to them caused the
    child to hang until the timeout during testing."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        script_path = Path(tmp_dir) / "snippet.py"
        script_path.write_text(code, encoding="utf-8")

        try:
            result = subprocess.run(
                [sys.executable, "-I", str(script_path)],
                capture_output=True,
                text=True,
                timeout=_TIMEOUT_SECONDS,
                cwd=tmp_dir,
                env={},  # no inherited env vars — no DB URL, no API keys
                stdin=subprocess.DEVNULL,
            )
        except subprocess.TimeoutExpired:
            return f"Blocked: execution exceeded {_TIMEOUT_SECONDS}s timeout."

        output = result.stdout if result.returncode == 0 else f"Error: {result.stderr}"
        return output[:_MAX_OUTPUT_CHARS]


@mcp.tool()
async def run_python(code: str) -> str:
    """Execute a short, sandboxed Python snippet and return its stdout.

    No imports, no filesystem/network access, no dunder attribute access.
    Runs with a 5-second timeout in an isolated subprocess.
    """
    try:
        _validate(code)
    except SandboxViolation as exc:
        return f"Blocked: {exc}"

    return await asyncio.to_thread(_run_in_subprocess, code)


if __name__ == "__main__":
    mcp.run()
