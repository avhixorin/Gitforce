from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from gitforce.app.database.models import (
    AuditLog,
    Task,
    TaskEvent,
    TaskStatus,
)


class TaskRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, task: Task) -> Task:
        self._session.add(task)
        await self._session.commit()
        await self._session.refresh(task)
        return task

    async def get(self, task_id: str) -> Task | None:
        result = await self._session.get(Task, task_id)
        return result

    async def find_by_repository_issue(
        self, repository_url: str, issue_url: str
    ) -> Task | None:
        result = await self._session.execute(
            select(Task)
            .where(
                Task.repository_url == repository_url,
                Task.issue_url == issue_url,
            )
            .order_by(Task.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def list_all(self, limit: int = 50, offset: int = 0) -> list[Task]:
        result = await self._session.scalars(
            select(Task).order_by(Task.created_at.desc()).limit(limit).offset(offset)
        )
        return list(result)

    async def update_status(
        self, task_id: str, status: TaskStatus, **fields: object
    ) -> Task | None:
        task = await self.get(task_id)
        if task is None:
            return None
        task.status = status
        for key, value in fields.items():
            setattr(task, key, value)
        await self._session.commit()
        await self._session.refresh(task)
        return task

    async def update_state(self, task_id: str, state: dict) -> None:
        await self._session.execute(
            update(Task).where(Task.id == task_id).values(state=state)
        )
        await self._session.commit()

    async def add_event(self, event: TaskEvent) -> TaskEvent:
        self._session.add(event)
        await self._session.commit()
        await self._session.refresh(event)
        return event

    async def list_events(self, task_id: str, limit: int = 500) -> list[TaskEvent]:
        result = await self._session.scalars(
            select(TaskEvent)
            .where(TaskEvent.task_id == task_id)
            .order_by(TaskEvent.created_at.asc())
            .limit(limit)
        )
        return list(result)

    async def add_audit(self, entry: AuditLog) -> AuditLog:
        self._session.add(entry)
        await self._session.commit()
        await self._session.refresh(entry)
        return entry

    async def list_audit(
        self,
        task_id: str | None = None,
        agent: str | None = None,
        limit: int = 200,
    ) -> list[AuditLog]:
        query = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)
        if task_id:
            query = query.where(AuditLog.task_id == task_id)
        if agent:
            query = query.where(AuditLog.agent == agent)
        result = await self._session.scalars(query)
        return list(result)