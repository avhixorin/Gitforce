from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from gitforce.app.database import models
from gitforce.app.database.models import Task, TaskEvent, TaskStatus
from gitforce.app.database.session import SessionLocal, engine
from gitforce.app.evaluation.benchmarks import BenchmarkCase, JudgeEvaluator
from gitforce.app.evaluation.cost import aggregate_usage
from gitforce.app.evaluation.models import (
    CostSummary,
    TaskEvaluation,
)
from gitforce.app.evaluation.rag import evaluate_retrieval
from gitforce.app.evaluation.service import (
    EvaluationService,
    evaluate_task,
    summarize,
)
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


async def _seed_task(
    *,
    task_id: str = "ev1",
    status: TaskStatus = TaskStatus.COMPLETED,
    state: dict | None = None,
    report: dict | None = None,
) -> None:
    async with SessionLocal() as session:
        task = Task(
            id=task_id,
            repository_url="https://github.com/org/repo",
            issue_url="https://github.com/org/repo/issues/1",
            status=status,
            state=state or {},
            report=report or {},
        )
        session.add(task)
        await session.commit()


async def _seed_event(task_id: str, agent: str, event: str) -> None:
    async with SessionLocal() as session:
        session.add(TaskEvent(task_id=task_id, agent=agent, event=event))
        await session.commit()


def test_aggregate_usage_sums_costs() -> None:
    records = [
        {
            "agent": "coder",
            "input_tokens": 100,
            "output_tokens": 50,
            "estimated_cost_usd": 0.01,
            "latency_ms": 200.0,
        },
        {
            "agent": "coder",
            "input_tokens": 40,
            "output_tokens": 10,
            "estimated_cost_usd": 0.005,
            "latency_ms": 100.0,
        },
        {
            "agent": "reviewer",
            "input_tokens": 20,
            "output_tokens": 5,
            "estimated_cost_usd": 0.002,
            "latency_ms": 50.0,
        },
    ]
    summary = aggregate_usage(records)
    assert summary.total_tokens == 225
    assert summary.calls == 3
    assert summary.total_cost_usd == pytest.approx(0.017)
    assert summary.total_latency_ms == pytest.approx(350.0)
    assert summary.per_agent["coder"].total_tokens == 200
    assert summary.per_agent["coder"].calls == 2
    assert summary.per_agent["reviewer"].total_tokens == 25


def test_aggregate_usage_handles_bad_records() -> None:
    records: list = [None, {}, {"total_tokens": 7}]
    summary = aggregate_usage(records)
    assert summary.calls == 1
    assert summary.total_tokens == 7
    assert summary.per_agent["unknown"].calls == 1


def test_evaluate_task_derives_metrics() -> None:
    report = {
        "plan": {"quality_score": 0.9},
        "implementation": {"quality_score": 0.8},
        "test_results": {
            "tests_run": 10,
            "tests_passed": 9,
        },
        "security_results": {
            "passed": True,
            "findings": [{"severity": "info", "description": "note"}],
        },
        "review_results": {"approved": True, "score": 0.85},
        "judge_results": {"ready": True},
    }
    state = {
        "usage": [
            {"agent": "coder", "input_tokens": 100, "estimated_cost_usd": 0.01}
        ],
        "pr_cycles": 2,
    }
    task = Task(
        id="ev1",
        repository_url="https://github.com/org/repo",
        issue_url="https://github.com/org/repo/issues/1",
        status=TaskStatus.COMPLETED,
        state=state,
        report=report,
        iteration=3,
    )
    evaluation = evaluate_task(task)
    assert evaluation.succeeded
    assert evaluation.test_pass_rate == pytest.approx(0.9)
    assert evaluation.planning_quality == pytest.approx(0.9)
    assert evaluation.code_quality == pytest.approx(0.8)
    assert evaluation.security_passed
    assert evaluation.reviewer_accepted
    assert evaluation.judge_ready
    assert evaluation.iteration_count == 3
    assert evaluation.cost.total_cost_usd == pytest.approx(0.01)
    assert evaluation.trajectory.reviewer_cycles == 2


def test_evaluate_task_failed_task_not_successful() -> None:
    task = Task(
        id="ev2",
        repository_url="https://github.com/org/repo",
        issue_url="https://github.com/org/repo/issues/2",
        status=TaskStatus.FAILED,
        state={},
        report={},
    )
    evaluation = evaluate_task(task)
    assert not evaluation.succeeded
    assert not evaluation.task_success


def test_summarize_aggregates_rates() -> None:
    def _eval(task_id: str, succeeded: bool, cost: float) -> TaskEvaluation:
        return TaskEvaluation(
            task_id=task_id,
            issue_url=f"https://github.com/org/repo/issues/{task_id}",
            repository_url="https://github.com/org/repo",
            succeeded=succeeded,
            task_success=succeeded,
            test_pass_rate=1.0,
            planning_quality=0.9,
            code_quality=0.8,
            security_passed=succeeded,
            reviewer_accepted=succeeded,
            iteration_count=1,
            cost=CostSummary(total_cost_usd=cost),
            time_ms=1000.0,
        )

    summary = summarize([_eval("a", True, 0.01), _eval("b", False, 0.02)])
    assert summary.total_tasks == 2
    assert summary.succeeded == 1
    assert summary.task_success_rate == pytest.approx(0.5)
    assert summary.security_pass_rate == pytest.approx(0.5)
    assert summary.reviewer_acceptance_rate == pytest.approx(0.5)
    assert summary.avg_cost_per_task == pytest.approx(0.015)
    assert summary.avg_time_per_task_ms == pytest.approx(1000.0)
    assert summary.total_cost_usd == pytest.approx(0.03)


