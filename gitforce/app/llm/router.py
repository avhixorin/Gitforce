from __future__ import annotations

from pydantic import BaseModel

from gitforce.app.config.settings import Settings, get_settings
from gitforce.app.llm.models import (
    LLMTaskType,
    ProviderName,
    TaskComplexity,
)
from gitforce.app.llm.providers import BaseLLMProvider, create_provider


class RouteProfile(BaseModel):
    provider: ProviderName
    model: str


class ModelRouter:
    """Selects a model based on task complexity and type (section 31).

    The mapping is configurable via settings: provider defaults to the
    configured LLM_PROVIDER, models default to MODEL_FAST / MODEL_CODING /
    MODEL_REASONING / MODEL_JUDGE.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        provider = ProviderName(self._settings.llm_provider)
        self._profiles: dict[LLMTaskType, RouteProfile] = {
            LLMTaskType.CLASSIFICATION: RouteProfile(
                provider=provider, model=self._settings.model_fast
            ),
            LLMTaskType.SUMMARIZATION: RouteProfile(
                provider=provider, model=self._settings.model_fast
            ),
            LLMTaskType.CODE_GENERATION: RouteProfile(
                provider=provider, model=self._settings.model_coding
            ),
            LLMTaskType.ARCHITECTURE: RouteProfile(
                provider=provider, model=self._settings.model_reasoning
            ),
            LLMTaskType.SECURITY: RouteProfile(
                provider=provider, model=self._settings.model_reasoning
            ),
            LLMTaskType.REVIEW: RouteProfile(
                provider=provider, model=self._settings.model_reasoning
            ),
            LLMTaskType.JUDGE: RouteProfile(
                provider=provider, model=self._settings.model_judge
            ),
        }

    def profile_for(
        self,
        task_type: LLMTaskType,
        complexity: TaskComplexity = TaskComplexity.MODERATE,
    ) -> RouteProfile:
        profile = self._profiles[task_type]
        if complexity is TaskComplexity.SIMPLE and task_type in {
            LLMTaskType.CLASSIFICATION,
            LLMTaskType.SUMMARIZATION,
        }:
            return profile
        return profile

    def provider_for(
        self,
        task_type: LLMTaskType,
        complexity: TaskComplexity = TaskComplexity.MODERATE,
    ) -> BaseLLMProvider:
        profile = self.profile_for(task_type, complexity)
        return create_provider(profile.provider, self._settings)


def mock_router(settings: Settings | None = None) -> ModelRouter:
    """Router forced to use the deterministic MockProvider (tests/dev)."""
    settings = settings or get_settings()
    router = ModelRouter(settings)
    for task_type in router._profiles:
        router._profiles[task_type] = RouteProfile(
            provider=ProviderName.MOCK, model=settings.model_fast
        )
    return router