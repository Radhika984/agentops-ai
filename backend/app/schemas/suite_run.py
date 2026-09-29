from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# A small, explicit cap — bounded concurrency against a real external
# agent, not "as many as the event loop will schedule." Matches the
# locked audit's own "a small cap e.g. 5" (Final Architecture Spec §16).
MAX_CONCURRENCY_LIMIT = 5


class SuiteRunCreate(BaseModel):
    agent_version_id: uuid.UUID
    max_concurrency: int = Field(default=1, ge=1, le=MAX_CONCURRENCY_LIMIT)


class SuiteRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    suite_id: uuid.UUID
    agent_version_id: uuid.UUID
    status: str
    started_at: datetime | None
    completed_at: datetime | None
    pass_count: int
    fail_count: int
    inconclusive_count: int
    skipped_count: int
    llm_judge_invocation_count: int
    max_concurrency: int
    created_at: datetime


class TestCaseResultRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    suite_run_id: uuid.UUID
    test_case_id: uuid.UUID
    verdict: str
    verdict_method: str
    checks: list[dict[str, Any]]
    trials: list[dict[str, Any]]
    actual_output: Any | None
    latency_ms: int | None
    error: str | None
    suggested_fix: str | None
    created_at: datetime
    updated_at: datetime
