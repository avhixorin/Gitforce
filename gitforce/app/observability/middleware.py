from __future__ import annotations

import time

from opentelemetry import trace
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from gitforce.app.observability.metrics import metrics
from gitforce.app.observability.tracing import start_span

_MEASURED_PREFIXES = ("/api/", "/metrics", "/dashboard")


class ObservabilityMiddleware(BaseHTTPMiddleware):
    """Records HTTP request duration into Prometheus and creates a span per
    request (Phase 11)."""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        with start_span(
            "http.request",
            attributes={
                "http.method": request.method,
                "http.route": path,
            },
        ) as span:
            start = time.monotonic()
            try:
                response: Response = await call_next(request)
            except Exception as exc:  # noqa: BLE001
                span.record_exception(exc)
                span.set_status(
                    status=trace.StatusCode.ERROR,
                    description=str(exc),
                )
                raise
            finally:
                elapsed = time.monotonic() - start
            if any(path.startswith(p) for p in _MEASURED_PREFIXES):
                metrics.observe_request(request.method, path, elapsed)
            span.set_attribute("http.status_code", response.status_code)
            return response
