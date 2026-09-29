"""A minimal, safe path resolver for Assertion.path.

Deliberately not a JSONPath/jq expression engine and not an
expression-evaluating engine of any kind — it supports exactly two
things: a dotted key ("a.b.c") and a bracket list index ("a[0].b"),
optionally prefixed with the familiar "$" / "$." root marker. Pure data
traversal over dicts/lists; it cannot execute code, call a function, or
do anything other than descend into the structure it's given. This is
intentional per the locked audit's security boundary — the engine
evaluates untrusted agent output, so the path language itself must have
no expressive power beyond "look up this key/index."
"""

from __future__ import annotations

import re
from typing import Any

# A defensive cap, not a tuned limit — a legitimate assertion path is a
# handful of segments; anything wildly longer than this is almost
# certainly a malformed/pathological input, not a real use case.
MAX_PATH_SEGMENTS = 32

# One dot-separated segment: an optional key name, followed by zero or
# more [index] accessors — "name", "[0]", and "name[0][1]" all match;
# a segment with anything else (e.g. "name[0]x") does not.
_SEGMENT_RE = re.compile(r"^([^.\[\]]*)((?:\[-?\d+\])*)$")
_INDEX_RE = re.compile(r"\[(-?\d+)\]")


class InvalidPathError(ValueError):
    """Raised when a path string doesn't parse as a valid dotted/bracket
    path at all (not when a path simply fails to resolve against a
    particular value — that's a normal, expected "not found" outcome,
    not an error)."""


def parse_path(path: str) -> list[str | int]:
    text = path.strip()
    if text in ("", "$", "$."):
        return []
    if text.startswith("$."):
        text = text[2:]
    elif text.startswith("$"):
        text = text[1:]

    tokens: list[str | int] = []
    for segment in text.split("."):
        match = _SEGMENT_RE.match(segment)
        if not match:
            raise InvalidPathError(f"unparseable path segment {segment!r} in {path!r}")
        name, brackets = match.groups()
        if not name and not brackets:
            raise InvalidPathError(f"empty path segment in {path!r}")
        if name:
            tokens.append(name)
        for index_match in _INDEX_RE.finditer(brackets):
            tokens.append(int(index_match.group(1)))

    if len(tokens) > MAX_PATH_SEGMENTS:
        raise InvalidPathError(f"path {path!r} exceeds the maximum of {MAX_PATH_SEGMENTS} segments")

    return tokens


def resolve_path(data: Any, path: str) -> tuple[bool, Any]:
    """Returns (found, value). `found` is False if any segment along the
    way doesn't exist — never raises for a not-found path, only for a
    structurally invalid path string (see InvalidPathError)."""
    tokens = parse_path(path)
    current = data
    for token in tokens:
        if isinstance(token, str):
            if isinstance(current, dict) and token in current:
                current = current[token]
            else:
                return False, None
        else:
            if isinstance(current, list) and -len(current) <= token < len(current):
                current = current[token]
            else:
                return False, None
    return True, current
