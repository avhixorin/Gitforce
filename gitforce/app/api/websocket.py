from __future__ import annotations

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from gitforce.app.database.repositories import TaskRepository
from gitforce.app.database.session import SessionLocal
from gitforce.app.services.tasks import event_bus

router = APIRouter(tags=["websocket"])


@router.websocket("/ws/tasks/{task_id}")
async def task_events_ws(websocket: WebSocket, task_id: str) -> None:
    await websocket.accept()
    bus = event_bus
    queue: asyncio.Queue = bus.subscribe(task_id)

    # Replay persisted events first so a late subscriber sees history.
    async with SessionLocal() as session:
        repo = TaskRepository(session)
        events = await repo.list_events(task_id)
        for event in events:
            await websocket.send_json(
                {
                    "task_id": event.task_id,
                    "event": event.event,
                    "agent": event.agent,
                    "timestamp": event.created_at.isoformat(),
                    "metadata": event.metadata_ or {},
                }
            )

    try:
        while True:
            event = await queue.get()
            await websocket.send_json(event)
    except WebSocketDisconnect:
        pass
    finally:
        bus.unsubscribe(task_id, queue)