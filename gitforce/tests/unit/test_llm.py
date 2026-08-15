import asyncio
import os

os.environ.setdefault("GITFORCE_DEBUG", "false")
os.environ.setdefault("GITFORCE_LLM_PROVIDER", "mock")

from gitforce.app.config.settings import get_settings
from gitforce.app.llm.models import (
    LLMMessage,
    LLMRequest,
    LLMTaskType,
    ProviderName,
    TaskComplexity,
)
from gitforce.app.llm.providers import MockProvider, create_provider
from gitforce.app.llm.router import ModelRouter
from gitforce.tests.helpers import smart_responder


def test_mock_provider_returns_json() -> None:
    provider = MockProvider(get_settings(), responder=smart_responder)
    request = LLMRequest(
        messages=[LLMMessage(role="system", content="Requirements Analysis Agent x")],
        response_format="json",
        task_type=LLMTaskType.SUMMARIZATION,
    )
    resp = asyncio.run(provider.complete(request))
    assert resp.provider is ProviderName.MOCK
    assert resp.content == smart_responder(request)


def test_router_uses_mock_provider() -> None:
    router = ModelRouter(get_settings())
    profile = router.profile_for(LLMTaskType.CODE_GENERATION)
    assert profile.provider is ProviderName.MOCK


def test_router_selects_model_by_task_type() -> None:
    settings = get_settings()
    router = ModelRouter(settings)
    # With mock provider, model defaults to fast model for every task type.
    for task_type in LLMTaskType:
        profile = router.profile_for(task_type, TaskComplexity.COMPLEX)
        assert profile.provider is ProviderName.MOCK
        assert profile.model


def test_create_provider_mock() -> None:
    provider = create_provider(ProviderName.MOCK, get_settings())
    assert isinstance(provider, MockProvider)