from __future__ import annotations

from gitforce.app.agents.base import AgentBase
from gitforce.app.agents.models import FailureAnalysis
from gitforce.app.llm.providers import BaseLLMProvider
from gitforce.prompts.loader import load_prompt


class FailureAnalyzer:
    """Identifies the root cause of test failures so the coder can fix them (section 20)."""

    def __init__(self, provider: BaseLLMProvider) -> None:
        self._agent = AgentBase(provider)

    async def analyze(
        self,
        requirements: dict,
        plan: dict,
        test_results: dict,
        implementation_summary: str,
    ) -> FailureAnalysis:
        prompt = (
            load_prompt("failure", "analyze")
            .replace("{{requirements_json}}", str(requirements))
            .replace("{{plan_json}}", str(plan))
            .replace("{{test_results_json}}", str(test_results))
            .replace("{{implementation_summary}}", implementation_summary)
        )
        return await self._agent.run_structured(
            prompt, FailureAnalysis, max_tokens=1000
        )