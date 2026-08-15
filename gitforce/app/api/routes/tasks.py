from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from gitforce.app.api.schemas import (
    MessageOut,
    ResumeTask,
    TaskCreate,
    TaskCreated,
    TaskEventOut,
    TaskOut,
)
from gitforce.app.database.repositories import TaskRepository
from gitforce.app.database.session import get_session
from gitforce.app.github.client import GitHubValidationError
from gitforce.app.orchestration.runner import resume_task_bg, run_task
from gitforce.app.services.tasks import TaskNotFoundError, TaskService

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


async def _service(
    session: AsyncSession = Depends(get_session),
) -> TaskService:
    return TaskService(session)


@router.post("", response_model=TaskCreated, status_code=status.HTTP_201_CREATED)
async def create_task(
    payload: TaskCreate,
    background_tasks: BackgroundTasks,
    service: TaskService = Depends(_service),
) -> TaskCreated:
    try:
        task = await service.create_task(payload)
    except GitHubValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    background_tasks.add_task(run_task, task.id)
    return TaskCreated(task_id=task.id, status=task.status)


@router.get("", response_model=list[TaskOut])
async def list_tasks(
    limit: int = 50,
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
) -> list:
    repo = TaskRepository(session)
    tasks = await repo.list_all(limit=limit, offset=offset)
    return [TaskOut.model_validate(t) for t in tasks]


@router.get("/{task_id}", response_model=TaskOut)
async def get_task(task_id: str, service: TaskService = Depends(_service)) -> TaskOut:
    try:
        task = await service.get_task(task_id)
    except TaskNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Task not found") from exc
    return TaskOut.model_validate(task)


@router.get("/{task_id}/events", response_model=list[TaskEventOut])
async def get_events(
    task_id: str,
    limit: int = 500,
    session: AsyncSession = Depends(get_session),
) -> list:
    repo = TaskRepository(session)
    events = await repo.list_events(task_id, limit=limit)
    return [TaskEventOut.model_validate(e) for e in events]


@router.get("/{task_id}/report", response_model=dict)
async def get_report(
    task_id: str, service: TaskService = Depends(_service)
) -> dict:
    task = await service.get_task(task_id)
    return {"task_id": task.id, "report": task.report or {}}


@router.get("/{task_id}/pr", response_model=dict)
async def get_pr(task_id: str, service: TaskService = Depends(_service)) -> dict:
    task = await service.get_task(task_id)
    return {"task_id": task.id, "pr": task.pr or {}}


@router.post("/{task_id}/cancel", response_model=MessageOut)
async def cancel_task(
    task_id: str, service: TaskService = Depends(_service)
) -> MessageOut:
    await service.cancel_task(task_id)
    return MessageOut(message="Task cancelled")


@router.post("/{task_id}/resume", response_model=TaskOut)
async def resume_task(
    task_id: str,
    background_tasks: BackgroundTasks,
    body: ResumeTask | None = None,
    service: TaskService = Depends(_service),
) -> TaskOut:
    try:
        task = await service.get_task(task_id)
    except TaskNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Task not found") from exc
    background_tasks.add_task(
        resume_task_bg, task_id, body.answer if body else None
    )
    return TaskOut.model_validate(task)