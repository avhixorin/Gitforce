from __future__ import annotations

from gitforce.app.agents.base import AgentBase
from gitforce.app.agents.models import (
    CodingImplementation,
    CodingIntent,
    ImplementationPlan,
)
from gitforce.app.llm.models import LLMTaskType
from gitforce.app.llm.providers import BaseLLMProvider
from gitforce.prompts.loader import load_prompt


class CoderAgent(AgentBase):
    task_type = LLMTaskType.CODE_GENERATION

    def __init__(self, provider: BaseLLMProvider) -> None:
        super().__init__(provider)

    async def plan(
        self,
        repository_context: str,
        requirements: dict,
        relevant_files: list[str] | None = None,
    ) -> CodingIntent:
        prompt = (
            load_prompt("coder", "plan")
            .replace("{{repository_context}}", repository_context)
            .replace("{{requirements_json}}", str(requirements))
            .replace(
                "{{relevant_files}}", "\n".join(relevant_files or [])
            )
        )
        return await self.run_structured(
            prompt,
            CodingIntent,
            task_type=LLMTaskType.CODE_GENERATION,
            max_tokens=1200,
        )

    async def implement(
        self,
        repository_context: str,
        requirements: dict,
        plan: dict,
        intent: dict,
        existing_files: list[str],
        fix_analysis: dict | None = None,
        test_results: dict | None = None,
    ) -> CodingImplementation:
        prompt = (
            load_prompt("coder", "implement")
            .replace("{{repository_context}}", repository_context)
            .replace("{{requirements_json}}", str(requirements))
            .replace("{{plan_json}}", str(plan))
            .replace("{{intent_json}}", str(intent))
            .replace("{{existing_files}}", "\n".join(existing_files))
        )
        if fix_analysis:
            prompt = prompt.replace(
                "{{fix_analysis_json}}", str(fix_analysis)
            )
        else:
            prompt = prompt.replace("{{fix_analysis_json}}", "{}")
        if test_results:
            prompt = prompt.replace(
                "{{test_results_json}}", str(test_results)
            )
        else:
            prompt = prompt.replace("{{test_results_json}}", "{}")
        return await self.run_structured(
            prompt,
            CodingImplementation,
            task_type=LLMTaskType.CODE_GENERATION,
            max_tokens=4000,
        )


class PlannerAgent(AgentBase):
    task_type = LLMTaskType.ARCHITECTURE

    def __init__(self, provider: BaseLLMProvider) -> None:
        super().__init__(provider)

    async def create_plan(
        self,
        repository_analysis: dict,
        requirements: dict,
        retrieved_context: str = "",
    ) -> ImplementationPlan:
        prompt = (
            load_prompt("planner", "plan")
            .replace(
                "{{repository_analysis_json}}", str(repository_analysis)
            )
            .replace("{{requirements_json}}", str(requirements))
            .replace(
                "{{retrieved_context}}", retrieved_context or "(none)"
            )
        )
        return await self.run_structured(
            prompt,
            ImplementationPlan,
            task_type=LLMTaskType.ARCHITECTURE,
            max_tokens=1500,
        )