from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user
from app.db.session import get_db
from app.models.activity_event import ActivityEvent
from app.models.user import User
from app.schemas.activity import ActivityEventRead
from app.services.activity_service import ActivityService

router = APIRouter(prefix="/activity", tags=["activity"])


@router.get("", response_model=list[ActivityEventRead])
async def list_activity(
    limit: int = 20,
    event_type: str | None = None,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> list[ActivityEvent]:
    """`event_type` powers the Release Gate ("release_gate_evaluated")
    and AutoFix ("autofix_proposed") nav pages — a filtered view of this
    same real event log, not a second data source."""
    return await ActivityService(session).list_recent(
        current_user.id, limit=min(limit, 100), event_type=event_type
    )
