from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity_event import ActivityEvent


class ActivityEventRepository:
    """Database access for the Recent Activity feed. No ownership rules
    beyond the plain owner_id column filter (this table denormalizes
    owner_id directly onto every row — see the model's own docstring for
    why — so there is no join-based ownership chain to encode here, unlike
    ApprovalRepository/SuiteRunRepository)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        owner_id: uuid.UUID,
        event_type: str,
        title: str,
        description: str | None,
        entity_type: str | None,
        entity_id: uuid.UUID | None,
        metadata: dict[str, Any],
    ) -> ActivityEvent:
        event = ActivityEvent(
            owner_id=owner_id,
            event_type=event_type,
            title=title,
            description=description,
            entity_type=entity_type,
            entity_id=entity_id,
            event_metadata=metadata,
        )
        self._session.add(event)
        await self._session.flush()
        return event

    async def exists(
        self, *, owner_id: uuid.UUID, event_type: str, entity_id: uuid.UUID, title: str
    ) -> bool:
        """Dedupe check for events that describe a recomputable fact
        (e.g. a Release Gate re-evaluated with the same decision) — used
        so repeatedly re-checking something idempotent doesn't flood the
        activity feed with identical rows. Keyed on title (not just
        event_type/entity_id) deliberately: a *changed* outcome (e.g.
        hold -> pass on re-evaluation after a fix) has a different title
        and is therefore still recorded as the new, real event it is."""
        result = await self._session.execute(
            select(ActivityEvent.id).where(
                ActivityEvent.owner_id == owner_id,
                ActivityEvent.event_type == event_type,
                ActivityEvent.entity_id == entity_id,
                ActivityEvent.title == title,
            )
        )
        return result.scalar_one_or_none() is not None

    async def list_for_owner(
        self, owner_id: uuid.UUID, *, limit: int = 20, event_type: str | None = None
    ) -> list[ActivityEvent]:
        query = (
            select(ActivityEvent)
            .where(ActivityEvent.owner_id == owner_id)
            .order_by(ActivityEvent.created_at.desc())
            .limit(limit)
        )
        if event_type is not None:
            query = query.where(ActivityEvent.event_type == event_type)
        result = await self._session.execute(query)
        return list(result.scalars().all())

    async def count_release_gate_holds_for_owner(self, owner_id: uuid.UUID) -> int:
        """The dashboard's "Release Gate Holds" stat tile — counts
        distinct SuiteRuns with a "Release Gate Held" activity event for
        this owner. Release Gate evaluation has no dedicated persisted
        "decision" column on SuiteRun itself; this activity log IS the
        durable record of that fact (see app/services/activity_service.py
        and app/services/release_gate_service.py's dedupe='True' record()
        call)."""
        result = await self._session.execute(
            select(func.count(func.distinct(ActivityEvent.entity_id))).where(
                ActivityEvent.owner_id == owner_id,
                ActivityEvent.event_type == "release_gate_evaluated",
                ActivityEvent.title == "Release Gate Held",
            )
        )
        return int(result.scalar_one())
