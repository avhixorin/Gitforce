from __future__ import annotations

from gitforce.app.database.models import Task


class UsageService:
    """Persists per-call LLM usage into ``tasks.state["usage"]`` using its
    own DB session so cost tracking never blocks or races a task-service
    session (mirrors AuditService)."""

    def __init__(self, session_factory=None) -> None:
        if session_factory is None:
            from gitforce.app.database.session import SessionLocal

            session_factory = SessionLocal
        self._session_factory = session_factory

    async def record(self, task_id: str, usage: dict) -> None:
        async with self._session_factory() as session:
            task = await session.get(Task, task_id)
            if task is None:
                return
            state = dict(task.state or {})
            usage_list = list(state.get("usage") or [])
            usage_list.append(usage)
            state["usage"] = usage_list
            task.state = state
            await session.commit()

    def make_handler(self, task_id: str | None = None):
        """Build the ``usage_sink`` callable expected by AgentHarness."""

        async def handler(usage) -> None:
            await self.record(task_id or "", usage.model_dump())

        return handler
