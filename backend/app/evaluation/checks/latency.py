"""Deterministic latency comparison. Called only when
TestCase.latency_threshold_ms is set — the engine (engine.py) never
invokes this otherwise, so "no threshold configured" naturally means "no
latency check," with no special-casing needed here.

`latency_ms` is typed `int | None` here (not the stricter `int` Phase
10's AgentExecution guarantees) so this check stays correct and
independently testable even for a hypothetically incomplete execution
record — "missing latency should not PASS."
"""

from __future__ import annotations

from app.evaluation.models import Check, CheckStatus, Determinism

CHECK_TYPE = "latency"


def check_latency(threshold_ms: int, latency_ms: int | None) -> Check:
    if latency_ms is None:
        return Check(
            check_type=CHECK_TYPE,
            status=CheckStatus.FAIL,
            determinism=Determinism.DETERMINISTIC,
            detail="actual latency is missing; cannot evaluate against latency_threshold_ms",
        )

    if latency_ms <= threshold_ms:
        return Check(
            check_type=CHECK_TYPE,
            status=CheckStatus.PASS,
            determinism=Determinism.DETERMINISTIC,
            detail=f"latency {latency_ms}ms is within the {threshold_ms}ms threshold",
        )
    return Check(
        check_type=CHECK_TYPE,
        status=CheckStatus.FAIL,
        determinism=Determinism.DETERMINISTIC,
        detail=f"latency {latency_ms}ms exceeds the {threshold_ms}ms threshold",
    )
