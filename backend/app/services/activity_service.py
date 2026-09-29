"""Recent Activity — real, persisted product events.

A thin, additive service other services call (never the other way
around) right after a real mutating action they already commit — see
each call site's own comment for exactly which action. Never invoked
from a GET/read path: recording an event for something idempotent and
re-computable (an RCA read, a plain "list my approvals" call) would
misrepresent a recomputation as a fresh occurrence, so this module is
only ever called from the six real event points enumerated in
app/models/activity_event.py's ACTIVITY_EVENT_TYPES.

Respects each user's own notification preferences (app/models/user.py's
notify_on_* columns) — the one real, verifiable effect those preferences
have, since this app has no email/push delivery system to gate instead.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity_event import ActivityEvent
from app.models.agent import Agent
from app.models.project import Project
from app.models.test_suite import TestSuite
from app.repositories.activity_event_repository import ActivityEventRepository
from app.repositories.user_repository import UserRepository

# event_type -> the User preference column gating it. Anything absent
# from this map (agent_version_created/agent_version_promoted) is always
# recorded — there is no dedicated preference toggle for those in the
# reference's notification vocabulary, and they are low-volume, clearly
# deliberate actions a user always wants a record of.
_PREFERENCE_FIELD: dict[str, str] = {
    "suite_run_completed": "notify_on_suite_run_complete",
    "release_gate_evaluated": "notify_on_release_gate",
    "autofix_proposed": "notify_on_autofix_proposed",
    "approval_decided": "notify_on_approval_decided",
}


class ActivityService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._events = ActivityEventRepository(session)
        self._users = UserRepository(session)

    async def record(
        self,
        *,
        owner_id: uuid.UUID,
        event_type: str,
        title: str,
        description: str | None = None,
        entity_type: str | None = None,
        entity_id: uuid.UUID | None = None,
        metadata: dict[str, Any] | None = None,
        dedupe: bool = False,
    ) -> ActivityEvent | None:
        """Returns the created row, or None if suppressed by the user's
        own preference or a dedupe match — never raises: a failure to
        record activity must never be allowed to break the real action
        that triggered it (see every call site, which calls this only
        after its own primary write has already committed)."""
        preference_field = _PREFERENCE_FIELD.get(event_type)
        if preference_field is not None:
            user = await self._users.get_by_id(owner_id)
            if user is not None and not getattr(user, preference_field):
                return None

        if dedupe and entity_id is not None:
            already_exists = await self._events.exists(
                owner_id=owner_id, event_type=event_type, entity_id=entity_id, title=title
            )
            if already_exists:
                return None

        event = await self._events.create(
            owner_id=owner_id,
            event_type=event_type,
            title=title,
            description=description,
            entity_type=entity_type,
            entity_id=entity_id,
            metadata=metadata or {},
        )
        await self._session.commit()
        return event

    async def list_recent(
        self, owner_id: uuid.UUID, *, limit: int = 20, event_type: str | None = None
    ) -> list[ActivityEvent]:
        return await self._events.list_for_owner(owner_id, limit=limit, event_type=event_type)


async def resolve_suite_run_owner_id(
    session: AsyncSession, suite_id: uuid.UUID
) -> uuid.UUID | None:
    """SuiteRun -> TestSuite -> Agent -> Project -> owner_id, the exact
    join app/repositories/approval_repository.py's list_for_owner_suite_run()
    already established for the identical chain — reused here (not
    reimplemented) since suite_runner.py's background task has only a
    `suite_id`, never an owner_id, at the point it needs to record an
    activity event."""
    result = await session.execute(
        select(Project.owner_id)
        .join(Agent, Agent.project_id == Project.id)
        .join(TestSuite, TestSuite.agent_id == Agent.id)
        .where(TestSuite.id == suite_id)
    )
    return result.scalar_one_or_none()
