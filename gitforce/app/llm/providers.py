from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Any

from gitforce.app.config.settings import Settings
from gitforce.app.llm.models import (
    LLMConfigurationError,
    LLMRequest,
    LLMResponse,
    LLMTimeoutError,
    ProviderName,
)

# Rough USD per 1K tokens: (input, output) — used for cost estimation.
_COST_PER_1K: dict[str, tuple[float, float]] = {
    "gpt-4o": (0.005, 0.015),
    "gpt-4o-mini": (0.00015, 0.0006),
    "claude-3-5-sonnet": (0.003, 0.015),
    "claude-3-5-haiku": (0.0008, 0.004),
    "gemini-1.5-pro": (0.0035, 0.0105),
    "gemini-1.5-flash": (0.00035, 0.00105),
    "llama-3.1-8b": (0.00005, 0.00005),
    "llama-3.1-70b": (0.00059, 0.00079),
}
_DEFAULT_COST = (0.001, 0.002)


def _estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    in_cost, out_cost = _COST_PER_1K.get(model, _DEFAULT_COST)
    return (input_tokens / 1000 * in_cost) + (output_tokens / 1000 * out_cost)


class BaseLLMProvider(ABC):
    """Provider abstraction. Implementations live behind lazy imports so the
    app boots without every vendor SDK installed."""

    name: ProviderName

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @abstractmethod
    async def complete(self, request: LLMRequest) -> LLMResponse:
        """Run a chat completion."""

    def _finalize(
        self,
        content: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        start: float,
        raw: dict[str, Any] | None = None,
    ) -> LLMResponse:
        elapsed = (time.perf_counter() - start) * 1000
        return LLMResponse(
            content=content,
            model=model,
            provider=self.name,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=round(elapsed, 2),
            estimated_cost_usd=round(
                _estimate_cost(model, input_tokens, output_tokens), 6
            ),
            raw=raw or {},
        )


class OpenAIProvider(BaseLLMProvider):
    name = ProviderName.OPENAI

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        if not settings.openai_api_key:
            raise LLMConfigurationError("OPENAI_API_KEY is not set")
        try:
            from openai import AsyncOpenAI

            self._client = AsyncOpenAI(api_key=settings.openai_api_key)
        except ImportError as exc:  # pragma: no cover
            raise LLMConfigurationError(
                "openai package is not installed"
            ) from exc

    async def complete(self, request: LLMRequest) -> LLMResponse:
        model = request.model or self._settings.model_coding
        start = time.perf_counter()
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": [m.model_dump() for m in request.messages],
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
        }
        if request.response_format == "json":
            kwargs["response_format"] = {"type": "json_object"}
        try:
            resp = await self._client.chat.completions.create(**kwargs)
        except Exception as exc:  # noqa: BLE001
            raise LLMTimeoutError(str(exc)) from exc
        content = resp.choices[0].message.content or ""
        usage = resp.usage
        return self._finalize(
            content,
            model,
            usage.prompt_tokens if usage else 0,
            usage.completion_tokens if usage else 0,
            start,
            resp.model_dump(),
        )


class AnthropicProvider(BaseLLMProvider):
    name = ProviderName.ANTHROPIC

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        if not settings.anthropic_api_key:
            raise LLMConfigurationError("ANTHROPIC_API_KEY is not set")
        try:
            from anthropic import AsyncAnthropic

            self._client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        except ImportError as exc:  # pragma: no cover
            raise LLMConfigurationError(
                "anthropic package is not installed"
            ) from exc

    async def complete(self, request: LLMRequest) -> LLMResponse:
        model = request.model or self._settings.model_coding
        system = " ".join(
            m.content for m in request.messages if m.role == "system"
        )
        messages = [
            {"role": m.role, "content": m.content}
            for m in request.messages
            if m.role in {"user", "assistant"}
        ]
        start = time.perf_counter()
        try:
            resp = await self._client.messages.create(
                model=model,
                max_tokens=request.max_tokens,
                temperature=request.temperature,
                system=system or None,
                messages=messages,
            )
        except Exception as exc:  # noqa: BLE001
            raise LLMTimeoutError(str(exc)) from exc
        content = "".join(
            block.text for block in resp.content if block.type == "text"
        )
        return self._finalize(
            content,
            model,
            resp.usage.input_tokens,
            resp.usage.output_tokens,
            start,
            resp.model_dump(),
        )


