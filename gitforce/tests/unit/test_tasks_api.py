from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient

from gitforce.app.database import models
from gitforce.app.database.session import engine
from gitforce.app.main import app


@pytest.fixture(autouse=True)
async def _db() -> AsyncGenerator[None, None]:
    async with engine.begin() as conn:
        await conn.run_sync(models.Base.metadata.drop_all)
        await conn.run_sync(models.Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(models.Base.metadata.drop_all)


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_health(client: AsyncClient) -> None:
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


async def test_create_task_and_fetch(client: AsyncClient) -> None:
    payload = {
        "repository_url": "https://github.com/org/repo",
        "issue_url": "https://github.com/org/repo/issues/12",
    }
    resp = await client.post("/api/tasks", json=payload)
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "queued"
    task_id = body["task_id"]

    resp = await client.get(f"/api/tasks/{task_id}")
    assert resp.status_code == 200
    assert resp.json()["repository_url"] == payload["repository_url"]


async def test_create_task_rejects_bad_url(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/tasks",
        json={
            "repository_url": "https://example.com/not-github",
            "issue_url": "https://github.com/org/repo/issues/1",
        },
    )
    assert resp.status_code == 400


async def test_create_task_rejects_bad_issue(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/tasks",
        json={
            "repository_url": "https://github.com/org/repo",
            "issue_url": "https://github.com/org/repo",
        },
    )
    assert resp.status_code == 400


async def test_events_track_creation(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/tasks",
        json={
            "repository_url": "https://github.com/org/repo",
            "issue_url": "https://github.com/org/repo/issues/12",
        },
    )
    task_id = resp.json()["task_id"]
    resp = await client.get(f"/api/tasks/{task_id}/events")
    assert resp.status_code == 200
    events = resp.json()
    assert len(events) == 1
    assert events[0]["event"] == "task.created"
    assert events[0]["metadata"]["task_id"] == task_id


async def test_get_missing_task_404(client: AsyncClient) -> None:
    resp = await client.get("/api/tasks/nonexistent")
    assert resp.status_code == 404


async def test_cancel_task(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/tasks",
        json={
            "repository_url": "https://github.com/org/repo",
            "issue_url": "https://github.com/org/repo/issues/12",
        },
    )
    task_id = resp.json()["task_id"]
    resp = await client.post(f"/api/tasks/{task_id}/cancel")
    assert resp.status_code == 200
    resp = await client.get(f"/api/tasks/{task_id}")
    assert resp.json()["status"] == "cancelled"


async def test_report_and_pr_default(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/tasks",
        json={
            "repository_url": "https://github.com/org/repo",
            "issue_url": "https://github.com/org/repo/issues/12",
        },
    )
    task_id = resp.json()["task_id"]
    for path in ("report", "pr"):
        resp = await client.get(f"/api/tasks/{task_id}/{path}")
        assert resp.status_code == 200