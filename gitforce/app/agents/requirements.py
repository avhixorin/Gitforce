from __future__ import annotations

import json

from gitforce.app.agents.base import AgentBase
from gitforce.app.agents.models import RequirementsAnalysis
from gitforce.app.llm.models import LLMTaskType
from gitforce.app.llm.providers import BaseLLMProvider
from gitforce.prompts.loader import load_prompt


class RequirementsAgent(AgentBase):
    task_type = LLMTaskType.SUMMARIZATION

    def __init__(self, provider: BaseLLMProvider) -> None:
        super().__init__(provider)

    async def analyze(
        self,
        issue: dict,
        comments: list[dict] | None = None,
        feedback: list[dict] | None = None,
    ) -> RequirementsAnalysis:
        prompt = (
            load_prompt("requirements", "analyze")
            .replace("{{issue_json}}", json.dumps(issue, indent=2))
            .replace(
                "{{comments_json}}",
                json.dumps(comments or [], indent=2),
            )
            .replace(
                "{{feedback_json}}",
                json.dumps(feedback or [], indent=2),
            )
        )
        return await self.run_structured(
            prompt,
            RequirementsAnalysis,
            task_type=LLMTaskType.SUMMARIZATION,
            max_tokens=1200,
        )