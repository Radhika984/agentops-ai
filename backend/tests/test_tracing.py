"""Phase 7 observability/tracing.py tests.

Uses the module's real TracerProvider/exporter (a fresh in-process,
in-memory pipeline — no network, no external collector), so these tests
exercise genuine OTel span creation and export, not a mock. Concurrency
safety is verified by actually running two "runs" concurrently via
asyncio.gather() and checking their spans never cross — contextvars are
per-task, so this is the real mechanism the graph relies on in
run_service.py, not a simulated one.
"""

from __future__ import annotations

import asyncio

import pytest

from app.observability import tracing

pytestmark = pytest.mark.anyio


def test_get_spans_for_run_returns_empty_list_for_unknown_run() -> None:
    assert tracing.get_spans_for_run("no-such-run") == []


def test_traced_node_without_a_run_id_does_not_raise() -> None:
    # current_run_id defaults to None outside of run_graph_and_persist's
    # scoping — traced_node must still work (just produces an unassociated
    # span that no run_id lookup will ever retrieve).
    with tracing.traced_node("standalone"):
        pass


async def test_traced_node_records_a_span_for_the_current_run() -> None:
    run_id = "test-run-1"
    token = tracing.current_run_id.set(run_id)
    try:
        with tracing.traced_node("planner"):
            pass
        with tracing.traced_node("evaluation"):
            pass
    finally:
        tracing.current_run_id.reset(token)

    spans = tracing.get_spans_for_run(run_id)

    assert [s["name"] for s in spans] == ["planner", "evaluation"]
    assert all(s["duration_ms"] >= 0 for s in spans)
    assert all(s["start_time_ns"] > 0 for s in spans)

    tracing.clear_spans_for_run(run_id)


def test_clear_spans_for_run_removes_the_record() -> None:
    run_id = "test-run-2"
    token = tracing.current_run_id.set(run_id)
    try:
        with tracing.traced_node("verification"):
            pass
    finally:
        tracing.current_run_id.reset(token)

    assert tracing.get_spans_for_run(run_id) != []

    tracing.clear_spans_for_run(run_id)

    assert tracing.get_spans_for_run(run_id) == []


def test_clear_spans_for_run_is_safe_on_unknown_run() -> None:
    tracing.clear_spans_for_run("never-existed")  # does not raise


async def test_concurrent_runs_spans_do_not_cross() -> None:
    async def do_run(run_id: str, node_name: str) -> None:
        token = tracing.current_run_id.set(run_id)
        try:
            with tracing.traced_node(node_name):
                await asyncio.sleep(0)  # yield control, mimicking real interleaving
        finally:
            tracing.current_run_id.reset(token)

    await asyncio.gather(
        do_run("run-a", "planner"),
        do_run("run-b", "verification"),
    )

    spans_a = tracing.get_spans_for_run("run-a")
    spans_b = tracing.get_spans_for_run("run-b")

    assert [s["name"] for s in spans_a] == ["planner"]
    assert [s["name"] for s in spans_b] == ["verification"]

    tracing.clear_spans_for_run("run-a")
    tracing.clear_spans_for_run("run-b")
