from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict

from gitforce.app.agents.models import (
    CodingImplementation,
    FailureAnalysis,
    FeedbackAnalysis,
    ImplementationPlan,
    JudgeDecision,
    RepositoryAnalysis,
    RequirementsAnalysis,
    ReviewDecision,
    SecurityResults,
    TestResults,
)
from gitforce.app.llm.models import Usage


class ForgeState(TypedDict, total=False):
    """Persistent workflow state (Requirement section 34).

    LangGraph checkpoints this after every node, enabling restart recovery,
    task resumption, human-approval interruption, and iteration history.
    """

    # Task identity
    task_id: str
    repository_url: str
    issue_url: str

    # Discovery (Phase 1)
    repository: dict
    issue: dict
    issue_comments: list[dict]

    # Agent outputs (structured)
    repository_analysis: RepositoryAnalysis
    requirements: RequirementsAnalysis
    plan: ImplementationPlan
    coding_intent: dict
    implementation: CodingImplementation
    changes: Annotated[list[dict], operator.add]
    test_results: TestResults
    security_results: SecurityResults
    review_results: ReviewDecision
    judge_results: JudgeDecision
    fix_analysis: FailureAnalysis
    fix_analysis_steps: Annotated[list[dict], operator.add]
    pr: dict

    # Reviewer feedback
    reviewer_feedback: Annotated[list[dict], operator.add]
    feedback_analyses: Annotated[list[FeedbackAnalysis], operator.add]
    pr_cycles: int

    # PR iteration history (Requirement section 29)
    pr_iterations: Annotated[list[dict], operator.add]

    # Workflow control
    iteration: int
    status: str  # running | paused | completed | failed | cancelled
    errors: Annotated[list[dict], operator.add]
    retries: Annotated[list[dict], operator.add]

    # Cost / observability
    usage: Annotated[list[Usage], operator.add]

    # Any ephemeral data a node wants to stash
    metadata: dict[str, Any]
    retrieved_context: str
    commit_sha: str
    llm_calls: int
    tool_calls: int