from __future__ import annotations

import asyncio

from gitforce.app.agents import models as agent_models
from gitforce.app.llm.providers import BaseLLMProvider
from gitforce.app.orchestration.graph import (
    build_graph,
    route_after_feedback,
    route_after_requirements,
    route_after_tester,
)
from gitforce.app.orchestration.state import ForgeState

TR = agent_models.TestResults
RequirementsAnalysis = agent_models.RequirementsAnalysis
JudgeDecision = agent_models.JudgeDecision
FeedbackAnalysis = agent_models.FeedbackAnalysis
FeedbackCategory = agent_models.FeedbackCategory


def test_route_after_requirements_ambiguous() -> None:
    state: ForgeState = {
        "requirements": RequirementsAnalysis(
            problem="", ambiguities=["a", "b"]
        )
    }
    assert route_after_requirements(state) == "needs_clarification"


def test_route_after_requirements_clear() -> None:
    state: ForgeState = {
        "requirements": RequirementsAnalysis(
            problem="p", acceptance_criteria=["c"]
        )
    }
    assert route_after_requirements(state) == "planner"


def test_route_after_tester_passed() -> None:
    state: ForgeState = {
        "test_results": TR(passed=True, tests_run=1, tests_passed=1),
    }
    assert route_after_tester(state) == "security"


def test_route_after_tester_failed_under_limit() -> None:
    state: ForgeState = {
        "test_results": TR(passed=False, tests_failed=1),
        "fix_analysis_steps": [{"root_cause": "x"}],
    }
    assert route_after_tester(state) == "failure_analyzer"


def test_route_after_tester_failed_over_limit() -> None:
    state: ForgeState = {
        "test_results": TR(passed=False, tests_failed=1),
        "fix_analysis_steps": [{"root_cause": f"{i}"} for i in range(5)],
    }
    assert route_after_tester(state) == "failed"


def test_graph_topology_runs() -> None:
    graph = build_graph()
    state: ForgeState = {
        "requirements": RequirementsAnalysis(
            problem="p", acceptance_criteria=["c"]
        ),
        # Pre-seeded so the placeholder nodes terminate the graph.
        "test_results": TR(passed=True, tests_run=1, tests_passed=1),
        "judge_results": JudgeDecision(ready=True),
    }
    result = asyncio.run(
        graph.ainvoke(state, config={"configurable": {"thread_id": "test-1"}})
    )
    assert result["iteration"] >= 1


def test_failed_node_marks_task_failed_with_error() -> None:
    """Section 20: the exhausted-fix-loop terminal must fail the task, not
    complete it."""
    from unittest.mock import AsyncMock

    from gitforce.app.orchestration.nodes import AgentContext, failed_node

    service = AsyncMock()
    service.fail_task = AsyncMock()
    provider: BaseLLMProvider = None  # type: ignore[assignment]
    ctx = AgentContext(task_service=service, provider=provider)

    state: ForgeState = {
        "task_id": "t-fail-1",
        "test_results": TR(
            passed=False, tests_run=1, tests_failed=1, failures=["boom"]
        ),
    }
    result = asyncio.run(failed_node(state, ctx))
    assert result["status"] == "failed"
    service.fail_task.assert_awaited_once_with(
        "t-fail-1",
        "Fix loop exhausted: tests never passed: boom",
    )


def test_route_after_feedback_approval_comples() -> None:
    state: ForgeState = {
        "feedback_analyses": [
            FeedbackAnalysis(actionable=False, category=FeedbackCategory.APPROVAL)
        ],
        "pr_cycles": 1,
    }
    assert route_after_feedback(state) == "finalize"


def test_route_after_feedback_architecture_replans() -> None:
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