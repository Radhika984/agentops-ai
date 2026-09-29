"""Cost optimization: analyzes historical model usage from model_calls,
recommends routing changes.

Scope note: the blueprint's own phrasing is "analyzes historical
accuracy-per-model-per-task-type" — but this project's schema (per the
blueprint's own model_calls columns: agent, model, tokens_in, tokens_out,
cost, cache_hit, created_at) captures no correctness/accuracy label, and
Google's Free Tier only actually resolves two real, distinct model ids
for this account (see app/ai/router.py's docstring — most candidate
alternative Gemini models return 404 under this API key), so there's
little genuine "accuracy per model" variance to mine even if a label
existed. This instead analyzes the real signals actually captured: cost,
call volume, and fallback frequency per (agent, model_group, model), plus
one real outcome proxy this project *does* have — model_calls.run_id
(a Phase 8 addition to the blueprint's minimum schema, see
models/model_call.py) lets a call be correlated with whether the run it
belonged to ultimately succeeded, which is the closest thing to a real
"did this model's output actually work" signal in the data, rather than
a fabricated accuracy score.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.router import MODEL_GROUPS
from app.models.model_call import ModelCall
from app.models.run import Run

# Below this many calls, per-model success/fallback signals are too noisy
# to act on — avoids recommending a routing change off a single unlucky
# call.
_MIN_SAMPLE_SIZE = 3


@dataclass
class ModelGroupStats:
    agent: str
    model_group: str
    model: str
    call_count: int
    cache_hit_count: int
    total_cost: float
    avg_tokens_in: float
    avg_tokens_out: float
    # None when none of this (agent, model_group, model)'s calls were
    # linked to a run (e.g. agent="ask", which has no run concept).
    run_success_rate: float | None


@dataclass
class CostRecommendation:
    agent: str
    model_group: str
    message: str


@dataclass
class UsageReport:
    stats: list[ModelGroupStats] = field(default_factory=list)
    recommendations: list[CostRecommendation] = field(default_factory=list)


async def analyze_model_usage(
    session: AsyncSession, *, owner_id: uuid.UUID, limit: int = 1000
) -> list[ModelGroupStats]:
    """Aggregates the most recent `limit` model_calls rows belonging to
    `owner_id`, by (agent, model_group, model).

    Filtered on ModelCall.owner_id directly (populated at write time —
    see app/ai/client.py's current_owner_id / owner_call_context), not
    joined through Run: Run only exists for the legacy Run-graph's own
    calls, so scoping through it alone would silently exclude every
    modern call site's real rows (Suite Runner, RCA, ...) for their true
    owner too, not just block other users' data. A row with no owner_id
    (written before this scoping existed) matches no one, deliberately —
    never guessed or shown to whoever happens to ask first."""
    result = await session.execute(
        select(ModelCall, Run.status)
        .outerjoin(Run, ModelCall.run_id == Run.id)
        .where(ModelCall.owner_id == owner_id)
        .order_by(ModelCall.created_at.desc())
        .limit(limit)
    )
    rows = result.all()

    groups: dict[tuple[str, str, str], list[tuple[ModelCall, str | None]]] = defaultdict(list)
    for call, run_status in rows:
        groups[(call.agent, call.model_group, call.model)].append((call, run_status))

    stats: list[ModelGroupStats] = []
    for (agent, model_group, model), items in groups.items():
        calls = [c for c, _ in items]
        run_statuses = [s for _, s in items if s is not None]

        stats.append(
            ModelGroupStats(
                agent=agent,
                model_group=model_group,
                model=model,
                call_count=len(calls),
                cache_hit_count=sum(1 for c in calls if c.cache_hit),
                total_cost=sum(float(c.cost) for c in calls),
                avg_tokens_in=sum(c.tokens_in for c in calls) / len(calls),
                avg_tokens_out=sum(c.tokens_out for c in calls) / len(calls),
                run_success_rate=(
                    sum(1 for s in run_statuses if s == "succeeded") / len(run_statuses)
                    if run_statuses
                    else None
                ),
            )
        )

    return stats


def recommend_routing_changes(stats: list[ModelGroupStats]) -> list[CostRecommendation]:
    """Two real, grounded heuristics — no fabricated accuracy score:

    1. Fallback frequency: if a group's *non-primary* model accounts for
       a meaningful share of its calls, the primary is failing often
       enough to be worth investigating (that's the whole point of
       tracking which model actually served each call).
    2. Run-outcome correlation: if calls attributed to a given model
       correlate with a low run success rate (and there's enough volume
       to trust it), that's a real signal worth surfacing — even though
       it's a correlation, not a controlled comparison.
    """
    recommendations: list[CostRecommendation] = []

    by_group: dict[tuple[str, str], list[ModelGroupStats]] = defaultdict(list)
    for s in stats:
        by_group[(s.agent, s.model_group)].append(s)

    for (agent, model_group), group_stats in by_group.items():
        primary = MODEL_GROUPS.get(model_group, [None])[0]
        total_calls = sum(s.call_count for s in group_stats)

        for s in group_stats:
            if s.model == "cache":
                continue

            # Fallback-share only makes sense for a *non-primary* model —
            # "the primary fell back to itself" isn't a real finding. The
            # success-rate check below is deliberately not skipped here:
            # a low run-success rate is just as much a real finding when
            # it's the *primary* model doing badly.
            if s.model != primary and s.call_count >= _MIN_SAMPLE_SIZE and total_calls > 0:
                fallback_share = s.call_count / total_calls
                if fallback_share >= 0.2:
                    recommendations.append(
                        CostRecommendation(
                            agent=agent,
                            model_group=model_group,
                            message=(
                                f"'{primary}' fell back to '{s.model}' on "
                                f"{fallback_share:.0%} of {agent}'s '{model_group}' calls "
                                f"({s.call_count}/{total_calls}) — investigate '{primary}' "
                                "reliability."
                            ),
                        )
                    )

            if (
                s.run_success_rate is not None
                and s.call_count >= _MIN_SAMPLE_SIZE
                and s.run_success_rate < 0.5
            ):
                recommendations.append(
                    CostRecommendation(
                        agent=agent,
                        model_group=model_group,
                        message=(
                            f"Runs using '{s.model}' for {agent} succeeded only "
                            f"{s.run_success_rate:.0%} of the time across {s.call_count} "
                            f"linked calls — consider routing {agent}'s '{model_group}' "
                            f"group away from '{s.model}'."
                        ),
                    )
                )

    return recommendations


async def build_usage_report(
    session: AsyncSession, *, owner_id: uuid.UUID, limit: int = 1000
) -> UsageReport:
    stats = await analyze_model_usage(session, owner_id=owner_id, limit=limit)
    return UsageReport(stats=stats, recommendations=recommend_routing_changes(stats))
