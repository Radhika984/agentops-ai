"""Phase 18 — RCA + Release Gate: deterministic evidence extraction.

Pure functions over an already-persisted TestCaseResult's `checks[]`
array (Phase 13/15 evidence, verbatim — nothing here recomputes a check
or re-invokes any evaluator). The SAME small set of pattern-detectors is
reused by THREE consumers:
  - app/rca/service.py's deterministic RCA tier (the locked Phase 18
    brief's exact 4-category whitelist, §6)
  - app/release_gate/gate.py's hard-gate evaluation (the locked §15's 5
    hard-gate categories)
  - app/evaluation/checks/llm_judge.py's invocation-gating decision
    (Phase 19 — "never invoke the LLM judge merely to override an
    objective deterministic hard failure")
so none of the three concerns ever independently reimplements (and risks
silently disagreeing about) what counts as e.g. "a missing required tool
call."

Every detector matches on `check_type` (which check family produced this
entry — see app/evaluation/checks/*.py for where each string comes
from) plus, where necessary, a literal substring of that check's own
`detail` text (also produced by those same, unmodified Phase 13/15
modules) to disambiguate between two different FAIL reasons the same
check_type can carry (e.g. a `tool_call[i]:tool` FAIL can mean "never
called" or "called with the wrong arguments" — only the former is the
`missing_required_tool_call` RCA category). No new evaluation logic is
introduced; this module only classifies evidence that already exists.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_EXPECTED_TOOL_CALL_RE = re.compile(r"^tool_call\[\d+\]:")
_SAFETY_CHECK_RE = re.compile(r"^safety:")

CATEGORY_MISSING_REQUIRED_TOOL_CALL = "missing_required_tool_call"
CATEGORY_SCHEMA_FIELD_MISSING = "schema_field_missing"
CATEGORY_LATENCY_EXCEEDED = "latency_exceeded"
CATEGORY_FORBIDDEN_TOOL_CALLED = "forbidden_tool_called"

# The locked Phase 18 deterministic RCA whitelist (§6), in priority order.
DETERMINISTIC_RCA_CATEGORIES = (
    CATEGORY_MISSING_REQUIRED_TOOL_CALL,
    CATEGORY_SCHEMA_FIELD_MISSING,
    CATEGORY_LATENCY_EXCEEDED,
    CATEGORY_FORBIDDEN_TOOL_CALLED,
)

# Hard-gate-only categories (§15) that are not part of the RCA whitelist.
CATEGORY_SAFETY_FLAG = "safety_flag"
CATEGORY_SCHEMA_FAILURE = "schema_failure"
CATEGORY_CORRECTNESS_FAILURE = "correctness_failure"


@dataclass(frozen=True)
class DeterministicFinding:
    category: str
    check_type: str
    detail: str
    metadata: dict[str, Any]


def _is_fail(check: dict[str, Any]) -> bool:
    return check.get("status") == "fail"


def find_missing_required_tool_calls(checks: list[dict[str, Any]]) -> list[DeterministicFinding]:
    """A `tool_call[i]:tool` FAIL whose detail says the tool was never
    called (app/evaluation/checks/tool_trajectory.py's `_check_single_call`
    — the exact phrase "missing required tool call" it already writes),
    as opposed to being called with unsatisfying arguments (a different
    detail string, deliberately not matched here)."""
    return [
        DeterministicFinding(
            CATEGORY_MISSING_REQUIRED_TOOL_CALL,
            check["check_type"],
            check.get("detail", ""),
            check.get("metadata") or {},
        )
        for check in checks
        if _EXPECTED_TOOL_CALL_RE.match(check.get("check_type", ""))
        and _is_fail(check)
        and "missing required tool call" in check.get("detail", "")
    ]


def find_schema_field_missing(checks: list[dict[str, Any]]) -> list[DeterministicFinding]:
    """An `output_schema` FAIL whose detail is jsonschema's own "required
    property" error text (app/evaluation/checks/output_schema.py) — a
    required field being absent, distinct from a type/value mismatch."""
    return [
        DeterministicFinding(
            CATEGORY_SCHEMA_FIELD_MISSING,
            check["check_type"],
            check.get("detail", ""),
            check.get("metadata") or {},
        )
        for check in checks
        if check.get("check_type") == "output_schema"
        and _is_fail(check)
        and "is a required property" in check.get("detail", "")
    ]


def find_latency_exceeded(checks: list[dict[str, Any]]) -> list[DeterministicFinding]:
    """A `latency` FAIL whose detail says the threshold was exceeded
    (app/evaluation/checks/latency.py), distinct from that same
    check_type's other FAIL reason (latency_ms itself being missing)."""
    return [
        DeterministicFinding(
            CATEGORY_LATENCY_EXCEEDED,
            check["check_type"],
            check.get("detail", ""),
            check.get("metadata") or {},
        )
        for check in checks
        if check.get("check_type") == "latency"
        and _is_fail(check)
        and "exceeds" in check.get("detail", "")
    ]


def find_forbidden_tool_called(checks: list[dict[str, Any]]) -> list[DeterministicFinding]:
    """A `forbidden_tool_calls` FAIL (app/evaluation/checks/tool_trajectory.py's
    `_check_forbidden_tools`) — a tool call outside TestCase.allowed_tools."""
    return [
        DeterministicFinding(
            CATEGORY_FORBIDDEN_TOOL_CALLED,
            check["check_type"],
            check.get("detail", ""),
            check.get("metadata") or {},
        )
        for check in checks
        if check.get("check_type") == "forbidden_tool_calls" and _is_fail(check)
    ]


