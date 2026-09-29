from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.search import SearchResponse
from app.services.search_service import SearchService

router = APIRouter(prefix="/search", tags=["search"])


@router.get("", response_model=SearchResponse)
async def search(
    q: str = "",
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> SearchResponse:
    return await SearchService(session).search(owner_id=current_user.id, query=q)