class GoogleProvider(BaseLLMProvider):
    name = ProviderName.GOOGLE

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        if not settings.google_api_key:
            raise LLMConfigurationError("GOOGLE_API_KEY is not set")
        try:
            import google.generativeai as genai  # type: ignore

            genai.configure(api_key=settings.google_api_key)
            self._genai = genai
        except ImportError as exc:  # pragma: no cover
            raise LLMConfigurationError(
                "google-generativeai package is not installed"
            ) from exc

    async def complete(self, request: LLMRequest) -> LLMResponse:
        model = request.model or self._settings.model_coding
        prompt = "\n\n".join(m.content for m in request.messages)
        start = time.perf_counter()
        try:
            import asyncio

            def _run() -> Any:
                return self._genai.GenerativeModel(model).generate_content(prompt)

            resp = await asyncio.to_thread(_run)
        except Exception as exc:  # noqa: BLE001
            raise LLMTimeoutError(str(exc)) from exc
        content = resp.text or ""
        usage = getattr(resp, "usage_metadata", None)
        in_tok = getattr(usage, "prompt_token_count", 0)
        out_tok = getattr(usage, "candidates_token_count", 0)
        return self._finalize(content, model, in_tok, out_tok, start)


class GroqProvider(OpenAIProvider):
    """Groq exposes an OpenAI-compatible API."""

    name = ProviderName.GROQ

    def __init__(self, settings: Settings) -> None:
        BaseLLMProvider.__init__(self, settings)
        if not settings.groq_api_key:
            raise LLMConfigurationError("GROQ_API_KEY is not set")
        try:
            from openai import AsyncOpenAI

            self._client = AsyncOpenAI(
                api_key=settings.groq_api_key,
                base_url="https://api.groq.com/openai/v1",
            )
        except ImportError as exc:  # pragma: no cover
            raise LLMConfigurationError(
                "openai package is not installed"
            ) from exc


class LocalProvider(OpenAIProvider):
    """Any OpenAI-compatible local server (e.g. vLLM, Ollama)."""

    name = ProviderName.LOCAL

    def __init__(self, settings: Settings) -> None:
        BaseLLMProvider.__init__(self, settings)
        try:
            from openai import AsyncOpenAI

            base_url = self._settings.local_llm_base_url or (
                "http://localhost:8001/v1"
            )
            self._client = AsyncOpenAI(
                api_key=self._settings.local_llm_api_key or "not-needed",
                base_url=base_url,
            )
        except ImportError as exc:  # pragma: no cover
            raise LLMConfigurationError(
                "openai package is not installed"
            ) from exc


class MockProvider(BaseLLMProvider):
    """Deterministic provider for tests and development without API keys."""

    name = ProviderName.MOCK

    def __init__(self, settings: Settings, responder=None) -> None:
        super().__init__(settings)
        self._responder = responder or (
            lambda request: '{"ready": true}'
            if request.response_format == "json"
            else "mock response"
        )

    async def complete(self, request: LLMRequest) -> LLMResponse:
        model = request.model or self._settings.model_fast
        start = time.perf_counter()
        content = self._responder(request)
        if callable(content):
            content = content(request)
        return self._finalize(
            content,
            model,
            sum(len(m.content) for m in request.messages),
            len(content),
            start,
        )


_PROVIDER_CLASSES: dict[ProviderName, type[BaseLLMProvider]] = {
    ProviderName.OPENAI: OpenAIProvider,
    ProviderName.ANTHROPIC: AnthropicProvider,
    ProviderName.GOOGLE: GoogleProvider,
    ProviderName.GROQ: GroqProvider,
    ProviderName.LOCAL: LocalProvider,
    ProviderName.MOCK: MockProvider,
}


def create_provider(
    name: ProviderName | str, settings: Settings, **kwargs: Any
) -> BaseLLMProvider:
    provider_name = ProviderName(name)
    cls = _PROVIDER_CLASSES[provider_name]
    return cls(settings, **kwargs)