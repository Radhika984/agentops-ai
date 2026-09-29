"""Phase 5 tool tests.

Per the blueprint: "unit tests per tool server (mocked externally)" —
search_server's outbound HTTP call is mocked (no real network access in
this file); exec_server has no external dependency to mock (its "external"
resource is a local subprocess, not a network service), so it's tested for
real. registry.py's own tests mock mcp_client so they test the registry's
logic (timing, error handling, unknown-tool handling), not a full MCP
round-trip.

One real, local, non-network integration test proves a tool call's output
actually flows back correctly through the full MCP stdio pipeline (client
-> subprocess -> server -> tool), matching the blueprint's "integration
test proving a tool call's output correctly flows back into agent state."
A real *network* call (the search tool hitting DuckDuckGo) was verified
manually rather than in this automated suite, matching how Phase 2's real
Gemini call is verified manually rather than committed as a test that
depends on external network access.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.tools import mcp_client, registry
from app.tools.servers.exec_server import SandboxViolation, _validate, run_python
from app.tools.servers.search_server import web_search

pytestmark = pytest.mark.anyio


# ---- exec_server: AST validation (pure, no external dependency) ----


def test_validate_allows_plain_computation() -> None:
    _validate("print(sum(range(10)))")  # does not raise


def test_validate_rejects_import() -> None:
    with pytest.raises(SandboxViolation, match="Imports"):
        _validate("import os")


def test_validate_rejects_import_from() -> None:
    with pytest.raises(SandboxViolation, match="Imports"):
        _validate("from os import listdir")


def test_validate_rejects_dunder_name() -> None:
    with pytest.raises(SandboxViolation, match="__import__"):
        _validate("__import__('os')")


def test_validate_rejects_dunder_attribute_escape() -> None:
    with pytest.raises(SandboxViolation, match="__bases__"):
        _validate("().__class__.__bases__")


def test_validate_rejects_eval() -> None:
    with pytest.raises(SandboxViolation, match="eval"):
        _validate("eval('1+1')")


def test_validate_rejects_open() -> None:
    with pytest.raises(SandboxViolation, match="open"):
        _validate("open('/etc/passwd')")


def test_validate_rejects_syntax_errors() -> None:
    with pytest.raises(SandboxViolation, match="Syntax error"):
        _validate("this is not python (")


# ---- exec_server: run_python (real subprocess — no network involved) ----


async def test_run_python_executes_allowed_code() -> None:
    output = await run_python("print(sum(range(10)))")
    assert output.strip() == "45"


async def test_run_python_blocks_forbidden_import() -> None:
    output = await run_python("import os\nprint(os.listdir('.'))")
    assert output.startswith("Blocked:")
    assert "Imports" in output


async def test_run_python_times_out_on_infinite_loop() -> None:
    output = await run_python("while True:\n    pass")
    assert "timeout" in output.lower()


async def test_run_python_reports_runtime_errors() -> None:
    output = await run_python("print(1 / 0)")
    assert output.startswith("Error:")
    assert "ZeroDivisionError" in output


# ---- search_server: web_search (external HTTP call mocked) ----


async def test_web_search_returns_abstract_text() -> None:
    fake_response = MagicMock()
    fake_response.json.return_value = {"AbstractText": "Python is a language.", "RelatedTopics": []}
    fake_response.raise_for_status = MagicMock()

    fake_client = AsyncMock()
    fake_client.get.return_value = fake_response
    fake_client.__aenter__.return_value = fake_client
    fake_client.__aexit__.return_value = None

    with patch("app.tools.servers.search_server.httpx.AsyncClient", return_value=fake_client):
        result = await web_search("Python programming language")

    assert result == "Python is a language."


async def test_web_search_falls_back_when_nothing_found() -> None:
    fake_response = MagicMock()
    fake_response.json.return_value = {"AbstractText": "", "RelatedTopics": []}
    fake_response.raise_for_status = MagicMock()

    fake_client = AsyncMock()
    fake_client.get.return_value = fake_response
    fake_client.__aenter__.return_value = fake_client
    fake_client.__aexit__.return_value = None

    with patch("app.tools.servers.search_server.httpx.AsyncClient", return_value=fake_client):
        result = await web_search("an obscure conversational goal")

    assert result == "No results found."


# ---- registry.py: pluggability, timing, error handling (mcp_client mocked) ----


async def test_registry_call_tool_returns_ok_result(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_call(server_name: str, tool_name: str, arguments: dict[str, object]) -> str:
        assert server_name == "search"
        assert tool_name == "web_search"
        return "some result"

    monkeypatch.setattr(mcp_client, "call_tool", fake_call)

    result = await registry.call_tool("web_search", {"query": "x"})

    assert result.ok is True
    assert result.output == "some result"
    assert result.duration_ms >= 0


async def test_registry_call_tool_reports_unknown_tool() -> None:
    result = await registry.call_tool("not_a_real_tool", {})

    assert result.ok is False
    assert "Unknown tool" in result.output


async def test_registry_call_tool_does_not_raise_on_tool_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_call(server_name: str, tool_name: str, arguments: dict[str, object]) -> str:
        raise mcp_client.ToolCallError("boom")

    monkeypatch.setattr(mcp_client, "call_tool", fake_call)

    result = await registry.call_tool("run_python", {"code": "x"})

    assert result.ok is False
    assert "boom" in result.output


# ---- real, local (non-network) integration: full MCP stdio round-trip ----


async def test_registry_call_tool_real_round_trip_for_exec() -> None:
    """No mocking at all here — spawns the real exec MCP server subprocess
    via the real registry -> mcp_client -> stdio_client -> ClientSession
    pipeline, proving a tool call's output genuinely flows back correctly.
    """
    result = await registry.call_tool("run_python", {"code": "print(2 + 2)"})

    assert result.ok is True
    assert result.output.strip() == "4"
    assert result.tool_name == "run_python"
