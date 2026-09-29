"""MCP server exposing a web-search tool.

Uses DuckDuckGo's free Instant Answer API (no API key, no billing, no
account) — the only search option that fits this project's hard free-tier
constraint. Known, honest limitation: it's an "instant answer" API, not a
general web index, so it returns good results for encyclopedia-style
topics but often nothing for conversational/task-style goals. The tool
reports "No results found." in that case rather than failing — callers
(see app/agents/planner.py) treat search context as optional grounding,
not a hard dependency.

Run standalone via stdio (spawned by app/tools/mcp_client.py), matching
the same process-per-server model exec_server.py uses.
"""

from __future__ import annotations

import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("search")

_TIMEOUT_SECONDS = 10.0


@mcp.tool()
async def web_search(query: str) -> str:
    """Search the web for `query` and return a short summary of what's found."""
    async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
        response = await client.get(
            "https://api.duckduckgo.com/",
            params={"q": query, "format": "json", "no_html": 1, "skip_disambig": 1},
        )
        response.raise_for_status()
        data = response.json()

    parts: list[str] = []
    abstract = data.get("AbstractText")
    if abstract:
        parts.append(abstract)

    for topic in data.get("RelatedTopics", [])[:3]:
        text = topic.get("Text") if isinstance(topic, dict) else None
        if text:
            parts.append(text)

    return "\n".join(parts) if parts else "No results found."


if __name__ == "__main__":
    mcp.run()
