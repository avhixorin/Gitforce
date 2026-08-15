from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from gitforce.app.database.repositories import TaskRepository
from gitforce.app.database.session import get_session
from gitforce.app.evaluation.models import EvaluationSummary, TaskEvaluation
from gitforce.app.evaluation.service import EvaluationService

router = APIRouter(prefix="/api/evaluation", tags=["evaluation"])


async def _service(
    session: AsyncSession = Depends(get_session),
) -> EvaluationService:
    return EvaluationService(TaskRepository(session))


@router.get("/summary", response_model=EvaluationSummary)
async def get_summary(
    service: EvaluationService = Depends(_service),
) -> EvaluationSummary:
    return await service.summarize_all()


@router.get("/{task_id}", response_model=TaskEvaluation)
async def get_task_evaluation(
    task_id: str,
    service: EvaluationService = Depends(_service),
) -> TaskEvaluation:
    evaluation = await service.evaluate(task_id)
    if evaluation is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return evaluation


@router.get("", response_model=list[TaskEvaluation])
async def list_evaluations(
    task_ids: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> list[TaskEvaluation]:
    repo = TaskRepository(session)
    service = EvaluationService(repo)
    if task_ids:
        ids = [i for i in task_ids.split(",") if i.strip()]
        return await service.evaluate_many(ids)
    tasks = await repo.list_all(limit=100)
    evaluations: list[TaskEvaluation] = []
    for t in tasks:
        evaluation = await service.evaluate(t.id)
        if evaluation is not None:
            evaluations.append(evaluation)
    return evaluations