async def test_evaluation_service_roundtrip() -> None:
    from gitforce.app.database.repositories import TaskRepository

    await _seed_task(
        report={
            "test_results": {"tests_run": 4, "tests_passed": 4},
            "security_results": {"passed": True},
            "review_results": {"approved": True},
            "judge_results": {"ready": True},
        },
        state={"usage": []},
    )
    await _seed_event("ev1", "planner", "agent.planner.started")
    await _seed_event("ev1", "planner", "agent.planner.completed")

    async with SessionLocal() as session:
        service = EvaluationService(TaskRepository(session))
        evaluation = await service.evaluate("ev1")
        assert evaluation is not None
        assert evaluation.succeeded
        assert evaluation.test_pass_rate == 1.0
        assert len(evaluation.trajectory.steps) == 1
        assert evaluation.trajectory.steps[0].agent == "planner"


def _make_task_evaluation(**overrides: object) -> TaskEvaluation:
    defaults: dict[str, object] = {
        "task_id": "t",
        "issue_url": "https://github.com/org/repo/issues/1",
        "repository_url": "https://github.com/org/repo",
        "succeeded": True,
        "task_success": True,
    }
    defaults.update(overrides)
    return TaskEvaluation(**defaults)  # type: ignore[arg-type]


async def test_evaluation_api_summary(client: AsyncClient) -> None:
    resp = await client.get("/api/evaluation/summary")
    assert resp.status_code == 200
    assert resp.json()["total_tasks"] == 0


async def test_evaluation_api_task_not_found(client: AsyncClient) -> None:
    resp = await client.get("/api/evaluation/nope")
    assert resp.status_code == 404


async def test_evaluation_api_task_roundtrip(client: AsyncClient) -> None:
    await _seed_task(
        report={
            "test_results": {"tests_run": 2, "tests_passed": 2},
            "security_results": {"passed": True},
            "review_results": {"approved": True},
            "judge_results": {"ready": True},
        },
        state={"usage": [{"agent": "coder", "input_tokens": 5}]},
    )
    resp = await client.get("/api/evaluation/ev1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["succeeded"]
    assert body["test_pass_rate"] == 1.0
    assert body["cost"]["total_tokens"] == 5

    resp = await client.get("/api/evaluation/summary")
    assert resp.status_code == 200
    assert resp.json()["total_tasks"] == 1
    assert resp.json()["task_success_rate"] == 1.0


async def test_evaluation_api_list_filtered(client: AsyncClient) -> None:
    await _seed_task(task_id="a", state={"usage": []})
    await _seed_task(task_id="b", state={"usage": []})
    resp = await client.get("/api/evaluation?task_ids=a,b")
    assert resp.status_code == 200
    assert {t["task_id"] for t in resp.json()} == {"a", "b"}


async def test_evaluate_retrieval_quality(tmp_path: Path) -> None:
    from gitforce.app.rag.retriever import Retriever

    repo = _make_rag_repo(tmp_path)
    async with SessionLocal() as session:
        from gitforce.app.rag.indexer import RepositoryIndexer

        await RepositoryIndexer(session).index(str(repo), repo)
        retriever = Retriever(session)

        quality = await evaluate_retrieval(
            retriever,
            repository_url=str(repo),
            queries=[("square function", ["src/greeter.py"])],
            top_k=5,
        )
        assert quality.queries == 1
        assert quality.relevant_retrieved >= 1
        assert quality.recall_at_k == 1.0
        assert 0.0 < quality.precision_at_k <= 1.0


async def test_evaluate_retrieval_miss(tmp_path: Path) -> None:
    from gitforce.app.rag.retriever import Retriever

    repo = _make_rag_repo(tmp_path)
    async with SessionLocal() as session:
        from gitforce.app.rag.indexer import RepositoryIndexer

        await RepositoryIndexer(session).index(str(repo), repo)
        retriever = Retriever(session)

        quality = await evaluate_retrieval(
            retriever,
            repository_url=str(repo),
            queries=[("nonexistent thing", ["src/nowhere.py"])],
            top_k=5,
        )
        assert quality.recall_at_k == 0.0


async def test_judge_evaluator_uses_acceptance_criteria() -> None:
    from gitforce.app.config.settings import get_settings
    from gitforce.app.llm.providers import MockProvider

    case = BenchmarkCase(
        id="b1",
        repository_url="https://github.com/org/repo",
        issue_url="https://github.com/org/repo/issues/1",
        title="Add greeting",
        description="Add a greeting function",
        acceptance_criteria=["greet returns Hello"],
    )
    provider = MockProvider(get_settings())
    evaluator = JudgeEvaluator(provider)
    evaluation = _make_task_evaluation(succeeded=True)
    score = await evaluator.judge(case, evaluation)
    assert 0.0 <= score <= 1.0


def test_benchmark_case_roundtrip() -> None:
    case = BenchmarkCase(
        id="b1",
        repository_url="https://github.com/org/repo",
        issue_url="https://github.com/org/repo/issues/1",
        title="t",
        description="d",
        acceptance_criteria=["c1"],
    )
    data = case.to_dict()
    assert data["id"] == "b1"
    assert data["acceptance_criteria"] == ["c1"]


def _make_rag_repo(tmp_path: Path) -> Path:
    import subprocess

    repo = tmp_path / "evproj"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "greeter.py").write_text(
        '"""demo"""\nclass Greeter:\n    def hello(self, name: str) -> str:\n'
        "        return f\"Hello, {name}\"\n\ndef square(x: int) -> int:\n"
        "    return x * x\n"
    )
    (repo / "README.md").write_text("# Demo\nA demo project.\n")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-q", "-m", "init"], check=True
    )
    return repo
