"""Phase 19 — AutoFix proposal response schema.

Computed on read/write of the existing Approval/TestCaseResult rows —
nothing new is persisted beyond those (no AutoFixResult/AutoFixApproval
table; see app/services/autofix_service.py's own docstring).
"""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel

from app.autofix.proposal import AutoFixOption


class AutoFixProposalRead(BaseModel):
    option: AutoFixOption
    rca_category: str | None
    field: str | None
    current_value: Any | None
    proposed_value: Any | None
    rationale: str
    requires_approval: bool
    # Set only for Options 1-3 (requires_approval=True) — the pending
    # Approval row a human must approve/reject via the existing
    # POST /approvals/{id}/decide endpoint before anything is applied.
    approval_id: uuid.UUID | None
    # Set only for Option 4 — TestCaseResult.suggested_fix was written,
    # explicitly prefixed "[NOT APPLIED]"; nothing else changed.
    suggested_fix_recorded: bool
