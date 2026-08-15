from __future__ import annotations

from gitforce.app.llm.providers import BaseLLMProvider
from gitforce.app.orchestration.failure import categorize_exception
from gitforce.app.orchestration.graph import build_graph
from gitforce.app.orchestration.nodes import AgentContext
from gitforce.app.services.tasks import TaskService


def _memory_checkpointer():
    from langgraph.checkpoint.memory import MemorySaver

    return MemorySaver()


class LangGraphWorkflow:
    """Phase 3 workflow: LangGraph supervisor with persistent checkpoints.

    Runs the engineering graph for a task and mirrors the checkpointed state
    back into the tasks table so the REST/WebSocket layers stay the source
    of truth for observers.
    """

    def __init__(
        self,
        task_service: TaskService,
        provider: BaseLLMProvider,
        checkpointer=None,
    ) -> None:
        self._tasks = task_service
        self._provider = provider
        self._checkpointer = checkpointer or _memory_checkpointer()

    def _context(self) -> AgentContext:
        return AgentContext(task_service=self._tasks, provider=self._provider)

    def _graph(self):
        return build_graph(checkpointer=self._checkpointer, ctx=self._context())

    def _config(self, task_id: str) -> dict:
        return {"configurable": {"thread_id": task_id}}

    async def run(self, task_id: str) -> None:
        task = await self._tasks.get_task(task_id)
        graph = self._graph()
        config = self._config(task_id)
        await self._tasks.emit(task_id, "workflow.started")
        initial = {
            "task_id": task_id,
            "repository_url": task.repository_url,
            "issue_url": task.issue_url,
            "repository": task.repository or {},
            "issue": task.issue or {},
            "iteration": task.iteration,
            "status": "running",
        }
        try:
            await graph.ainvoke(initial, config=config)
        except Exception as exc:  # noqa: BLE001
            await self._tasks.fail_task(
                task_id, f"[{categorize_exception(exc).value}] {exc}"
            )
            return
        await self._sync(task_id, graph, config)

    async def resume(self, task_id: str, answer: str | None = None) -> None:
        from langgraph.types import Command

        await self._tasks.get_task(task_id)
        graph = self._graph()
        config = self._config(task_id)
        await self._tasks.mark_started(task_id)
        try:
            if answer is not None:
                await graph.ainvoke(Command(resume=answer), config=config)
            else:
                await graph.ainvoke(None, config=config)
        except Exception as exc:  # noqa: BLE001
            await self._tasks.fail_task(
                task_id, f"[{categorize_exception(exc).value}] {exc}"
            )
            return
        await self._sync(task_id, graph, config)

    async def _sync(self, task_id: str, graph, config: dict) -> None:
        snapshot = await graph.aget_state(config)
        values = dict(snapshot.values)
        # An interrupt (human clarification / approval) halts before the node
        # returns, so the checkpoint may still say "running". Force "paused".
        if getattr(snapshot, "interrupts", None):
            values["status"] = "paused"
            await self._tasks.pause_task(task_id)
        await self._tasks.persist_workflow_state(task_id, values)