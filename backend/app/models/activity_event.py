from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDMixin

# The whitelist of real product events this app ever records — deliberately
# not open-ended. Each one corresponds to an actual mutating action already
# happening somewhere in the app (see app/services/activity_service.py's
# record() call sites); nothing here is a read/GET being relabeled as an
# "event". RCA is intentionally absent: computing RCA is an idempotent read
# (GET .../rca), not a one-time occurrence, so logging it would misrepresent
# a recomputation as a fresh "analysis completed" event.
ACTIVITY_EVENT_TYPES = (
    "suite_run_completed",
    "release_gate_evaluated",
    "autofix_proposed",
    "approval_decided",
    "agent_version_created",
    "agent_version_promoted",
)


class ActivityEvent(UUIDMixin, Base):
    """A real, persisted product event, owned by the User whose project the
    event happened under — the data source for the dashboard's Recent
    Activity feed and the Release Gate / AutoFix nav pages' event lists.

    `owner_id` is denormalized directly onto this row (not derived via a
    join every read) deliberately: unlike Approval/TestCaseResult (which
    always have a live parent chain to join through), an activity event
    must remain readable forever even if the event describes something on
    an entity chain, and a direct owner_id column is also what makes the
    dashboard's "recent activity" query a single indexed lookup instead of
    a multi-table join on every page load.

    `entity_type`/`entity_id` point at whatever row the event is about
    (e.g. "suite_run"/<uuid>) — informational only, no FK constraint,
    since the referenced row's own table has the real FK/CASCADE rules;
    an activity record is a historical fact and must survive even if the
    entity it describes is later deleted (deleting a SuiteRun should not
    silently rewrite "what happened" history).
    """

    __tablename__ = "activity_events"

    owner_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    entity_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    event_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
