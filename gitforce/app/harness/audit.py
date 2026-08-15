from __future__ import annotations

from gitforce.app.database.models import AuditLog


class AuditService:
    """Persists harness audit events to ``audit_logs`` using its own DB
    session, so auditing never blocks or reuses a task-service session."""

    def __init__(self, session_factory=None) -> None:
        if session_factory is None:
            from gitforce.app.database.session import SessionLocal

            session_factory = SessionLocal
        self._session_factory = session_factory

    async def log(
        self,
        *,
        agent: str,
        action: str,
        decision: str = "allowed",
        task_id: str | None = None,
        detail: dict | None = None,
    ) -> None:
        async with self._session_factory() as session:
            from gitforce.app.database.repositories import TaskRepository

            entry = AuditLog(
                task_id=task_id,
                agent=agent,
                action=action,
                decision=decision,
                detail=detail or {},
            )
            await TaskRepository(session).add_audit(entry)

    def make_handler(self, task_id: str | None = None):
        """Build the ``audit`` callable expected by AgentHarness."""

        async def handler(agent: str, action: str, message: str) -> None:
            await self.log(
                agent=agent,
                action=action,
                decision="allowed",
                task_id=task_id,
                detail={"message": message},
            )

        return handler