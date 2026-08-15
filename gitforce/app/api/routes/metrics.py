from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import Response

from gitforce.app.observability.metrics import metrics

router = APIRouter(tags=["observability"])


@router.get("/metrics")
async def metrics_endpoint() -> Response:
    """Prometheus text exposition format (Phase 11 metrics)."""
    return Response(
        content=metrics.render(),
        media_type="text/plain; version=0.0.4",
    )
