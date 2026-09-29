"""Account-wide TestCaseResult listing — the "Evaluation" nav page (all
verdicts) and, with `verdicts=FAIL,INCONCLUSIVE`, the "RCA" nav page's
data source. See app/services/suite_run_service.py's
list_all_results_for_owner().
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.dashboard import TestCaseResultListResponse
from app.services.suite_run_service import SuiteRunService

router = APIRouter(prefix="/results", tags=["results"])

_VALID_VERDICTS = {"PASS", "FAIL", "INCONCLUSIVE"}


@router.get("", response_model=TestCaseResultListResponse)
async def list_results(
    verdicts: str | None = None,
    limit: int = 20,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> TestCaseResultListResponse:
    verdict_list: list[str] | None = None
    if verdicts:
        requested = [v.strip().upper() for v in verdicts.split(",") if v.strip()]
        verdict_list = [v for v in requested if v in _VALID_VERDICTS] or None

    items, total = await SuiteRunService(session).list_all_results_for_owner(
        owner_id=current_user.id,
        limit=min(limit, 100),
        offset=max(offset, 0),
        verdicts=verdict_list,
    )
    return TestCaseResultListResponse(items=items, total=total)
