"""Home dashboard — every response here is computed live from real,
owner-scoped data (see app/services/dashboard_service.py's own module
docstring). No endpoint in this router accepts write access; all four
are plain, ownership-scoped reads.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.dashboard import (
    DashboardStats,
    PerformanceOverview,
    SuiteRunListResponse,
    VerdictDistribution,
)
from app.services.dashboard_service import DEFAULT_PERFORMANCE_WINDOW_DAYS, DashboardService

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/stats", response_model=DashboardStats)
async def get_stats(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> DashboardStats:
    return await DashboardService(session).get_stats(current_user.id)


@router.get("/recent-suite-runs", response_model=SuiteRunListResponse)
async def get_recent_suite_runs(
    limit: int = 20,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> SuiteRunListResponse:
    return await DashboardService(session).get_recent_suite_runs(
        current_user.id, limit=min(limit, 100), offset=max(offset, 0)
    )


@router.get("/verdict-distribution", response_model=VerdictDistribution)
async def get_verdict_distribution(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> VerdictDistribution:
    return await DashboardService(session).get_verdict_distribution(current_user.id)


@router.get("/performance", response_model=PerformanceOverview)
async def get_performance_overview(
    days: int = DEFAULT_PERFORMANCE_WINDOW_DAYS,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> PerformanceOverview:
    # Clamped, not rejected — an out-of-range request degrades to the
    # nearest sane window rather than a 422 for what is, in every case,
    # a harmless read.
    bounded_days = max(1, min(days, 90))
    return await DashboardService(session).get_performance_overview(
        current_user.id, days=bounded_days
    )
