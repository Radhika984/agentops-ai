"""OpenTelemetry setup + custom span helpers.

Real OTel — a genuine TracerProvider, real spans with real start/end
timestamps — not a hand-rolled timer. There's no external tracing backend
(Jaeger/Honeycomb/etc.) here: that would mean either a paid service or
standing up more infrastructure than a "basic Run Trace view" (the
blueprint's own words for Phase 7's frontend) actually needs. Instead, a
custom in-memory SpanExporter captures finished spans, and
get_spans_for_run() reads them back out — enough to build a real,
per-run, agent-by-agent timeline without adding paid or heavyweight
infrastructure.

Spans are associated with a run via a contextvar (`current_run_id`), not
by threading a run_id through AgentState — asyncio contextvars are
isolated per-Task, so concurrent runs (multiple BackgroundTasks in
flight at once) never mix up each other's spans, without every node
needing to know its own run_id.
"""

from __future__ import annotations

import contextvars
from collections import defaultdict
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import TypedDict

from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.trace import Span

current_run_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "current_run_id", default=None
)


class TraceSpanRecord(TypedDict):
    name: str
    start_time_ns: int
    duration_ms: float


class _InMemoryRunSpanExporter(SpanExporter):
    """Collects finished spans, keyed by their `run_id` attribute."""

    def __init__(self) -> None:
        self.spans_by_run: dict[str, list[ReadableSpan]] = defaultdict(list)

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        for span in spans:
            run_id = (span.attributes or {}).get("run_id")
            if isinstance(run_id, str):
                self.spans_by_run[run_id].append(span)
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        pass


_exporter = _InMemoryRunSpanExporter()
_provider = TracerProvider()
_provider.add_span_processor(SimpleSpanProcessor(_exporter))
tracer = _provider.get_tracer("agentops")


@contextmanager
def traced_node(name: str) -> Iterator[Span]:
    """Wraps one agent node's execution in a real OTel span, tagged with
    the current run_id (if set) so it can be retrieved later via
    get_spans_for_run()."""
    run_id = current_run_id.get()
    with tracer.start_as_current_span(name) as span:
        if run_id is not None:
            span.set_attribute("run_id", run_id)
        yield span


def get_spans_for_run(run_id: str) -> list[TraceSpanRecord]:
    """Returns this run's spans in the order they completed — for a
    strictly sequential graph (planner -> evaluation -> hallucination ->
    verification, looping back to planner on retry), that's also
    execution order, giving a correct agent-by-agent timeline."""
    spans = _exporter.spans_by_run.get(run_id, [])
    return [
        TraceSpanRecord(
            name=span.name,
            start_time_ns=span.start_time or 0,
            duration_ms=round(((span.end_time or 0) - (span.start_time or 0)) / 1_000_000, 3),
        )
        for span in spans
    ]


def clear_spans_for_run(run_id: str) -> None:
    """Frees the in-memory record for a run once its trace has been
    persisted — see run_service.py. Without this, spans_by_run would grow
    unboundedly for the lifetime of the process."""
    _exporter.spans_by_run.pop(run_id, None)