def classify_deterministic(checks: list[dict[str, Any]]) -> list[DeterministicFinding]:
    """The full locked 4-category RCA whitelist (§6), in priority order.
    Empty if no deterministic pattern matches — the caller (app/rca/
    service.py) falls through to the LLM hypothesis tier only then."""
    return [
        *find_missing_required_tool_calls(checks),
        *find_schema_field_missing(checks),
        *find_latency_exceeded(checks),
        *find_forbidden_tool_called(checks),
    ]


def find_safety_flags(checks: list[dict[str, Any]]) -> list[DeterministicFinding]:
    """Any failing `safety:*` check (app/evaluation/checks/safety.py) —
    hard-gate-eligible (§15/§26), not part of the RCA whitelist (§6 does
    not list a safety category)."""
    return [
        DeterministicFinding(
            CATEGORY_SAFETY_FLAG,
            check["check_type"],
            check.get("detail", ""),
            check.get("metadata") or {},
        )
        for check in checks
        if _SAFETY_CHECK_RE.match(check.get("check_type", "")) and _is_fail(check)
    ]


def find_schema_failures(checks: list[dict[str, Any]]) -> list[DeterministicFinding]:
    """ANY failing `output_schema` check — broader than
    `find_schema_field_missing` above (§29: schema failure is hard
    regardless of which specific validation rule tripped)."""
    return [
        DeterministicFinding(
            CATEGORY_SCHEMA_FAILURE,
            check["check_type"],
            check.get("detail", ""),
            check.get("metadata") or {},
        )
        for check in checks
        if check.get("check_type") == "output_schema" and _is_fail(check)
    ]


# Check_types already covered by their own named hard-gate category
# above — never double-counted as a generic "correctness_failure" too.
_ALREADY_CATEGORIZED_EXACT_CHECK_TYPES = frozenset({"forbidden_tool_calls", "output_schema"})
# check_types that fail deterministically but are explicitly NOT
# hard-gate-eligible correctness signals: `latency` (§15/§30 — performance
# alone is never a hard gate), `grounding` (§15's hard-gate list does not
# name grounding — a deliberate, documented classification), `rubric`
# (Phase 13's PENDING_LLM placeholder — never itself a FAIL, excluded
# defensively), and `rubric_judge` (Phase 19 — the LLM judge's own
# resolved PASS/FAIL/INCONCLUSIVE check; a subjective judgment must
# remain distinguishable from an objective correctness failure and must
# never itself become an automatic correctness hard-gate reason, per the
# locked Phase 19 brief's §D).
_EXCLUDED_FROM_CORRECTNESS_CHECK_TYPES = frozenset(
    {"latency", "grounding", "rubric", "rubric_judge"}
)


def find_correctness_failures(checks: list[dict[str, Any]]) -> list[DeterministicFinding]:
    """The Release-Gate-only "correctness" hard-gate category (§15's
    "Correctness: a correctness failure that is eligible for hard
    gating"), evaluated explicitly from Phase 13's actual deterministic
    check evidence — NEVER from `TestCaseResult.verdict == "FAIL"` alone
    (that was a real bug: a case can legitimately FAIL solely because of
    an excluded, non-hard-gate-eligible check like `latency`, and
    treating every FAIL verdict as a correctness hard gate would
    incorrectly hard-gate that case too).

    Matches: `expected_output` FAIL, `assertion[i]` FAIL (app/evaluation/
    checks/assertions.py), `tool_call_order` FAIL, a `tool_call[i]:tool`
    FAIL caused by unsatisfied argument constraints (as opposed to the
    tool never being called at all — that's already
    `missing_required_tool_call`, excluded here to avoid double
    -counting), and a malformed `expected_tool_call[i]` spec FAIL. Does
    NOT match `latency`, `grounding`, `rubric`, or anything already
    covered by its own named category (safety, forbidden tool, missing
    required tool, schema).

    This is deliberately NOT part of `classify_deterministic()` (the RCA
    whitelist, §6) — RCA has no catch-all correctness pattern; an
    unmatched correctness failure is exactly the case meant to reach
    RCA's LLM hypothesis tier instead. Called by app/release_gate/gate.py
    only when the case's own verdict is "FAIL" — see that module's own
    docstring for why (avoiding a trial-majority-tie INCONCLUSIVE case's
    last-trial checks from being treated as a hard-gate reason)."""
    findings: list[DeterministicFinding] = []
    for check in checks:
        if not _is_fail(check):
            continue
        check_type = check.get("check_type", "")
        if check_type in _EXCLUDED_FROM_CORRECTNESS_CHECK_TYPES:
            continue
        if check_type in _ALREADY_CATEGORIZED_EXACT_CHECK_TYPES:
            continue
        if _SAFETY_CHECK_RE.match(check_type):
            continue
        if _EXPECTED_TOOL_CALL_RE.match(check_type) and "missing required tool call" in check.get(
            "detail", ""
        ):
            continue  # already categorized as missing_required_tool_call
        findings.append(
            DeterministicFinding(
                CATEGORY_CORRECTNESS_FAILURE,
                check_type,
                check.get("detail", ""),
                check.get("metadata") or {},
            )
        )
    return findings
