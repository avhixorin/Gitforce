from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import httpx
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from gitforce.app.api.schemas import TaskCreate
from gitforce.app.database.models import Task, TaskEvent, TaskStatus
from gitforce.app.database.repositories import TaskRepository
from gitforce.app.github.client import (
    GitHubClient,
    GitHubValidationError,
    parse_issue_url,
    parse_repository_url,
)


class TaskNotFoundError(Exception):
    pass


def _json_safe(value: object) -> object:
    """Recursively convert Pydantic models / typed objects to JSON-safe data."""
    from pydantic import BaseModel as _BM

    if isinstance(value, _BM):
        return _json_safe(value.model_dump())
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    return value


def _json_safe_dict(value: dict) -> dict:
    return {k: _json_safe(v) for k, v in value.items()}


class EventBus:
    """In-process pub/sub for task events. Redis-backed pub/sub can replace
    this for horizontal scaling without changing call sites."""

    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue]] = {}

    async def publish(self, task_id: str, event: dict) -> None:
        for queue in list(self._subscribers.get(task_id, ())):
            await queue.put(event)

    def subscribe(self, task_id: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._subscribers.setdefault(task_id, set()).add(queue)
        return queue

    def unsubscribe(self, task_id: str, queue: asyncio.Queue) -> None:
        subscribers = self._subscribers.get(task_id)
        if subscribers:
            subscribers.discard(queue)
            if not subscribers:
                self._subscribers.pop(task_id, None)


event_bus = EventBus()


class TaskService:
    def __init__(self, session: AsyncSession) -> None:
        self._repo = TaskRepository(session)
        self._session = session
        self.bus = event_bus

    async def create_task(self, payload: TaskCreate) -> Task:
        # Validate URLs first; raise before persisting anything.
        parse_repository_url(payload.repository_url)
        parse_issue_url(payload.issue_url)

        # Idempotency (Phase 12): skip duplicates of the same repo/issue.
        from gitforce.app.security.recovery import idempotency_store

        key = idempotency_store.key(
            "task.create", payload.repository_url, payload.issue_url
        )
        if not idempotency_store.check_and_mark(key):
            existing = await self._repo.find_by_repository_issue(
                payload.repository_url, payload.issue_url
            )
            if existing is not None:
                return existing

        task = Task(
            repository_url=payload.repository_url,
            issue_url=payload.issue_url,
            status=TaskStatus.QUEUED,
            target_branch=payload.target_branch,
            model=payload.model,
            max_iterations=payload.max_iterations,
            test_execution_mode=payload.test_execution_mode,
            approval_mode=payload.approval_mode,
        )
        await self._repo.create(task)
        await self.emit(task.id, "task.created", metadata={"task_id": task.id})
        return task

    async def get_task(self, task_id: str) -> Task:
        task = await self._repo.get(task_id)
        if task is None:
            raise TaskNotFoundError(task_id)
        return task

    async def cancel_task(self, task_id: str) -> Task:
        task = await self._repo.update_status(task_id, TaskStatus.CANCELLED)
        if task is None:
            raise TaskNotFoundError(task_id)
        await self.emit(task_id, "task.cancelled", metadata={"task_id": task_id})
        return task

    async def mark_started(self, task_id: str) -> Task:
        task = await self._repo.update_status(
            task_id,
            TaskStatus.RUNNING,
            started_at=datetime.now(UTC),
        )
        if task is None:
            raise TaskNotFoundError(task_id)
        await self.emit(task_id, "task.started", metadata={"task_id": task_id})
        return task

    async def run(self, task_id: str) -> Task:
        """Full discovery run: mark running, fetch repo + issue, persist state."""
        task = await self.mark_started(task_id)
        try:
            await self._discover(task_id)
        except (httpx.HTTPError, GitHubValidationError) as exc:
            task = await self._fail(task_id, f"Discovery failed: {exc}")
        return task

    async def _fail(self, task_id: str, error: str) -> Task:
        task = await self._repo.update_status(
            task_id,
            TaskStatus.FAILED,
            error=error,
            completed_at=datetime.now(UTC),
        )
        if task is None:
            raise TaskNotFoundError(task_id)
        await self.emit(
            task_id, "workflow.failed", metadata={"error": error}
        )
        return task

    async def update_agent_result(
        self, task_id: str, key: str, value: object
    ) -> None:
        """Persist a structured agent result into task state."""
        if isinstance(value, BaseModel):
            value = value.model_dump()
        task = await self.get_task(task_id)
        state = dict(task.state or {})
        state[key] = value
        task.state = state
        setattr(task, key, value)
        await self._session.commit()
        await self.emit(task_id, f"agent.{key}.completed")

    async def record_usage(self, task_id: str, usage: dict) -> None:
        """Append one LLM usage record to the task's cumulative usage (41)."""
        task = await self.get_task(task_id)
        state = dict(task.state or {})
        usage_list = list(state.get("usage") or [])
        usage_list.append(usage)
        state["usage"] = usage_list
        task.state = state
        await self._session.commit()
        await self.emit(
            task_id,
            "usage.recorded",
            metadata={"model": usage.get("model"), "cost_usd": usage.get("estimated_cost_usd")},
        )

    async def persist_workflow_state(self, task_id: str, values: dict) -> None:
        """Mirror a LangGraph checkpoint snapshot into the tasks table.

        Preserves cost/usage records that ``UsageService`` appends through
        its own session so ``task.state["usage"]`` is not clobbered by the
        graph's (empty) usage accumulator.
        """
        task = await self.get_task(task_id)
        state = _json_safe_dict(values)
        existing = dict(task.state or {})
        existing_usage = existing.get("usage") or []
        if existing_usage and not state.get("usage"):
            state["usage"] = existing_usage
        task.state = state
        if "plan" in state:
            task.plan = state["plan"]
        if "status" in state:
            from gitforce.app.database.models import TaskStatus as TS

            try:
                task.status = TS(state["status"])
            except ValueError:
                pass
        await self._session.commit()

    async def pause_task(self, task_id: str) -> Task:
        task = await self._repo.update_status(task_id, TaskStatus.PAUSED)
        if task is None:
            raise TaskNotFoundError(task_id)
        await self.emit(task_id, "workflow.paused")
        return task

    async def complete_task(self, task_id: str) -> Task:
        task = await self._repo.update_status(
            task_id,
            TaskStatus.COMPLETED,
            completed_at=datetime.now(UTC),
        )
        if task is None:
            raise TaskNotFoundError(task_id)
        await self.emit(task_id, "workflow.completed")
        return task

    async def fail_task(self, task_id: str, error: str) -> Task:
        return await self._fail(task_id, error)

    async def _discover(self, task_id: str) -> Task:
        from gitforce.app.security.recovery import TransientRetryPolicy

        task = await self.get_task(task_id)

        async def _fetch() -> dict:
            async with GitHubClient() as client:
                repo_ref = parse_repository_url(task.repository_url)
                issue_ref = parse_issue_url(task.issue_url)
                await self.emit(task_id, "repository.fetch.started")
                repository = await client.get_repository(repo_ref)
                await self.emit(task_id, "repository.fetch.completed")
                await self.emit(task_id, "issue.fetch.started")
                issue = await client.get_issue(issue_ref)
                await self.emit(task_id, "issue.fetch.completed")
            return {"repository": repository, "issue": issue}

        # Transient GitHub failures (429/5xx/timeouts) are retried with
        # exponential backoff (sections 46, Phase 12 failure recovery).
        result = await TransientRetryPolicy(max_attempts=3).run(_fetch)
        if not result.ok:
            raise httpx.HTTPError(result.error)
        data = result.value
        task.repository = data["repository"]
        task.issue = data["issue"]
        state = dict(task.state or {})
        state.update(repository=data["repository"], issue=data["issue"])
        task.state = state
        await self._session.commit()
        return task

    async def emit(self, task_id: str, event: str, metadata: dict | None = None) -> None:
        event_row = TaskEvent(
            task_id=task_id, event=event, metadata_=metadata or {}
        )
        await self._repo.add_event(event_row)
        await self.bus.publish(
            task_id,
            {
                "task_id": task_id,
                "event": event,
                "timestamp": event_row.created_at.isoformat(),
                "metadata": metadata or {},
            },
        )