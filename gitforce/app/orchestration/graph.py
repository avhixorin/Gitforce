from __future__ import annotations

from collections.abc import Callable

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy

from gitforce.app.config.settings import get_settings
from gitforce.app.orchestration.nodes import (
    AgentContext,
    coder_node,
    delivery_node,
    failed_node,
    failure_analyzer_node,
    feedback_node,
    finalize_node,
    judge_node,
    needs_clarification_node,
    planner_node,
    repository_node,
    requirements_node,
    reviewer_node,
    security_node,
    tester_node,
)
from gitforce.app.orchestration.state import ForgeState

# Retry transient failures (LLM timeouts, 5xx, network) up to 3 attempts
# with exponential backoff. Permanent failures propagate to the supervisor.
_RETRY_POLICY = RetryPolicy(max_attempts=3)


class NodeFactory:
    """Binds graph node functions to a shared AgentContext."""

    def __init__(self, ctx: AgentContext) -> None:
        self._ctx = ctx

    def _bind(self, fn: Callable) -> Callable:
        async def wrapped(state: ForgeState, config: RunnableConfig) -> dict:
            return await fn(state, self._ctx)

        return wrapped

    @property
    def nodes(self) -> dict[str, Callable]:
        return {
            "repository": self._bind(repository_node),
            "requirements": self._bind(requirements_node),
            "planner": self._bind(planner_node),
            "coder": self._bind(coder_node),
            "needs_clarification": self._bind(needs_clarification_node),
            "tester": self._bind(tester_node),
            "failure_analyzer": self._bind(failure_analyzer_node),
            "security": self._bind(security_node),
            "reviewer": self._bind(reviewer_node),
            "judge": self._bind(judge_node),
            "delivery": self._bind(delivery_node),
            "feedback": self._bind(feedback_node),
            "finalize": self._bind(finalize_node),
            "failed": self._bind(failed_node),
        }


def route_after_requirements(state: ForgeState) -> str:
    """Supervisor decision after requirements analysis (section 10).

    Ambiguous requirements pause for human clarification; otherwise continue
    to planning.
    """
    requirements = state.get("requirements")
    if requirements is not None and requirements.is_ambiguous:
        return "needs_clarification"
    return "planner"


def _fix_attempts(state: ForgeState) -> int:
    return len(state.get("fix_analysis_steps") or [])


def route_after_tester(state: ForgeState) -> str:
    """Section 20 failure/fix loop: failed tests bounce back to the coder.

    The failure analyzer names the root cause, then the coder re-runs with
    the fix guidance. We cap the loop with max_fix_iterations (default 5);
    hitting the cap produces a failure report (section 20).
    """
    results = state.get("test_results")
    if results is None or results.passed:
        return "security"
    max_fix = get_settings().max_fix_iterations
    if _fix_attempts(state) < max_fix:
        return "failure_analyzer"
    return "failed"


def supervise(state: ForgeState) -> str:
    """Supervisor check after the judge (section 8.1).

    The judge decides whether the work is ready; when ready we proceed to
    PR delivery (Phase 8), otherwise loop back to the coder (up to
    max_workflow_iterations) and re-implement.
    """
    judge = state.get("judge_results")
    if judge is not None and judge.ready:
        return "delivery"
    max_iterations = get_settings().max_workflow_iterations
    if _fix_attempts(state) < max_iterations:
        return "coder"
    return "delivery"


def route_after_feedback(state: ForgeState) -> str:
    """Phase 9 router: decide whether reviewer feedback requires re-planning.

    If the reviewer requested a meaningful change we loop back to the
    repository (re-analysis) and planner (section 28 re-engineering
    workflow), capped by ``max_feedback_iterations``. Approval or
    non-actionable feedback proceeds to finalize.
    """
    analyses = state.get("feedback_analyses") or []
    if not analyses:
        return "finalize"
    needs_replan = any(a.requires_replanning and a.actionable for a in analyses)
    if not needs_replan:
        return "finalize"
    cycles = state.get("pr_cycles") or 0
    if cycles > get_settings().max_feedback_iterations:
        return "finalize"
    return "repository"


def build_graph(checkpointer=None, ctx: AgentContext | None = None):
    """Build and compile the Gitforce LangGraph.

    ``ctx`` provides the real agent implementations; when omitted a set of
    placeholder nodes is used so graph wiring is testable standalone.
    ``checkpointer`` is a LangGraph BaseCheckpointSaver; defaults to
    in-memory.
    """
    if ctx is not None:
        nodes: dict[str, Callable] = NodeFactory(ctx).nodes
    else:
        node_names = (
            "repository",
            "requirements",
            "planner",
            "coder",
            "needs_clarification",
            "tester",
            "failure_analyzer",
            "security",
            "reviewer",
            "judge",
            "delivery",
            "feedback",
            "finalize",
            "failed",
        )
        nodes = dict.fromkeys(node_names, _placeholder_node)

    graph = StateGraph(ForgeState)
    for name, node in nodes.items():
        graph.add_node(name, node, retry_policy=_RETRY_POLICY)

    graph.add_edge(START, "repository")
    graph.add_edge("repository", "requirements")
    graph.add_conditional_edges(
        "requirements",
        route_after_requirements,
        {
            "needs_clarification": "needs_clarification",
            "planner": "planner",
        },
    )
    graph.add_edge("planner", "coder")
    graph.add_edge("coder", "tester")
    graph.add_conditional_edges(
        "tester",
        route_after_tester,
        {
            "failure_analyzer": "failure_analyzer",
            "security": "security",
            "failed": "failed",
            "finalize": "finalize",
        },
    )
    graph.add_edge("failure_analyzer", "coder")
    graph.add_edge("security", "reviewer")
    graph.add_edge("reviewer", "judge")
    graph.add_conditional_edges(
        "judge",
        supervise,
        {"coder": "coder", "delivery": "delivery"},
    )
    graph.add_edge("needs_clarification", "planner")
    graph.add_edge("delivery", "feedback")
    graph.add_conditional_edges(
        "feedback",
        route_after_feedback,
        {"repository": "repository", "finalize": "finalize"},
    )
    graph.add_edge("finalize", END)
    graph.add_edge("failed", END)

    saver = checkpointer or MemorySaver()
    return graph.compile(checkpointer=saver)


async def _placeholder_node(state: ForgeState, config: RunnableConfig) -> dict:
    return {"iteration": state.get("iteration", 0) + 1}