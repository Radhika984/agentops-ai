"""Phase 8 agents/cost_optimization.py tests.

analyze_model_usage()/recommend_routing_changes() read/reason over real
rows through the real ORM against the test database (via the shared
db_session fixture from conftest.py) — no mocking, matching
tests/test_monitoring.py's approach for the same kind of module (a pure
SQL-aggregation-plus-heuristics function with no external dependency to
mock). A minimal User -> Project -> Run chain is created directly via the
ORM to satisfy model_calls.run_id's FK, same as test_monitoring.py does
for flags.run_id.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.cost_optimization import analyze_model_usage, recommend_routing_changes
from app.core.config import settings
from app.models.model_call import ModelCall
from app.models.project import Project
from app.models.run import Run
from app.models.user import User

_PRIMARY = settings.GEMINI_MODEL
_FALLBACK = settings.GEMINI_FALLBACK_MODEL

pytestmark = pytest.mark.anyio


async def _make_run(
    session: AsyncSession, *, status: str = "succeeded"
) -> tuple[uuid.UUID, uuid.UUID]:
    """Returns (run_id, owner_id) — every ModelCall a test creates must
    also carry owner_id explicitly (see the 202609270001 migration):
    unlike run_id, it's never inferred from the run, since most real
    call sites (Suite Runner, RCA, ...) have no run at all."""
    user = User(email=f"{uuid.uuid4()}@example.com", hashed_password="not-a-real-hash")
    session.add(user)
    await session.flush()

    project = Project(name="Cost Test Project", owner_id=user.id)
    session.add(project)
    await session.flush()

    run = Run(project_id=project.id, goal="test goal", status=status, state={})
    session.add(run)
    await session.flush()

    return run.id, user.id


async def test_analyze_model_usage_with_no_calls(db_session: AsyncSession) -> None:
    stats = await analyze_model_usage(db_session, owner_id=uuid.uuid4())

    assert stats == []


async def test_analyze_model_usage_aggregates_by_agent_group_and_model(
    db_session: AsyncSession,
) -> None:
    run_id, owner_id = await _make_run(db_session)

    db_session.add_all(
        [
            ModelCall(
                run_id=run_id,
                owner_id=owner_id,
                agent="planner",
                model_group="reasoning",
                model=_PRIMARY,
                tokens_in=10,
                tokens_out=20,
                cost=0.0001,
                cache_hit=False,
            ),
            ModelCall(
                run_id=run_id,
                owner_id=owner_id,
                agent="planner",
                model_group="reasoning",
                model=_PRIMARY,
                tokens_in=12,
                tokens_out=18,
                cost=0.0002,
                cache_hit=False,
            ),
            ModelCall(
                run_id=run_id,
                owner_id=owner_id,
                agent="safety",
                model_group="judgment",
                model=_PRIMARY,
                tokens_in=5,
                tokens_out=5,
                cost=0.00005,
                cache_hit=True,
            ),
        ]
    )
    await db_session.flush()

    stats = await analyze_model_usage(db_session, owner_id=owner_id)
    by_agent = {s.agent: s for s in stats}

    assert by_agent["planner"].call_count == 2
    assert by_agent["planner"].cache_hit_count == 0
    assert round(by_agent["planner"].total_cost, 6) == 0.0003
    assert by_agent["planner"].avg_tokens_in == 11.0
    assert by_agent["planner"].run_success_rate == 1.0

    assert by_agent["safety"].call_count == 1
    assert by_agent["safety"].cache_hit_count == 1


async def test_analyze_model_usage_correlates_run_outcome(db_session: AsyncSession) -> None:
    failed_run_id, owner_id = await _make_run(db_session, status="failed")

    for _ in range(3):
        db_session.add(
            ModelCall(
                run_id=failed_run_id,
                owner_id=owner_id,
                agent="planner",
                model_group="reasoning",
                model=_FALLBACK,
                tokens_in=10,
                tokens_out=10,
                cost=0.0001,
                cache_hit=False,
            )
        )
    await db_session.flush()

    stats = await analyze_model_usage(db_session, owner_id=owner_id)

    assert len(stats) == 1
    assert stats[0].run_success_rate == 0.0


async def test_analyze_model_usage_leaves_unlinked_calls_with_no_success_rate(
    db_session: AsyncSession,
) -> None:
    # No run_id — e.g. the /ask endpoint's calls, which have no run
    # concept — but a real owner_id, exactly like the Suite Runner's own
    # rubric-judge/grounding calls (which likewise never have a run_id).
    # A real registered user: owner_id is a genuine FK to users.id.
    user = User(email=f"{uuid.uuid4()}@example.com", hashed_password="not-a-real-hash")
    db_session.add(user)
    await db_session.flush()
    owner_id = user.id
    db_session.add(
        ModelCall(
            run_id=None,
            owner_id=owner_id,
            agent="ask",
            model_group="reasoning",
            model=_PRIMARY,
            tokens_in=8,
            tokens_out=8,
            cost=0.0001,
            cache_hit=False,
        )
    )
    await db_session.flush()

    stats = await analyze_model_usage(db_session, owner_id=owner_id)

    assert stats[0].run_success_rate is None


def test_recommend_routing_changes_flags_heavy_fallback_usage() -> None:
    from app.agents.cost_optimization import ModelGroupStats

    stats = [
        ModelGroupStats(
            agent="planner",
            model_group="reasoning",
            model=_PRIMARY,
            call_count=4,
            cache_hit_count=0,
            total_cost=0.001,
            avg_tokens_in=10,
            avg_tokens_out=10,
            run_success_rate=1.0,
        ),
        ModelGroupStats(
            agent="planner",
            model_group="reasoning",
            model=_FALLBACK,
            call_count=6,
            cache_hit_count=0,
            total_cost=0.001,
            avg_tokens_in=10,
            avg_tokens_out=10,
            run_success_rate=1.0,
        ),
    ]

    recommendations = recommend_routing_changes(stats)

    assert len(recommendations) == 1
    assert recommendations[0].agent == "planner"
    assert "fell back" in recommendations[0].message


def test_recommend_routing_changes_flags_low_success_rate() -> None:
    from app.agents.cost_optimization import ModelGroupStats

    stats = [
        ModelGroupStats(
            agent="planner",
            model_group="reasoning",
            model=_PRIMARY,
            call_count=5,
            cache_hit_count=0,
            total_cost=0.001,
            avg_tokens_in=10,
            avg_tokens_out=10,
            run_success_rate=0.2,
        ),
    ]

    recommendations = recommend_routing_changes(stats)

    assert len(recommendations) == 1
    assert "succeeded only" in recommendations[0].message


def test_recommend_routing_changes_empty_for_healthy_usage() -> None:
    from app.agents.cost_optimization import ModelGroupStats

    stats = [
        ModelGroupStats(
            agent="planner",
            model_group="reasoning",
            model=_PRIMARY,
            call_count=10,
            cache_hit_count=0,
            total_cost=0.001,
            avg_tokens_in=10,
            avg_tokens_out=10,
            run_success_rate=1.0,
        ),
    ]

    assert recommend_routing_changes(stats) == []
