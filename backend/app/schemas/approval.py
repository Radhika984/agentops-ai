from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ApprovalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    # Phase 18: exactly one of run_id/suite_run_id is set (DB CHECK
    # constraint) — both nullable here so this one schema serves both
    # the legacy Run approval queue and the new SuiteRun Release Gate
    # approvals through the same GET /approvals endpoint.
    run_id: uuid.UUID | None
    suite_run_id: uuid.UUID | None
    node: str
    status: str
    reason: str | None
    requested_at: datetime
    decided_by: uuid.UUID | None
    decided_at: datetime | None


class ApprovalDecide(BaseModel):
    approved: bool
    reason: str | None = Field(default=None, max_length=2000)


class ReleaseSnapshotRead(BaseModel):
    status: str
    root_cause: str | None
    root_cause_pattern: str | None
    auto_fix_proposed_task: str | None
    auto_fix_applied: bool
    hard_gate_passed: bool | None
    soft_score: float | None
    soft_score_components: dict[str, float]
    decision: Literal["ship", "hold", "rollback"] | None
    reason: str | None
