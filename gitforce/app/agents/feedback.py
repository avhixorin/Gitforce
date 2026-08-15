from __future__ import annotations

from gitforce.app.agents.base import AgentBase
from gitforce.app.agents.models import FeedbackAnalysis
from gitforce.app.llm.models import LLMTaskType
from gitforce.app.llm.providers import BaseLLMProvider
from gitforce.prompts.loader import load_prompt


class FeedbackAnalyzer(AgentBase):
    """Classifies human feedback on a PR (Phase 9, sections 26-27).

    Reads the reviewer's comment together with the current requirements and
    implementation, then decides whether the feedback is actionable, which
    category it falls in, and whether it requires a full re-planning cycle
    rather than a blind patch.
    """

    task_type = LLMTaskType.CLASSIFICATION

    def __init__(self, provider: BaseLLMProvider) -> None:
        super().__init__(provider)

    async def analyze(
        self,
        *,
        comment: str,
        comment_url: str = "",
        requirements: dict,
        implementation_summary: str = "",
        diff: str = "",
    ) -> FeedbackAnalysis:
        import json

        prompt = (
            load_prompt("feedback", "feedback_analysis")
            .replace("{{comment}}", comment)
            .replace("{{comment_url}}", comment_url)
            .replace("{{requirements_json}}", json.dumps(requirements, indent=2))
            .replace("{{implementation_summary}}", implementation_summary)
            .replace("{{diff}}", diff)
        )
        return await self.run_structured(
            prompt,
            FeedbackAnalysis,
            task_type=LLMTaskType.CLASSIFICATION,
            max_tokens=1200,
        )