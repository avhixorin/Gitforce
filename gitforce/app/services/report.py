from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from gitforce.app.agents.models import (
    CodingImplementation,
    ImplementationPlan,
    JudgeDecision,
    RepositoryAnalysis,
    RequirementsAnalysis,
    ReviewDecision,
    SecurityResults,
    TestResults,
)


@dataclass
class TaskReport:
    """Structured final report persisted to the task and rendered into the
    PR description (Phase 8; section 25 'ForgeAI Task Report')."""

    task_id: str
    issue_url: str
    repository_analysis: RepositoryAnalysis
    requirements: RequirementsAnalysis
    plan: ImplementationPlan
    implementation: CodingImplementation
    test_results: TestResults
    security_results: SecurityResults
    review_results: ReviewDecision
    judge_results: JudgeDecision
    changes: list[dict]

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "issue_url": self.issue_url,
            "repository_analysis": self.repository_analysis.model_dump(),
            "requirements": self.requirements.model_dump(),
            "plan": self.plan.model_dump(),
            "implementation": self.implementation.model_dump(),
            "test_results": self.test_results.model_dump(),
            "security_results": self.security_results.model_dump(),
            "review_results": self.review_results.model_dump(),
            "judge_results": self.judge_results.model_dump(),
            "changes": self.changes,
        }


def build_task_report(
    *,
    task_id: str,
    issue_url: str,
    repository_analysis: RepositoryAnalysis,
    requirements: RequirementsAnalysis,
    plan: ImplementationPlan,
    implementation: CodingImplementation,
    test_results: TestResults,
    security_results: SecurityResults,
    review_results: ReviewDecision,
    judge_results: JudgeDecision,
    changes: list[dict],
) -> TaskReport:
    return TaskReport(
        task_id=task_id,
        issue_url=issue_url,
        repository_analysis=repository_analysis,
        requirements=requirements,
        plan=plan,
        implementation=implementation,
        test_results=test_results,
        security_results=security_results,
        review_results=review_results,
        judge_results=judge_results,
        changes=changes,
    )