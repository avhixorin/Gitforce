from __future__ import annotations

from pydantic import BaseModel

from gitforce.app.agents.base import AgentBase
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
from gitforce.app.llm.models import LLMTaskType
from gitforce.app.llm.providers import BaseLLMProvider
from gitforce.prompts.loader import load_prompt


class PRDescription(BaseModel):
    body: str
    title: str = ""


class DeliveryAgent(AgentBase):
    """Builds the human-readable PR description (Phase 8, section 25).

    Uses a dedicated LLM call to turn the structured workflow outputs into
    a markdown PR body following the section 25 template, then falls back
    to a deterministic template if the model output is unusable.
    """

    task_type = LLMTaskType.SUMMARIZATION

    def __init__(self, provider: BaseLLMProvider) -> None:
        super().__init__(provider)

    async def describe(
        self,
        *,
        issue_url: str,
        task_id: str,
        repository_analysis: RepositoryAnalysis,
        requirements: RequirementsAnalysis,
        plan: ImplementationPlan,
        implementation: CodingImplementation,
        test_results: TestResults,
        security_results: SecurityResults,
        review_results: ReviewDecision,
        judge_results: JudgeDecision,
        diff_stat: str = "",
        changes: list[dict] | None = None,
    ) -> PRDescription:
        context = _pr_context(
            issue_url=issue_url,
            task_id=task_id,
            repository_analysis=repository_analysis,
            requirements=requirements,
            plan=plan,
            implementation=implementation,
            test_results=test_results,
            security_results=security_results,
            review_results=review_results,
            judge_results=judge_results,
            diff_stat=diff_stat,
            changes=changes,
        )
        prompt = (
            load_prompt("delivery", "pr_description")
            .replace("{{issue_url}}", issue_url)
            .replace("{{task_id}}", task_id)
            .replace("{{context}}", context)
        )
        body = await self.run_structured(
            prompt,
            PRDescription,
            task_type=LLMTaskType.SUMMARIZATION,
            max_tokens=2500,
        )
        if not body.body.strip():
            body.body = _fallback_body(context)
        if not body.title:
            body.title = plan.summary or requirements.problem or "Automated changes"
        return body


def _pr_context(**values: object) -> str:
    import json

    def safe(value: object) -> object:
        if hasattr(value, "model_dump"):
            return value.model_dump()  # type: ignore[union-attr]
        return value

    payload = {k: safe(v) for k, v in values.items()}
    return json.dumps(payload, indent=2, default=str)


def _fallback_body(context: str) -> str:
    import json

    try:
        data = json.loads(context)
    except json.JSONDecodeError:
        return "ForgeAI automated changes.\n\nSee the ForgeAI Task Report."
    requirements = data.get("requirements", {})
    plan = data.get("plan", {})
    impl = data.get("implementation", {})
    test = data.get("test_results", {})
    security = data.get("security_results", {})
    changes = data.get("changes") or [
        {"path": f.get("path")} for f in impl.get("files", [])
    ]
    lines = [
        "## Summary",
        plan.get("summary") or impl.get("summary") or "",
        "",
        "## Problem",
        requirements.get("problem", ""),
        "",
        "## Requirements",
        *_bullet(requirements.get("requirements", [])),
        "## Implementation",
        *_bullet(plan.get("implementation_steps", [])),
        "## Files Changed",
        *_bullet([c.get("path") for c in changes]),
        "## Tests",
        f"Tests run: {test.get('tests_run', 0)}; passed: "
        f"{test.get('tests_passed', 0)}; failed: {test.get('tests_failed', 0)}.",
        "## Security Review",
        security.get("summary") or "No findings reported.",
        "## Risks",
        *_bullet(plan.get("risks", [])),
        "## Alternatives Considered",
        *_bullet(plan.get("alternatives_considered", [])),
        "## Related Issue",
        data.get("issue_url", ""),
        "",
        "## ForgeAI Task Report",
        f"Task: {data.get('task_id', '')}",
    ]
    return "\n".join(lines)


def _bullet(items: list) -> list[str]:
    return [f"- {i}" for i in items if i] or ["- N/A", ""]
