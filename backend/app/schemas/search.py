from __future__ import annotations

import uuid

from pydantic import BaseModel

# Exactly the entity kinds app/services/search_service.py actually
# queries — a closed set, matching how every other typed field in this
# app enumerates its real possibilities rather than leaving `kind` as a
# bare str.
SearchResultKind = str
# "project" | "agent" | "test_suite" | "test_case" | "suite_run" | "agent_version"


class SearchResult(BaseModel):
    kind: SearchResultKind
    id: uuid.UUID
    title: str
    subtitle: str | None
    """Route the frontend should navigate to for this result — a real,
    already-existing route in the app, never a placeholder."""
    href: str


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResult]
