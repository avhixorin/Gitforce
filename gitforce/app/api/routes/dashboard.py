from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from gitforce.app.database.repositories import TaskRepository
from gitforce.app.database.session import get_session
from gitforce.app.evaluation.service import EvaluationService
from gitforce.app.observability.metrics import metrics
from gitforce.app.observability.tracing import span_recorder

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/traces")
async def recent_traces(
    limit: int = Query(default=20, ge=1, le=100),
) -> dict:
    """List recent trace IDs with span summaries for agent execution
    visualization (Phase 11)."""
    traces = []
    for trace_id in span_recorder.recent_traces(limit=limit):
        spans = span_recorder.spans_for(trace_id)
        traces.append(
            {
                "trace_id": trace_id,
                "span_count": len(spans),
                "spans": [s.to_dict() for s in spans],
            }
        )
    return {"traces": traces}


@router.get("/traces/{trace_id}")
async def trace_detail(trace_id: str) -> dict:
    spans = span_recorder.spans_for(trace_id)
    return {"trace_id": trace_id, "spans": [s.to_dict() for s in spans]}


@router.get("/metrics")
async def dashboard_metrics() -> dict:
    """Token/cost breakdown per agent for the dashboard (Phase 11)."""
    return {
        "tokens_by_agent": metrics.tokens_by_agent(),
        "cost_by_agent": metrics.cost_by_agent(),
        "total_tokens": sum(metrics.tokens_by_agent().values()),
        "total_cost_usd": round(sum(metrics.cost_by_agent().values()), 6),
    }


@router.get("/tasks")
async def dashboard_tasks(
    limit: int = Query(default=20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Per-task evaluation metrics for the dashboard."""
    service = EvaluationService(TaskRepository(session))
    summary = await service.summarize_all()
    tasks = summary.tasks[-limit:]
    return {
        "summary": summary.model_dump(exclude={"tasks"}),
        "tasks": [t.model_dump() for t in tasks],
    }
