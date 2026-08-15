from __future__ import annotations

from datetime import datetime

from gitforce.app.database.models import Task, TaskEvent, TaskStatus
from gitforce.app.database.repositories import TaskRepository
from gitforce.app.evaluation.cost import aggregate_usage
from gitforce.app.evaluation.models import (
    AgentStep,
    EvaluationSummary,
    TaskEvaluation,
    TrajectoryEvaluation,
)


def _fraction(numerator: float, denominator: float) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def evaluate_task(task: Task, events: list[TaskEvent] | None = None) -> TaskEvaluation:
    """Compute section 42 metrics for a single task from its persisted
    state, report, and event trace."""
    state = dict(task.state or {})
    report = task.report or {}
    plan = report.get("plan") or {}
    implementation = report.get("implementation") or {}
    test_results = report.get("test_results") or {}
    security_results = report.get("security_results") or {}
    review_results = report.get("review_results") or {}
    judge_results = report.get("judge_results") or {}

    usage = state.get("usage") or []
    cost = aggregate_usage(list(usage))

    succeeded = task.status == TaskStatus.COMPLETED

    tests_run = int(test_results.get("tests_run") or 0)
    tests_passed = int(test_results.get("tests_passed") or 0)
    test_pass_rate = (
        _fraction(tests_passed, tests_run) if tests_run else 1.0
    )

    judge_ready = bool(judge_results.get("ready"))
    reviewer_accepted = bool(review_results.get("approved"))
    security_passed = bool(
        security_results.get("passed", True)
    ) and not any(
        f.get("severity") == "critical"
        for f in security_results.get("findings") or []
    )

    planning_quality = float(plan.get("quality_score") or 0.0)
    code_quality = float(
        implementation.get("quality_score")
        or review_results.get("score")
        or 0.0
    )

    time_ms = 0.0
    if task.completed_at and task.started_at:
        time_ms = (task.completed_at - task.started_at).total_seconds() * 1000

    trajectory = _trajectory(task, events)

    return TaskEvaluation(
        task_id=task.id,
        issue_url=task.issue_url,
        repository_url=task.repository_url,
        status=str(task.status.value),
        succeeded=succeeded,
        task_success=succeeded,
        test_pass_rate=test_pass_rate,
        planning_quality=planning_quality,
        code_quality=code_quality,
        security_passed=security_passed,
        reviewer_accepted=reviewer_accepted,
        judge_ready=judge_ready,
        iteration_count=task.iteration or 0,
        cost=cost,
        time_ms=round(time_ms, 2),
        trajectory=trajectory,
    )


def _trajectory(
    task: Task, events: list[TaskEvent] | None
) -> TrajectoryEvaluation:
    events = events or []
    steps: list[AgentStep] = []
    agent_started: dict[str, datetime] = {}
    for event in events:
        if not event.agent:
            continue
        if event.event.endswith(".started"):
            agent_started[event.agent] = event.created_at
        elif event.event.endswith(".completed"):
            started = agent_started.pop(event.agent, None)
            elapsed = 0.0
            if started:
                elapsed = (
                    event.created_at - started
                ).total_seconds() * 1000
            steps.append(
                AgentStep(
                    agent=event.agent,
                    started_at=started,
                    completed_at=event.created_at,
                    status="completed",
                    elapsed_ms=round(elapsed, 2),
                )
            )

    reviewer_cycles = int((task.state or {}).get("pr_cycles") or 0)
    total_elapsed = sum(s.elapsed_ms for s in steps)

    return TrajectoryEvaluation(
        task_id=task.id,
        steps=steps,
        iteration_count=task.iteration or 0,
        retry_count=task.retry_count or 0,
        reviewer_cycles=reviewer_cycles,
        total_elapsed_ms=round(total_elapsed, 2),
    )


def summarize(evaluations: list[TaskEvaluation]) -> EvaluationSummary:
    """Aggregate per-task evaluations into a section 42 summary."""
    if not evaluations:
        return EvaluationSummary()

    succeeded = sum(1 for e in evaluations if e.succeeded)
    security_passed = sum(1 for e in evaluations if e.security_passed)
    reviewer_accepted = sum(1 for e in evaluations if e.reviewer_accepted)

    return EvaluationSummary(
        total_tasks=len(evaluations),
        succeeded=succeeded,
        task_success_rate=_fraction(succeeded, len(evaluations)),
        avg_test_pass_rate=_fraction(
            sum(e.test_pass_rate for e in evaluations), len(evaluations)
        ),
        avg_planning_quality=_fraction(
            sum(e.planning_quality for e in evaluations), len(evaluations)
        ),
        avg_code_quality=_fraction(
            sum(e.code_quality for e in evaluations), len(evaluations)
        ),
        security_pass_rate=_fraction(security_passed, len(evaluations)),
        reviewer_acceptance_rate=_fraction(
            reviewer_accepted, len(evaluations)
        ),
        avg_iteration_count=_fraction(
            sum(e.iteration_count for e in evaluations), len(evaluations)
        ),
        avg_cost_per_task=_fraction(
            sum(e.cost.total_cost_usd for e in evaluations),
            len(evaluations),
        ),
        avg_time_per_task_ms=_fraction(
            sum(e.time_ms for e in evaluations), len(evaluations)
        ),
        total_cost_usd=round(
            sum(e.cost.total_cost_usd for e in evaluations), 6
        ),
        tasks=evaluations,
    )


class EvaluationService:
    """Loads tasks from the database and produces per-task + aggregate
    section 42 evaluations."""

    def __init__(self, repository: TaskRepository) -> None:
        self._repo = repository

    async def evaluate(self, task_id: str) -> TaskEvaluation | None:
        task = await self._repo.get(task_id)
        if task is None:
            return None
        events = await self._repo.list_events(task_id)
        return evaluate_task(task, events)

    async def evaluate_many(self, task_ids: list[str]) -> list[TaskEvaluation]:
        evaluations = []
        for task_id in task_ids:
            evaluation = await self.evaluate(task_id)
            if evaluation is not None:
                evaluations.append(evaluation)
        return evaluations

    async def summarize_all(self) -> EvaluationSummary:
        tasks = await self._repo.list_all()
        evaluations = []
        for task in tasks:
            events = await self._repo.list_events(task.id)
            evaluations.append(evaluate_task(task, events))
        return summarize(evaluations)
