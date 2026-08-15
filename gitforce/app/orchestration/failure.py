from __future__ import annotations

import enum

import httpx

from gitforce.app.execution.commands import CommandDeniedError
from gitforce.app.llm.models import (
    LLMConfigurationError,
    LLMResponseError,
    LLMTimeoutError,
)


class FailureCategory(enum.StrEnum):
    TRANSIENT = "TRANSIENT"
    PERMANENT = "PERMANENT"
    AGENT_ERROR = "AGENT_ERROR"
    TOOL_ERROR = "TOOL_ERROR"
    USER_ACTION_REQUIRED = "USER_ACTION_REQUIRED"
    SECURITY_BLOCK = "SECURITY_BLOCK"


def categorize_exception(exc: BaseException) -> FailureCategory:
    """Map an exception to a failure category (Requirement section 46)."""
    if isinstance(exc, LLMTimeoutError):
        return FailureCategory.TRANSIENT
    if isinstance(exc, httpx.HTTPStatusError):
        if exc.response.status_code in {429, 500, 502, 503, 504}:
            return FailureCategory.TRANSIENT
        return FailureCategory.PERMANENT
    if isinstance(exc, httpx.HTTPError):
        return FailureCategory.TRANSIENT
    if isinstance(exc, (LLMConfigurationError, LLMResponseError)):
        return FailureCategory.PERMANENT
    if isinstance(exc, CommandDeniedError):
        return FailureCategory.SECURITY_BLOCK
    return FailureCategory.AGENT_ERROR


def is_retryable(category: FailureCategory) -> bool:
    return category is FailureCategory.TRANSIENT