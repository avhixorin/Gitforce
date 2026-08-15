from __future__ import annotations

from gitforce.app.config.settings import get_settings
from gitforce.app.database.models import TaskStatus
from gitforce.app.database.session import SessionLocal
from gitforce.app.llm.models import LLMTaskType
from gitforce.app.llm.providers import BaseLLMProvider
from gitforce.app.llm.router import ModelRouter
from gitforce.app.orchestration.workflow import LangGraphWorkflow
from gitforce.app.services.tasks import TaskService


async def run_task(task_id: str) -> None:
    """Background entry point for a task.

    Opens its own DB session (independent of any request-scoped session),
    runs Phase 1 discovery, then executes the LangGraph engineering workflow.
    """
    if not get_settings().auto_discover:
        return
    from gitforce.app.observability.metrics import metrics
    from gitforce.app.observability.tracing import start_span

    async with SessionLocal() as session:
        service = TaskService(session)
        provider = _resolve_provider()
        try:
            with start_span(
                "workflow.run", {"task_id": task_id}
            ):
                await service.run(task_id)
                task = await service.get_task(task_id)
                if task.status is TaskStatus.RUNNING:
                    workflow = LangGraphWorkflow(service, provider)
                    await workflow.run(task_id)
            metrics.task_created()
            metrics.workflow_done("completed")
        except Exception as exc:  # noqa: BLE001
            await service.fail_task(task_id, str(exc))
            metrics.workflow_done("failed")


def _resolve_provider() -> BaseLLMProvider:
    settings = get_settings()
    return ModelRouter(settings).provider_for(LLMTaskType.CODE_GENERATION)


async def resume_task_bg(task_id: str, answer: str | None = None) -> None:
    """Resume a paused workflow (e.g. after human clarification)."""
    if not get_settings().auto_discover:
        return
    async with SessionLocal() as session:
        service = TaskService(session)
        provider = _resolve_provider()
        try:
            workflow = LangGraphWorkflow(service, provider)
            await workflow.resume(task_id, answer=answer)
        except Exception as exc:  # noqa: BLE001
            await service.fail_task(task_id, str(exc))