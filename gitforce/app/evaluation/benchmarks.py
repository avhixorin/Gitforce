from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel

from gitforce.app.agents.base import AgentBase
from gitforce.app.evaluation.models import TaskEvaluation
from gitforce.app.llm.providers import BaseLLMProvider
from gitforce.prompts.loader import load_prompt


class BenchmarkCase(BaseModel):
    """One task benchmark: repository + issue + acceptance criteria.

    The criteria power the LLM-as-Judge (section 43) so scoring is not
    based on the coding agent's own explanation.
    """

    id: str
    repository_url: str
    issue_url: str
    title: str
    description: str
    acceptance_criteria: list[str] = []
    relevant_files: list[str] = []
    expected: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "repository_url": self.repository_url,
            "issue_url": self.issue_url,
            "title": self.title,
            "description": self.description,
            "acceptance_criteria": self.acceptance_criteria,
            "relevant_files": self.relevant_files,
            "expected": self.expected,
        }


@dataclass
class BenchmarkResult:
    """Outcome of running one benchmark case through the platform."""

    case_id: str
    succeeded: bool
    evaluation: TaskEvaluation | None = None
    error: str = ""
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "succeeded": self.succeeded,
            "error": self.error,
            "metadata": self.metadata,
        }


@dataclass
class BenchmarkRun:
    """Aggregate result across all cases in a benchmark."""

    cases: int = 0
    passed: int = 0
    acceptance_rate: float = 0.0
    results: list[BenchmarkResult] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "cases": self.cases,
            "passed": self.passed,
            "acceptance_rate": self.acceptance_rate,
            "results": [r.to_dict() for r in self.results],
        }


class JudgeEvaluator:
    """LLM-as-Judge scoring of a completed task against its acceptance
    criteria (section 43). Uses an independent evaluation context so the
    coding agent's own summary is not taken at face value."""

    def __init__(self, provider: BaseLLMProvider) -> None:
        self._agent = AgentBase(provider)

    async def judge(self, case: BenchmarkCase, evaluation: TaskEvaluation) -> float:
        prompt = (
            load_prompt("judge", "judge_evaluation")
            .replace("{{title}}", case.title)
            .replace("{{description}}", case.description)
            .replace("{{acceptance_criteria}}", "\n".join(case.acceptance_criteria))
            .replace("{{task_status}}", evaluation.status)
            .replace("{{test_pass_rate}}", str(evaluation.test_pass_rate))
            .replace("{{security_passed}}", str(evaluation.security_passed))
            .replace("{{code_quality}}", str(evaluation.code_quality))
            .replace("{{judge_ready}}", str(evaluation.judge_ready))
            .replace("{{reviewer_accepted}}", str(evaluation.reviewer_accepted))
        )
        decision = await self._agent.run_structured(
            prompt, _JudgeScore, max_tokens=512
        )
        return decision.score


class _JudgeScore(BaseModel):
    """Final acceptance score produced by the LLM-as-Judge."""

    score: float = 0.0
    rationale: str = ""
