from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient

from gitforce.app.database import models
from gitforce.app.database.models import Task, TaskStatus
from gitforce.app.database.session import SessionLocal, engine
from gitforce.app.main import app
from gitforce.app.observability.metrics import Metrics
from gitforce.app.observability.tracing import (
    SpanInfo,
    SpanRecorder,
)


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


def test_metrics_counters_aggregate() -> None:
    m = Metrics()
    m.task_created()
    m.task_created()
    m.workflow_done("completed")
    m.agent_completed("coder", elapsed_ms=1200.0, tokens=500, cost=0.01)
    m.agent_completed("coder", elapsed_ms=800.0, tokens=300, cost=0.005)

    assert m.tokens_by_agent()["coder"] == 800
    assert m.cost_by_agent()["coder"] == pytest.approx(0.015)
    rendered = m.render().decode()
    assert "gitforce_agent_calls_total" in rendered
    assert "gitforce_tokens_total" in rendered


def test_metrics_render_includes_help() -> None:
    m = Metrics()
    m.task_created(status="queued")
    out = m.render().decode()
    assert 'gitforce_tasks_total{status="queued"}' in out
    assert "# HELP gitforce_tasks_total" in out


def test_span_recorder_storage_contract() -> None:
    recorder = SpanRecorder()
    info = SpanInfo(
        name="node.coder",
        trace_id="abc",
        span_id="def",
        parent_span_id=None,
        start_time_ns=0,
        end_time_ns=1_000_000,
        duration_ms=1.0,
        attributes={"task_id": "t1"},
    )
    recorder._spans["abc"] = [info]
    recorder._order.append("abc")
    assert recorder.spans_for("abc")[0].name == "node.coder"
    assert info.to_dict()["duration_ms"] == 1.0


def test_span_recorder_recent_traces_order() -> None:
    recorder = SpanRecorder()
    for trace_id in ("aaa", "bbb", "ccc"):
        recorder._spans[trace_id] = [
            SpanInfo(
                name="x",
                trace_id=trace_id,
                span_id=trace_id,
                parent_span_id=None,
                start_time_ns=0,
                end_time_ns=1,
                duration_ms=0.001,
            )
        ]
        recorder._order.append(trace_id)
    assert recorder.recent_traces(limit=2) == ["ccc", "bbb"]
    recorder.clear("ccc")
    assert recorder.spans_for("ccc") == []


def test_span_recorder_clear_all() -> None:
    recorder = SpanRecorder()
    recorder._spans["aaa"] = []
    recorder._order.append("aaa")
    recorder.clear()
    assert recorder.recent_traces() == []


async def test_harness_run_creates_span() -> None:
    from gitforce.app.harness.executor import AgentHarness
    from gitforce.app.harness.permissions import permissions_for
    from gitforce.app.observability.tracing import init_tracing, span_recorder

    init_tracing()
    span_recorder.clear()

    harness = AgentHarness(
        agent="coder", permissions=permissions_for("coder"), task_id="t1"
    )

    async def ping() -> str:
        return "pong"

    result = await harness.run(ping)
    assert result.ok

    traces = span_recorder.recent_traces()
    assert traces, "harness run must record a span"
    spans = span_recorder.spans_for(traces[0])
    assert any(s.name == "agent.coder.run" for s in spans)
    span_recorder.clear()


async def test_llm_call_creates_span() -> None:
    from gitforce.app.agents.base import AgentBase
    from gitforce.app.config.settings import get_settings
    from gitforce.app.harness.executor import AgentHarness
    from gitforce.app.harness.permissions import permissions_for
    from gitforce.app.llm.providers import MockProvider
    from gitforce.app.observability.tracing import init_tracing, span_recorder

    init_tracing()
    span_recorder.clear()

    harness = AgentHarness(
        agent="coder", permissions=permissions_for("coder"), task_id="t1"
    )
    agent = AgentBase(harness.wrap_provider(MockProvider(get_settings())))

    from gitforce.app.agents.models import ReviewDecision

    await agent.run_structured(
        "review the change", ReviewDecision, max_tokens=128
    )

    traces = span_recorder.recent_traces()
    assert traces
    spans = span_recorder.spans_for(traces[0])
    assert any(s.name == "llm.complete" for s in spans)
    span_recorder.clear()


async def test_metrics_endpoint(client: AsyncClient) -> None:
    resp = await client.get("/metrics")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
    assert "gitforce_" in resp.text


async def test_dashboard_metrics_empty(client: AsyncClient) -> None:
    resp = await client.get("/api/dashboard/metrics")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body["total_tokens"], int)
    assert isinstance(body["total_cost_usd"], float)
    assert "tokens_by_agent" in body
    assert "cost_by_agent" in body


async def test_dashboard_traces_empty(client: AsyncClient) -> None:
    resp = await client.get("/api/dashboard/traces")
    assert resp.status_code == 200
    assert isinstance(resp.json()["traces"], list)


async def test_dashboard_tasks_empty(client: AsyncClient) -> None:
    resp = await client.get("/api/dashboard/tasks")
    assert resp.status_code == 200
    body = resp.json()
    assert body["summary"]["total_tasks"] == 0


async def test_dashboard_tasks_with_data(client: AsyncClient) -> None:
    async with SessionLocal() as session:
        session.add(
            Task(
                id="d1",
                repository_url="https://github.com/org/repo",
                issue_url="https://github.com/org/repo/issues/1",
                status=TaskStatus.COMPLETED,
                state={"usage": [{"agent": "coder", "input_tokens": 10}]},
                report={
                    "test_results": {"tests_run": 2, "tests_passed": 2},
                    "security_results": {"passed": True},
                },
            )
        )
        await session.commit()

    resp = await client.get("/api/dashboard/tasks")
    assert resp.status_code == 200
    body = resp.json()
    assert body["summary"]["total_tasks"] == 1
    assert body["tasks"][0]["task_id"] == "d1"


async def test_trace_detail_not_found(client: AsyncClient) -> None:
    resp = await client.get("/api/dashboard/traces/no-such-trace")
    assert resp.status_code == 200
    assert resp.json()["spans"] == []
