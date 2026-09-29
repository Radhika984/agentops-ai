"""GET /api/v1/cost — the cost dashboard's data source.

Not project-scoped (an agent/run's model usage isn't owned by any one
project), but it IS owner-scoped: build_usage_report() filters to
current_user.id, since a fresh account with no calls of its own must
never see another account's usage/spend. See
app/agents/cost_optimization.py and the 202609270001 migration for how
each model_calls row gets attributed to an owner at write time.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.cost_optimization import build_usage_report
from app.api.v1.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.cost import CostRecommendationRead, ModelGroupStatsRead, UsageReportRead

router = APIRouter(prefix="/cost", tags=["cost"])


@router.get("", response_model=UsageReportRead)
async def get_cost_dashboard(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> UsageReportRead:
    report = await build_usage_report(session, owner_id=current_user.id)
    # Built explicitly from the dataclasses rather than via
    # UsageReportRead.model_validate(report, from_attributes=True):
    # from_attributes on a nested-list field isn't guaranteed to cascade
    # to each list item's own (unconfigured) model the way a single
    # from_attributes=True model_config on each Read schema would — this
    # sidesteps that ambiguity entirely.
    return UsageReportRead(
        stats=[ModelGroupStatsRead(**vars(s)) for s in report.stats],
        recommendations=[CostRecommendationRead(**vars(r)) for r in report.recommendations],
    )
