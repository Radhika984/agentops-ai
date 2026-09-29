"""Safety: policy engine + LLM fallback classifier.

Two-tier, per the blueprint: "Policy engine (deterministic rules) first,
LLM classifier as a second opinion on edge cases" — and per Phase 7's own
"Common Mistakes": never rely solely on the LLM classifier, since rules
are auditable and can't be talked out of their decision the way a
prompt-injected model might be.

1. deny_patterns (observability/policy_rules.yaml): a regex match blocks
   the call immediately. No LLM call — fast, free, deterministic.
2. review_patterns: a regex match is inherently ambiguous (e.g. "hack" in
   both "hack a website" and "lifehack for productivity") — escalated to
   the LLM classifier for a second opinion.
3. No match at all: allowed.

Called from app/tools/registry.py, before any tool call reaches
app/tools/mcp_client.py — see that module for why the check lives there
rather than as a separate graph node (it's the one place every tool call,
present or future, is guaranteed to pass through).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from app.agents.schemas import SafetyClassification
from app.ai.client import AIClientError, call_model

_POLICY_PATH = Path(__file__).resolve().parent.parent / "observability" / "policy_rules.yaml"
_LLM_PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "safety_review.txt"


@dataclass
class PolicyRule:
    pattern: re.Pattern[str]
    type: str
    severity: str = "medium"


@dataclass
class SafetyResult:
    allowed: bool
    type: str | None = None
    severity: str | None = None
    reason: str | None = None
    used_llm_fallback: bool = False


def _load_rules(key: str) -> list[PolicyRule]:
    data = yaml.safe_load(_POLICY_PATH.read_text(encoding="utf-8"))
    return [
        PolicyRule(
            pattern=re.compile(rule["pattern"], re.IGNORECASE),
            type=rule["type"],
            severity=rule.get("severity", "medium"),
        )
        for rule in data.get(key, [])
    ]


_DENY_RULES = _load_rules("deny_patterns")
_REVIEW_RULES = _load_rules("review_patterns")


def _stringify(arguments: dict[str, Any]) -> str:
    return " ".join(str(v) for v in arguments.values())


async def check_tool_call(tool_name: str, arguments: dict[str, Any]) -> SafetyResult:
    """Checks a proposed tool call against policy before it's allowed to
    execute. Never raises — a Safety-check failure (e.g. the LLM fallback
    being unavailable) fails safe (denies), it never silently allows
    through an unreviewable call.
    """
    text = _stringify(arguments)

    for rule in _DENY_RULES:
        if rule.pattern.search(text):
            return SafetyResult(
                allowed=False,
                type=rule.type,
                severity=rule.severity,
                reason=f"Matched deny pattern for '{rule.type}'.",
            )

    matched_review_rule = next((r for r in _REVIEW_RULES if r.pattern.search(text)), None)
    if matched_review_rule is None:
        return SafetyResult(allowed=True)

    prompt = _LLM_PROMPT_PATH.read_text(encoding="utf-8").format(
        tool_name=tool_name, arguments=text
    )
    try:
        # Phase 8: "judgment" group (classification, not open-ended
        # generation) and cacheable=True — the same ambiguous tool call
        # deserves the same verdict every time, so a repeat is a real
        # cache hit, not a stale answer (see app/ai/cache.py's docstring).
        classification = await call_model(
            prompt, SafetyClassification, agent="safety", model_group="judgment", cacheable=True
        )
    except AIClientError:
        # Fail safe: an unreviewable ambiguous call is denied, not allowed.
        return SafetyResult(
            allowed=False,
            type=matched_review_rule.type,
            severity="medium",
            reason="Ambiguous call could not be reviewed (model unavailable); denied by default.",
            used_llm_fallback=True,
        )

    return SafetyResult(
        allowed=classification.allowed,
        type=matched_review_rule.type if not classification.allowed else None,
        severity="low" if not classification.allowed else None,
        reason=classification.reason,
        used_llm_fallback=True,
    )
