from __future__ import annotations

import subprocess

from gitforce.app.agents.feedback import FeedbackAnalyzer
from gitforce.app.agents.models import (
    FeedbackAnalysis,
    FeedbackCategory,
    FeedbackSeverity,
)
from gitforce.app.config.settings import get_settings
from gitforce.app.github.git import GitWorktree
from gitforce.app.llm.providers import MockProvider
from gitforce.app.orchestration.graph import route_after_feedback
from gitforce.app.orchestration.state import ForgeState


async def test_feedback_analyzer_parses_architecture_concern():
    settings = get_settings()

    def responder(req):
        return (
            '{"actionable": true, "category": "architecture_concern", '
            '"severity": "high", "requires_replanning": true, '
            '"affected_requirements": ["Use shared rate limiter"], '
            '"affected_files": ["src/app.py"], "summary": "Reuse limiter", '
            '"reason": "Do not reinvent."}'
        )

    agent = FeedbackAnalyzer(MockProvider(settings, responder=responder))
    analysis = await agent.analyze(
        comment="Use the existing shared rate limiter instead of adding a new one.",
        requirements={"requirements": ["Add rate limiting"]},
        implementation_summary="Added a new rate limiter.",
    )
    assert isinstance(analysis, FeedbackAnalysis)
    assert analysis.actionable is True
    assert analysis.category is FeedbackCategory.ARCHITECTURE_CONCERN
    assert analysis.severity is FeedbackSeverity.HIGH
    assert analysis.requires_replanning is True
    assert analysis.affected_files == ["src/app.py"]


async def test_feedback_analyzer_minor_change_not_replanning():
    settings = get_settings()

    def responder(req):
        return (
            '{"actionable": true, "category": "minor_requested_change", '
            '"severity": "low", "requires_replanning": false, '
            '"affected_requirements": [], "affected_files": [], '
            '"summary": "Rename variable", "reason": "Style"}'
        )

    agent = FeedbackAnalyzer(MockProvider(settings, responder=responder))
    analysis = await agent.analyze(
        comment="Please rename `foo` to `bar`.",
        requirements={"requirements": []},
    )
    assert analysis.actionable is True
    assert analysis.category is FeedbackCategory.MINOR_REQUESTED_CHANGE
    assert analysis.requires_replanning is False


def test_route_after_feedback_no_analyses():
    assert route_after_feedback(ForgeState()) == "finalize"


def test_route_after_feedback_approval():
    state: ForgeState = {
        "feedback_analyses": [
            FeedbackAnalysis(actionable=False, category=FeedbackCategory.APPROVAL)
        ]
    }
    assert route_after_feedback(state) == "finalize"


def test_route_after_feedback_replanning():
    state: ForgeState = {
        "feedback_analyses": [
            FeedbackAnalysis(
                actionable=True,
                category=FeedbackCategory.ARCHITECTURE_CONCERN,
                requires_replanning=True,
            )
        ],
        "pr_cycles": 1,
    }
    assert route_after_feedback(state) == "repository"


def test_route_after_feedback_replanning_exhausted():
    state: ForgeState = {
        "feedback_analyses": [
            FeedbackAnalysis(
                actionable=True,
                category=FeedbackCategory.REQUIREMENT_CHANGE,
                requires_replanning=True,
            )
        ],
        "pr_cycles": 99,
    }
    assert route_after_feedback(state) == "finalize"


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


def test_git_ensure_branch_resumes_existing(tmp_path):
    repo = _make_repo(tmp_path)
    git = GitWorktree(repo)
    git.create_branch("forgeai/abc12345")
    (repo / "app.py").write_text("def greet():\n    return 'hi'\n")
    git.add_all()
    first = git.commit("feat: first")
    assert first
    # Re-planning cycle: branch already exists, must resume it.
    git.ensure_branch("forgeai/abc12345")
    assert git.current_branch() == "forgeai/abc12345"
    assert git.current_sha() == first
    # A fresh ensure on a new branch creates it.
    git.ensure_branch("forgeai/new")
    assert git.current_branch() == "forgeai/new"


def test_git_has_changes_and_commit_skip(tmp_path):
    repo = _make_repo(tmp_path)
    git = GitWorktree(repo)
    git.ensure_branch("forgeai/abc12345")
    assert not git.has_changes()
    (repo / "app.py").write_text("def greet():\n    return 'hi'\n")
    assert git.has_changes()
    git.add_all()
    git.commit("feat: change")
    assert not git.has_changes()
