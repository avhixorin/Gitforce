from __future__ import annotations

import enum
from typing import Any

from pydantic import BaseModel, Field


class ProviderName(enum.StrEnum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GOOGLE = "google"
    GROQ = "groq"
    LOCAL = "local"
    MOCK = "mock"


class TaskComplexity(enum.StrEnum):
    SIMPLE = "simple"
    MODERATE = "moderate"
    COMPLEX = "complex"


class LLMTaskType(enum.StrEnum):
    CLASSIFICATION = "classification"
    SUMMARIZATION = "summarization"
    CODE_GENERATION = "code_generation"
    ARCHITECTURE = "architecture"
    SECURITY = "security"
    REVIEW = "review"
    JUDGE = "judge"


class LLMMessage(BaseModel):
    role: str = Field(..., pattern="^(system|user|assistant)$")
    content: str


class LLMRequest(BaseModel):
    messages: list[LLMMessage]
    model: str | None = None
    temperature: float = 0.0
    max_tokens: int = 2048
    response_format: str | None = Field(
        default=None, pattern="^(text|json)$"
    )
    task_type: LLMTaskType = LLMTaskType.CLASSIFICATION


class LLMResponse(BaseModel):
    content: str
    model: str
    provider: ProviderName
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0
    estimated_cost_usd: float = 0.0
    raw: dict[str, Any] = Field(default_factory=dict)


class LLMError(Exception):
    """Base class for LLM failures."""


class LLMConfigurationError(LLMError):
    """Raised when a provider is misconfigured (e.g. missing API key)."""


class LLMTimeoutError(LLMError):
    """Raised when an LLM call exceeds its timeout."""


class LLMResponseError(LLMError):
    """Raised when the provider returns an error or malformed response."""


class Usage(BaseModel):
    """Per-call usage record for cost tracking (section 41)."""

    task_id: str | None = None
    agent: str | None = None
    model: str
    provider: ProviderName
    input_tokens: int
    output_tokens: int
    total_tokens: int
    estimated_cost_usd: float
    latency_ms: float