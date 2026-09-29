"""Phase 19 — AutoFix: deterministic, whitelist-only remediation proposals.

AutoFix is NOT an autonomous code-writing agent — this module never calls
an LLM, never generates arbitrary patches, and never touches
AgentVersion.adapter_config (that column is never even imported here).
`build_autofix_proposal()` is a pure, rule-based mapping from Phase 18's
already-computed RCA evidence (app/rca/evidence.py's deterministic
whitelist — reused, not reimplemented) onto exactly one of the four
locked, whitelisted options:

  1. testcase_edit          — propose relaxing a specific TestCase field
  2. agent_default_edit     — propose relaxing an Agent default-contract
                               field (not used by the deterministic rules
                               below by default — see their own
                               docstrings for why the narrower,
                               single-TestCase-scoped option 1 is
                               preferred; still a real, reachable option)
  3. trial_count_increase   — propose a bounded retry for suspected
                               nondeterminism
  4. owner_suggestion       — a NOT-APPLIED natural-language note only,
                               requires no approval, changes nothing

Every editable field name is drawn from one of the two frozensets below
— TESTCASE_EDITABLE_FIELDS / AGENT_DEFAULT_EDITABLE_FIELDS — the
explicit whitelist app/autofix/apply.py re-validates against before
ever writing anything. Neither set contains "adapter_config" or any
credential-shaped field; both are exhaustively enumerated, not pattern
-matched, so there is no way for an unlisted field to slip through.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

from app.models.agent import Agent
from app.models.test_case import TestCase
from app.models.test_case_result import TestCaseResult
from app.rca.evidence import (
    CATEGORY_FORBIDDEN_TOOL_CALLED,
    CATEGORY_LATENCY_EXCEEDED,
    CATEGORY_MISSING_REQUIRED_TOOL_CALL,
    CATEGORY_SCHEMA_FIELD_MISSING,
    DeterministicFinding,
    classify_deterministic,
)

AutoFixOption = Literal[
    "testcase_edit", "agent_default_edit", "trial_count_increase", "owner_suggestion"
]

# Option 3's explicit, bounded maximum (§ "must be bounded... explicit
# maximum... never an infinite retry loop"). Matches this project's own
# "small explicit cap" convention (e.g. schemas/suite_run.py's
# MAX_CONCURRENCY_LIMIT = 5).
MAX_AUTOFIX_TRIAL_COUNT = 5

# Option 1's whitelist — TestCase fields safe for a "flaky/over-strict
# test" remediation to touch. Deliberately excludes `name`, `input`,
# `history`, `rubric`, `tags`, `metadata` (not correctness-contract
# fields) and `trial_count` (that is Option 3's own, separately-bounded
# path, never folded into a generic field edit).
TESTCASE_EDITABLE_FIELDS = frozenset(
    {
        "expected_output",
        "assertions",
        "allowed_tools",
        "expected_tool_calls",
        "output_schema",
        "reference_context",
    }
)

# Option 2's whitelist — EXACTLY the Agent default-contract fields named
# in the locked Phase 19 brief. No other Agent field (name, description,
# is_enabled, project_id, id) is ever eligible.
AGENT_DEFAULT_EDITABLE_FIELDS = frozenset(
    {
        "default_expected_behavior",
        "default_forbidden_behavior",
        "default_output_schema",
        "default_latency_threshold_ms",
        "default_allowed_tools",
        "default_required_tools",
        "min_call_interval_ms",
        "default_timeout_ms",
    }
)

_MISSING_SCHEMA_FIELD_RE = re.compile(r"'([^']+)' is a required property")


@dataclass(frozen=True)
class AutoFixProposal:
    option: AutoFixOption
    rca_category: str | None
    field: str | None
    current_value: Any
    proposed_value: Any
    rationale: str
    requires_approval: bool


def _extract_missing_tool_name(finding: DeterministicFinding) -> str | None:
    # check_type is e.g. "tool_call[0]:search" — the part after ':'.
    if ":" in finding.check_type:
        return finding.check_type.split(":", 1)[1]
    return None


def _extract_missing_schema_field(finding: DeterministicFinding) -> str | None:
    match = _MISSING_SCHEMA_FIELD_RE.search(finding.detail)
    return match.group(1) if match else None


def _has_mixed_trial_results(result: TestCaseResult) -> bool:
    verdicts = {trial.get("verdict") for trial in result.trials}
    return len(verdicts) > 1


def _owner_suggestion(rationale: str, rca_category: str | None = None) -> AutoFixProposal:
    return AutoFixProposal(
        option="owner_suggestion",
        rca_category=rca_category,
        field=None,
        current_value=None,
        proposed_value=None,
        rationale=rationale,
        requires_approval=False,
    )


def build_autofix_proposal(
    test_case: TestCase,
    result: TestCaseResult,
    *,
    agent: Agent | None = None,
    prefer_agent_default: bool = False,
) -> AutoFixProposal:
    """Maps `result`'s already-persisted evidence onto exactly one
    whitelisted AutoFix option — pure, deterministic, no LLM, no
    database access. Priority order matches the locked brief's own
    examples: a forbidden tool call is never "fixed" (always Option 4);
    a missing required tool gets a narrow, single-TestCase Option 1
    proposal; latency/nondeterminism evidence gets a bounded Option 3
    retry proposal; anything else falls back to an Option 4 note
    recommending manual review.

    A missing schema field is the one case the locked brief itself
    calls out as reachable via *either* Option 1 (narrow, single-
    TestCase) or Option 2 (Agent default_output_schema, §"or approved
    Agent default output schema correction") — Option 1 is the default
    (narrower blast radius), and the caller opts into Option 2 by
    passing `prefer_agent_default=True` together with the owning
    `agent` (app/services/autofix_service.py's `propose()` does this
    only when the caller of POST .../autofix explicitly asked for it).
    """
    deterministic = classify_deterministic(result.checks)
    categories = {finding.category for finding in deterministic}

    if CATEGORY_FORBIDDEN_TOOL_CALLED in categories:
        return _owner_suggestion(
            "The agent called a tool forbidden by this TestCase's allowed_tools. This is a "
            "safety/release concern with the agent under test, not a test-configuration "
            "problem — AutoFix does not propose changing the agent or the test's tool "
            "constraints for this. Review the agent's tool usage directly.",
            rca_category=CATEGORY_FORBIDDEN_TOOL_CALLED,
        )

    missing_tool_finding = next(
        (f for f in deterministic if f.category == CATEGORY_MISSING_REQUIRED_TOOL_CALL), None
    )
    if missing_tool_finding is not None:
        tool_name = _extract_missing_tool_name(missing_tool_finding)
        current = test_case.expected_tool_calls or []
        proposed = [entry for entry in current if entry.get("tool") != tool_name]
        return AutoFixProposal(
            option="testcase_edit",
            rca_category=CATEGORY_MISSING_REQUIRED_TOOL_CALL,
            field="expected_tool_calls",
            current_value=current,
            proposed_value=proposed,
            rationale=(
                f"Required tool '{tool_name}' was never observed. Proposing to remove this "
                "specific requirement from expected_tool_calls (the test may be over-strict) "
                "rather than assume the agent under test is broken."
            ),
            requires_approval=True,
        )

    schema_finding = next(
        (f for f in deterministic if f.category == CATEGORY_SCHEMA_FIELD_MISSING), None
    )
    if schema_finding is not None:
        missing_field = _extract_missing_schema_field(schema_finding)
        if prefer_agent_default and agent is not None:
            current_schema = agent.default_output_schema or {}
            required = list(current_schema.get("required", []))
            proposed_required = (
                [f for f in required if f != missing_field] if missing_field else required
            )
            proposed_schema = {**current_schema, "required": proposed_required}
            return AutoFixProposal(
                option="agent_default_edit",
                rca_category=CATEGORY_SCHEMA_FIELD_MISSING,
                field="default_output_schema",
                current_value=current_schema,
                proposed_value=proposed_schema,
                rationale=(
                    f"output_schema requires field {missing_field!r}, which the agent's output "
                    "never included. Proposing to relax the Agent's default_output_schema by "
                    "removing it from `required` — the caller asked for the broader, Agent-level "
                    "remediation rather than a single-TestCase edit."
                ),
                requires_approval=True,
            )
        current_schema = test_case.output_schema or {}
        required = list(current_schema.get("required", []))
        proposed_required = (
            [f for f in required if f != missing_field] if missing_field else required
        )
        proposed_schema = {**current_schema, "required": proposed_required}
        return AutoFixProposal(
            option="testcase_edit",
            rca_category=CATEGORY_SCHEMA_FIELD_MISSING,
            field="output_schema",
            current_value=current_schema,
            proposed_value=proposed_schema,
            rationale=(
                f"output_schema requires field {missing_field!r}, which the agent's output "
                "never included. Proposing to relax this TestCase's output_schema by removing "
                "it from `required` (a possible test-side over-specification)."
            ),
            requires_approval=True,
        )

    latency_finding = next(
        (f for f in deterministic if f.category == CATEGORY_LATENCY_EXCEEDED), None
    )
    if latency_finding is not None or _has_mixed_trial_results(result):
        current_trials = test_case.trial_count
        proposed_trials = min(max(current_trials * 2, current_trials + 1), MAX_AUTOFIX_TRIAL_COUNT)
        if proposed_trials <= current_trials:
            return _owner_suggestion(
                f"trial_count is already at AutoFix's bounded maximum ({MAX_AUTOFIX_TRIAL_COUNT}); "
                "no further automated retry increase is proposed. Manual review recommended.",
                rca_category=latency_finding.category if latency_finding else None,
            )
        return AutoFixProposal(
            option="trial_count_increase",
            rca_category=latency_finding.category if latency_finding else "nondeterminism",
            field="trial_count",
            current_value=current_trials,
            proposed_value=proposed_trials,
            rationale=(
                "Evidence suggests possible nondeterminism (latency variance or a mixed "
                f"pass/fail trial split); proposing a bounded trial_count increase "
                f"({current_trials} -> {proposed_trials}, capped at {MAX_AUTOFIX_TRIAL_COUNT}) "
                "rather than weakening any threshold."
            ),
            requires_approval=True,
        )

    return _owner_suggestion(
        f"TestCaseResult verdict is {result.verdict}; no deterministic AutoFix pattern "
        "matched this failure. Manual review is recommended."
    )
