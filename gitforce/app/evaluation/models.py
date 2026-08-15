from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class AgentStep(BaseModel):
    """One traced step of an agent run (section 42 trajectory evaluation)."""

    agent: str
    started_at: datetime | None = None
    completed_at: datetime | None = None
    status: str = "completed"
    attempts: int = 0
    tokens_used: int = 0
    elapsed_ms: float = 0.0
    error: str = ""


class TrajectoryEvaluation(BaseModel):
    """Ordered execution trace plus cycle/retry statistics for a task."""

    task_id: str = ""
    steps: list[AgentStep] = Field(default_factory=list)
    iteration_count: int = 0
    retry_count: int = 0
    reviewer_cycles: int = 0
    total_elapsed_ms: float = 0.0


class RetrievalQuality(BaseModel):
    """Whether relevant files/chunks were retrieved (section 42)."""

    queries: int = 0
    relevant_retrieved: int = 0
    recall_at_k: float = 0.0
    precision_at_k: float = 0.0


class CostSummary(BaseModel):
    """Cost per task / per agent (section 42)."""

    total_tokens: int = 0
    total_cost_usd: float = 0.0
    total_latency_ms: float = 0.0
    calls: int = 0
    per_agent: dict[str, AgentCost] = Field(default_factory=dict)


class AgentCost(BaseModel):
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    calls: int = 0


class TaskEvaluation(BaseModel):
    """Complete evaluation of one task against section 42 metrics."""

    task_id: str
    issue_url: str = ""
    repository_url: str = ""
    status: str = ""
    succeeded: bool = False
    task_success: bool = False
    test_pass_rate: float = 0.0
    planning_quality: float = 0.0
    code_quality: float = 0.0
    security_passed: bool = True
    reviewer_accepted: bool = False
    judge_ready: bool = False
    iteration_count: int = 0
    cost: CostSummary = Field(default_factory=CostSummary)
    time_ms: float = 0.0
    trajectory: TrajectoryEvaluation = Field(
        default_factory=lambda: TrajectoryEvaluation()
    )
    retrieval: RetrievalQuality | None = None


class EvaluationSummary(BaseModel):
    """Aggregate metrics across a set of tasks (section 42)."""

    total_tasks: int = 0
    succeeded: int = 0
    task_success_rate: float = 0.0
    avg_test_pass_rate: float = 0.0
    avg_planning_quality: float = 0.0
    avg_code_quality: float = 0.0
    security_pass_rate: float = 0.0
    reviewer_acceptance_rate: float = 0.0
    avg_iteration_count: float = 0.0
    avg_cost_per_task: float = 0.0
    avg_time_per_task_ms: float = 0.0
    total_cost_usd: float = 0.0
    tasks: list[TaskEvaluation] = Field(default_factory=list)
