from __future__ import annotations

import subprocess

import pytest

from gitforce.app.agents.delivery import DeliveryAgent, PRDescription
from gitforce.app.agents.models import (
    CodingImplementation,
    FileChange,
    ImplementationPlan,
    JudgeDecision,
    RepositoryAnalysis,
    RequirementsAnalysis,
    ReviewDecision,
    SecurityResults,
)
from gitforce.app.agents.models import TestResults as TR
from gitforce.app.config.settings import get_settings
from gitforce.app.github.git import GitError, GitWorktree
from gitforce.app.llm.providers import MockProvider
from gitforce.app.services.report import build_task_report


def _make_repo(tmp_path):
    repo = tmp_path / "proj"
    repo.mkdir()
    (repo / "app.py").write_text("def greet():\n    return 'hello'\n")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "t@t.io"], check=True
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.name", "t"], check=True
    )
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-q", "-m", "init"], check=True
    )
    return repo


def _sample_kwargs():
    return {
        "issue_url": "https://github.com/org/proj/issues/1",
        "task_id": "task-123",
        "repository_analysis": RepositoryAnalysis(languages=["python"]),
        "requirements": RequirementsAnalysis(problem="Add greeting"),
        "plan": ImplementationPlan(summary="Add greeting endpoint"),
        "implementation": CodingImplementation(
            files=[FileChange(path="src/app.py", content="")]
        ),
        "test_results": TR(passed=True, tests_run=1, tests_passed=1),
        "security_results": SecurityResults(passed=True),
        "review_results": ReviewDecision(approved=True),
        "judge_results": JudgeDecision(ready=True),
        "diff_stat": "1 file changed",
        "changes": [{"path": "src/app.py", "added_or_modified": True}],
    }


async def test_git_worktree_branch_commit_diff(tmp_path):
    repo = _make_repo(tmp_path)
    git = GitWorktree(repo)
    assert git.current_branch() in {"master", "main"}
    git.create_branch("feat/x")
    (repo / "app.py").write_text("def greet():\n    return 'hi'\n")
    git.add_all()
    sha = git.commit("feat: greet")
    assert sha
    assert git.diff_stat()
    assert git.diff()


async def test_git_worktree_commit_without_changes(tmp_path):
    repo = _make_repo(tmp_path)
    git = GitWorktree(repo)
    git.create_branch("feat/x")
    with pytest.raises(GitError):
        git.commit("empty commit")


async def test_delivery_agent_uses_model_title():
    settings = get_settings()

    def responder(req):
        return '{"title": "Add greeting", "body": "## Summary\\n\\ndone"}'

    agent = DeliveryAgent(MockProvider(settings, responder=responder))
    desc = await agent.describe(**_sample_kwargs())
    assert isinstance(desc, PRDescription)
    assert desc.title == "Add greeting"
    assert "## Summary" in desc.body


async def test_delivery_agent_fallback_when_empty():
    settings = get_settings()

    def responder(req):
        return '{"title": "", "body": ""}'

    agent = DeliveryAgent(MockProvider(settings, responder=responder))
    desc = await agent.describe(**_sample_kwargs())
    # Fallback template fills in a title and body.
    assert desc.title == "Add greeting endpoint"
    assert "## Summary" in desc.body


async def test_task_report_structure():
    report = build_task_report(
        task_id="task-123",
        issue_url="https://github.com/org/proj/issues/1",
        repository_analysis=RepositoryAnalysis(languages=["python"]),
        requirements=RequirementsAnalysis(problem="Add greeting"),
        plan=ImplementationPlan(summary="Add greeting endpoint"),
        implementation=CodingImplementation(
            files=[FileChange(path="src/app.py", content="")]
        ),
        test_results=TR(passed=True, tests_run=3, tests_passed=3),
        security_results=SecurityResults(passed=True, summary="No findings"),
        review_results=ReviewDecision(approved=True, score=0.9),
        judge_results=JudgeDecision(ready=True, overall_score=0.88),
        changes=[{"path": "src/app.py", "added_or_modified": True}],
    )
    data = report.to_dict()
    assert data["task_id"] == "task-123"
    assert data["issue_url"].startswith("https://github.com")
    assert data["requirements"]["problem"] == "Add greeting"
    assert data["changes"][0]["path"] == "src/app.py"
    assert data["judge_results"]["overall_score"] == 0.88
