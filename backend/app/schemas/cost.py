from __future__ import annotations

from pydantic import BaseModel


class ModelGroupStatsRead(BaseModel):
    agent: str
    model_group: str
    model: str
    call_count: int
    cache_hit_count: int
    total_cost: float
    avg_tokens_in: float
    avg_tokens_out: float
    run_success_rate: float | None


class CostRecommendationRead(BaseModel):
    agent: str
    model_group: str
    message: str


class UsageReportRead(BaseModel):
    # This project is Free Tier only — Google does not bill these calls.
    # `total_cost`/`cost` figures are litellm's notional per-token cost
    # estimate for the model actually used (see ai/router.py's
    # docstring), useful for spotting *relative* cost/volume patterns —
    # never a real charge.
    stats: list[ModelGroupStatsRead]
    recommendations: list[CostRecommendationRead]
