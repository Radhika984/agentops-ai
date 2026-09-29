"""Phase 19 — AutoFix: pure validation for applying an approved proposal.

No database access, no LLM, no code execution of any kind — these are
plain whitelist membership checks. app/services/autofix_service.py calls
these immediately before ever writing anything, as the last line of
defense (in addition to the fact that build_autofix_proposal() in
app/autofix/proposal.py only ever emits whitelisted fields itself) —
an approved proposal's field name is validated again here because the
proposal payload round-trips through Approval.reason as JSON text
between propose time and apply time, and this module treats that text
as untrusted input, not as something already known-safe.
"""

from __future__ import annotations

from app.autofix.proposal import (
    AGENT_DEFAULT_EDITABLE_FIELDS,
    MAX_AUTOFIX_TRIAL_COUNT,
    TESTCASE_EDITABLE_FIELDS,
)
from app.core.exceptions import ValidationError


def validate_testcase_field(field: str) -> None:
    if field not in TESTCASE_EDITABLE_FIELDS:
        raise ValidationError(
            f"AutoFix cannot edit TestCase field {field!r} — not in the allowed whitelist "
            f"{sorted(TESTCASE_EDITABLE_FIELDS)}"
        )


def validate_agent_field(field: str) -> None:
    if field not in AGENT_DEFAULT_EDITABLE_FIELDS:
        raise ValidationError(
            f"AutoFix cannot edit Agent field {field!r} — not in the allowed whitelist "
            f"{sorted(AGENT_DEFAULT_EDITABLE_FIELDS)}"
        )


def bound_trial_count(proposed: int) -> int:
    """Always clamps to the explicit, bounded maximum — never trusts a
    proposal payload's own number unconditionally, however it was
    produced or edited in transit."""
    return min(max(int(proposed), 1), MAX_AUTOFIX_TRIAL_COUNT)
