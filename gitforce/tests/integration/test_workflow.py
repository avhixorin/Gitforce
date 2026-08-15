from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from langgraph.checkpoint.memory import MemorySaver

from gitforce.app.config.settings import get_settings
from gitforce.app.database.models import Task, TaskStatus
from gitforce.app.database.repositories import TaskRepository
from gitforce.app.database.session import SessionLocal
from gitforce.app.llm.providers import MockProvider
from gitforce.app.orchestration.workflow import LangGraphWorkflow
from gitforce.app.services.tasks import TaskService
from gitforce.tests.helpers import smart_responder


def _git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "proj"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "__init__.py").write_text("")
    (repo / "src" / "app.py").write_text(
        "def greet(name: str) -> str:\n    return f'hello {name}'\n"
    )
    (repo / "README.md").write_text("# Proj\nA sample python project.\n")
    (repo / "pyproject.toml").write_text(
        "[project]\nname = 'proj'\n"
        "[tool.ruff.lint]\nignore = ['S101', 'I001']\n"
    )
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-q", "-m", "init"], check=True
    )
    return repo


@pytest.fixture(autouse=True)
async def _db():
    from gitforce.app.database import models
    from gitforce.app.database.session import engine

    async with engine.begin() as conn:
        await conn.run_sync(models.Base.metadata.drop_all)
        await conn.run_sync(models.Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(models.Base.metadata.drop_all)


async def _run_workflow(
    task: Task, responder
) -> Task:
    provider = MockProvider(get_settings(), responder=responder)
    async with SessionLocal() as session:
        saved = await TaskRepository(session).create(task)
        service = TaskService(session)
        workflow = LangGraphWorkflow(service, provider, checkpointer=MemorySaver())
        await workflow.run(saved.id)
        return await service.get_task(saved.id)


async def test_langgraph_workflow_completes(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    task = Task(
        repository_url=str(repo),
        issue_url="https://github.com/org/proj/issues/1",
        status=TaskStatus.RUNNING,
    )
    result = await _run_workflow(task, smart_responder)
    assert result.status is TaskStatus.COMPLETED
    state = result.state
    assert state["repository_analysis"]["test_framework"] == "pytest"
    assert state["requirements"]["problem"] == "Add a greeting endpoint"
    assert state["plan"]["approach"] == "Add a new route"
    assert result.plan is not None
    assert result.plan["summary"] == "Add greeting endpoint"
    assert state["coding_intent"]["summary"] == "Add greeting endpoint"
    # Phase 5: repo was indexed and the planner received retrieved context.
    assert state.get("commit_sha")
    assert "src/app.py" in state.get("retrieved_context", "")


async def test_langgraph_pauses_on_ambiguous_requirements(
    tmp_path: Path,
) -> None:
    repo = _git_repo(tmp_path)

    def ambiguous_responder(req):
        prompt = req.messages[0].content
        if "Requirements Analysis Agent" in prompt:
            return (
                '{"problem": "", "requirements": [], "acceptance_criteria": [], '
                '"constraints": [], "assumptions": [], "ambiguities": ["a", "b"], '
                '"risk_factors": []}'
            )
        return smart_responder(req)

    task = Task(
        repository_url=str(repo),
        issue_url="https://github.com/org/proj/issues/2",
        status=TaskStatus.RUNNING,
    )
    result = await _run_workflow(task, ambiguous_responder)
    assert result.status is TaskStatus.PAUSED
    assert result.state["status"] == "paused"


async def test_resume_after_clarification_completes(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)

    def ambiguous_responder(req):
        prompt = req.messages[0].content
        if "Requirements Analysis Agent" in prompt:
            return (
                '{"problem": "", "requirements": [], "acceptance_criteria": [], '
                '"constraints": [], "assumptions": [], "ambiguities": ["a", "b"], '
                '"risk_factors": []}'
            )
        return smart_responder(req)

    task = Task(
        repository_url=str(repo),
        issue_url="https://github.com/org/proj/issues/3",
        status=TaskStatus.RUNNING,
    )
    provider = MockProvider(get_settings(), responder=ambiguous_responder)

    async with SessionLocal() as session:
        saved = await TaskRepository(session).create(task)
        service = TaskService(session)
        checkpointer = MemorySaver()
        workflow = LangGraphWorkflow(service, provider, checkpointer=checkpointer)
        await workflow.run(saved.id)
        paused = await service.get_task(saved.id)
        assert paused.status is TaskStatus.PAUSED

        # Human answers the clarification; workflow resumes and completes.
        await workflow.resume(saved.id, answer="Use the greeting module")
        result = await service.get_task(saved.id)
        assert result.status is TaskStatus.COMPLETED
        assert result.state["metadata"]["clarification"] == "Use the greeting module"


async def test_fix_loop_routes_through_failure_analyzer(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    calls = {"implement": 0}

    def flaky_responder(req):
        prompt = req.messages[0].content
        if "Produce the actual file changes" in prompt:
            calls["implement"] += 1
            if calls["implement"] == 1:
                # First attempt: a broken test to force the fix loop.
                return _broken_implement_json()
            return smart_responder(req)
        return smart_responder(req)

    task = Task(
        repository_url=str(repo),
        issue_url="https://github.com/org/proj/issues/4",
        status=TaskStatus.RUNNING,
    )
    result = await _run_workflow(task, flaky_responder)
    assert result.status is TaskStatus.COMPLETED
    state = result.state
    assert state["test_results"]["passed"] is True
    assert len(state["fix_analysis_steps"]) >= 1
    assert state["fix_analysis"]["root_cause"] == "greet function not defined"


def _broken_implement_json() -> str:
    return """{
  "summary": "Broken implementation",
  "files": [
    {"path": "src/app.py", "content": "def greet(name: str) -> str:\\n    return 'broken'\\n"},
    {"path": "tests/test_greet.py", "content": "from src.app import greet\\n\\ndef test_greet():\\n    assert greet('x') == 'Hello, x! x'\\n"}
  ]
}"""