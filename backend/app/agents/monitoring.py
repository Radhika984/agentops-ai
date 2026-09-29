"""Monitoring: continuous health signal for the system.

Per the blueprint's Part 1 spec ("Threshold + anomaly-detection rules on
the metrics stream... alerts humans, doesn't act"): a simple, testable
summary over the flags table (Safety blocks + Hallucination findings) —
a spike in high-severity flags across recent runs is exactly the kind of
threshold signal Monitoring is meant to surface.

Scope note: Phase 7 implements this as a standalone, tested function, not
a new API endpoint or a background alerting process — the blueprint's
explicit Phase 7 frontend deliverable is the Run Trace view, not a
monitoring dashboard, and an always-running alerting system belongs with
observability infrastructure that's genuinely needed yet, not invented
ahead of a real caller.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.flag import Flag


@dataclass
class HealthSummary:
    total_flags: int
    by_agent: dict[str, int]
    by_severity: dict[str, int]
    high_severity_count: int


async def get_health_summary(session: AsyncSession, *, limit: int = 100) -> HealthSummary:
    """Summarizes the most recent `limit` flags across all runs."""
    result = await session.execute(select(Flag).order_by(Flag.created_at.desc()).limit(limit))
    flags = list(result.scalars().all())

    by_agent = Counter(f.agent for f in flags)
    by_severity = Counter(f.severity for f in flags)

    return HealthSummary(
        total_flags=len(flags),
        by_agent=dict(by_agent),
        by_severity=dict(by_severity),
        high_severity_count=by_severity.get("high", 0),
    )
