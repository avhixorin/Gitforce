from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
)

from gitforce.app.config.settings import get_settings

logger = logging.getLogger(__name__)

_DEFAULT_TRACER = trace.get_tracer("gitforce")
_INITIALIZED = False


def init_tracing() -> TracerProvider:
    """Configure the OpenTelemetry SDK from settings. Returns the provider.

    Always installs the in-process DashboardSpanProcessor so agent
    execution spans are captured for the visualization dashboard at zero
    external cost. When ``otel_enabled`` is set, spans are additionally
    exported (OTLP endpoint or console fallback).
    """
    global _INITIALIZED
    settings = get_settings()

    if _INITIALIZED:
        return trace.get_tracer_provider()  # type: ignore[return-value]

    resource = Resource.create(
        {"service.name": "gitforce", "service.version": "0.1.0"}
    )
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(DashboardSpanProcessor())

    if settings.otel_enabled:
        if settings.otel_exporter_otlp_endpoint:
            try:
                from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                    OTLPSpanExporter,
                )

                exporter = OTLPSpanExporter(
                    endpoint=settings.otel_exporter_otlp_endpoint
                )
                provider.add_span_processor(BatchSpanProcessor(exporter))
            except Exception as exc:  # noqa: BLE001
                logger.warning("OTLP exporter unavailable, using console: %s", exc)
                provider.add_span_processor(
                    SimpleSpanProcessor(ConsoleSpanExporter())
                )
        else:
            provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))

    trace.set_tracer_provider(provider)
    _INITIALIZED = True
    return provider


def get_tracer(name: str = "gitforce"):
    return trace.get_tracer(name)


@dataclass
class SpanInfo:
    """Lightweight, JSON-friendly snapshot of a completed span used by the
    agent execution visualization dashboard (Phase 11)."""

    name: str
    trace_id: str
    span_id: str
    parent_span_id: str | None
    start_time_ns: int
    end_time_ns: int
    duration_ms: float
    attributes: dict[str, Any] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)
    status: str = "ok"

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "start_time_ns": self.start_time_ns,
            "end_time_ns": self.end_time_ns,
            "duration_ms": round(self.duration_ms, 2),
            "attributes": self.attributes,
            "events": self.events,
            "status": self.status,
        }


class SpanRecorder:
    """In-process collector of completed spans for the dashboard.

    Keeps the most recent ``max_spans`` per trace so the UI can rebuild
    an execution timeline without a full tracing backend.
    """

    def __init__(self, max_spans: int = 5000) -> None:
        self._spans: dict[str, list[SpanInfo]] = {}
        self._order: list[str] = []
        self._max_spans = max_spans

    def record(self, span: ReadableSpan) -> None:
        trace_id = format(span.context.trace_id, "032x")
        parent = None
        if span.parent is not None:
            parent = format(span.parent.span_id, "016x")
        start_time = span.start_time or 0
        end_time = span.end_time or start_time
        duration_ms = (end_time - start_time) / 1_000_000
        status = "ok"
        if span.status is not None and span.status.status_code != 0:
            status = span.status.status_code.name.lower()
        info = SpanInfo(
            name=span.name,
            trace_id=trace_id,
            span_id=format(span.context.span_id, "016x"),
            parent_span_id=parent,
            start_time_ns=start_time,
            end_time_ns=end_time,
            duration_ms=duration_ms,
            attributes=dict(span.attributes or {}),
            events=[
                {
                    "name": e.name,
                    "timestamp_ns": e.timestamp,
                    "attributes": dict(e.attributes or {}),
                }
                for e in span.events or []
            ],
            status=status,
        )
        spans = self._spans.setdefault(trace_id, [])
        if len(spans) >= self._max_spans:
            return
        spans.append(info)
        self._order.append(trace_id)

    def spans_for(self, trace_id: str) -> list[SpanInfo]:
        return list(self._spans.get(trace_id, []))

    def recent_traces(self, limit: int = 50) -> list[str]:
        seen: list[str] = []
        for trace_id in reversed(self._order):
            if trace_id not in seen:
                seen.append(trace_id)
            if len(seen) >= limit:
                break
        return seen

    def clear(self, trace_id: str | None = None) -> None:
        if trace_id is None:
            self._spans.clear()
            self._order.clear()
            return
        self._spans.pop(trace_id, None)
        self._order = [t for t in self._order if t != trace_id]


span_recorder = SpanRecorder()


class DashboardSpanProcessor(SimpleSpanProcessor):
    """SimpleSpanProcessor that also snapshots finished spans into the
    in-process recorder for the dashboard. Uses a no-op-ish console sink
    so the base class receives a valid exporter."""

    def __init__(self, exporter=None) -> None:
        super().__init__(exporter or ConsoleSpanExporter())

    def on_end(self, span: ReadableSpan) -> None:
        span_recorder.record(span)
        super().on_end(span)


@contextmanager
def start_span(
    name: str,
    attributes: dict[str, Any] | None = None,
    tracer=None,
) -> Iterator[Any]:
    """Context-managed span helper (Phase 11 tracing)."""
    tracer = tracer or _DEFAULT_TRACER
    with tracer.start_as_current_span(name) as span:
        for key, value in (attributes or {}).items():
            span.set_attribute(key, value)
        yield span


def record_exception(span, exc: Exception) -> None:
    span.record_exception(exc)
    span.set_status(trace.Status(trace.StatusCode.ERROR, str(exc)))
