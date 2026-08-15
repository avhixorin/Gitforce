from __future__ import annotations

from gitforce.app.agents.base import AgentBase
from gitforce.app.agents.models import JudgeDecision, ReviewDecision
from gitforce.app.llm.providers import BaseLLMProvider
from gitforce.prompts.loader import load_prompt


class ReviewAgent:
    """Independent code review of the generated changes (section 22)."""

    def __init__(self, provider: BaseLLMProvider) -> None:
        self._agent = AgentBase(provider)

    async def review(
        self,
        requirements: dict,
        plan: dict,
        implementation_summary: str,
        diff: str,
        test_results: dict,
        security_results: dict,
    ) -> ReviewDecision:
        prompt = (
            load_prompt("reviewer", "review")
            .replace("{{requirements_json}}", str(requirements))
            .replace("{{plan_json}}", str(plan))
            .replace("{{implementation_summary}}", implementation_summary)
            .replace("{{diff}}", diff or "(no diff)")
            .replace("{{test_results_json}}", str(test_results))
            .replace("{{security_results_json}}", str(security_results))
        )
        return await self._agent.run_structured(
            prompt, ReviewDecision, max_tokens=1500
        )


class JudgeAgent:
    """LLM-as-Judge with an isolated, critical perspective (sections 23, 43)."""

    def __init__(self, provider: BaseLLMProvider) -> None:
        self._agent = AgentBase(provider)

    async def judge(
        self,
        issue: dict,
        requirements: dict,
        plan: dict,
        diff: str,
        test_results: dict,
        security_results: dict,
        review_results: dict,
    ) -> JudgeDecision:
        prompt = (
            load_prompt("judge", "judge")
            .replace("{{issue_json}}", str(issue))
            .replace("{{requirements_json}}", str(requirements))
            .replace("{{plan_json}}", str(plan))
            .replace("{{diff}}", diff or "(no diff)")
            .replace("{{test_results_json}}", str(test_results))
            .replace("{{security_results_json}}", str(security_results))
            .replace("{{review_results_json}}", str(review_results))
        )
        return await self._agent.run_structured(
            prompt, JudgeDecision, max_tokens=1500
        )