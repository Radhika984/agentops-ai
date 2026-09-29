"""Phase 7 agents/monitoring.py tests.

get_health_summary() reads real rows through the real ORM against the
test database (via the shared `db_session` fixture from conftest.py) —
no mocking, since this module's entire job is a SQL aggregation query and
the only meaningful thing to verify is that it's correct against real
rows. Flag rows carry a real FK to runs.id, so a minimal User -> Project
-> Run chain is created directly via the ORM first (this project's other
test files always go through the HTTP API instead, but monitoring.py has
no API endpoint of its own per its docstring's explicit scope note).
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.monitoring import get_health_summary
from app.models.flag import Flag
from app.models.project import Project
from app.models.run import Run
from app.models.user import User

pytestmark = pytest.mark.anyio


async def _make_run(session: AsyncSession) -> uuid.UUID:
    user = User(email=f"{uuid.uuid4()}@example.com", hashed_password="not-a-real-hash")
    session.add(user)
    await session.flush()

    project = Project(name="Monitoring Test Project", owner_id=user.id)
    session.add(project)
    await session.flush()

    run = Run(project_id=project.id, goal="test goal", status="succeeded", state={})
    session.add(run)
    await session.flush()

    return run.id


async def test_get_health_summary_with_no_flags(db_session: AsyncSession) -> None:
    summary = await get_health_summary(db_session)

    assert summary.total_flags == 0
    assert summary.by_agent == {}
    assert summary.by_severity == {}
    assert summary.high_severity_count == 0


async def test_get_health_summary_aggregates_by_agent_and_severity(
    db_session: AsyncSession,
) -> None:
    run_id = await _make_run(db_session)

    db_session.add_all(
        [
            Flag(
                run_id=run_id,
                agent="safety",
                type="destructive_filesystem",
                severity="high",
                details="rm -rf blocked",
            ),
            Flag(
                run_id=run_id,
                agent="safety",
                type="possible_malicious_intent",
                severity="low",
                details="ambiguous, allowed",
            ),
            Flag(
                run_id=run_id,
                agent="hallucination",
                type="unsupported_claim",
                severity="medium",
                details="fabricated address",
            ),
        ]
    )
    await db_session.flush()

    summary = await get_health_summary(db_session)

    assert summary.total_flags == 3
    assert summary.by_agent == {"safety": 2, "hallucination": 1}
    assert summary.by_severity == {"high": 1, "low": 1, "medium": 1}
    assert summary.high_severity_count == 1


async def test_get_health_summary_respects_limit(db_session: AsyncSession) -> None:
    run_id = await _make_run(db_session)

    db_session.add_all(
        [
            Flag(run_id=run_id, agent="safety", type="t", severity="high", details=f"flag {i}")
            for i in range(5)
        ]
    )
    await db_session.flush()

    summary = await get_health_summary(db_session, limit=2)

    assert summary.total_flags == 2
    assert summary.high_severity_count == 2
