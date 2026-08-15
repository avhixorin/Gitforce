from __future__ import annotations

import json
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from gitforce.app.llm.models import (
    LLMMessage,
    LLMRequest,
    LLMResponse,
    LLMResponseError,
    LLMTaskType,
)
from gitforce.app.llm.providers import BaseLLMProvider

T = TypeVar("T", bound=BaseModel)


class AgentBase:
    """Shared behaviour for agents: run the LLM, request structured output,
    and parse/validate it into a Pydantic model."""

    task_type = LLMTaskType.CLASSIFICATION

    def __init__(self, provider: BaseLLMProvider) -> None:
        self._provider = provider

    async def run_structured(
        self,
        prompt: str,
        output_model: type[T],
        *,
        task_type: LLMTaskType | None = None,
        max_tokens: int = 2048,
    ) -> T:
        from gitforce.app.observability.tracing import start_span

        request = LLMRequest(
            messages=[LLMMessage(role="system", content=prompt)],
            response_format="json",
            task_type=task_type or self.task_type,
            max_tokens=max_tokens,
        )
        with start_span(
            "llm.complete",
            {
                "task_type": str(task_type or self.task_type),
                "output_model": output_model.__name__,
                "max_tokens": max_tokens,
            },
        ):
            response = await self._provider.complete(request)
        return _parse_json(response, output_model)


def _parse_json[T: BaseModel](response: LLMResponse, output_model: type[T]) -> T:
    content = response.content.strip()
    if content.startswith("```"):
        content = content.strip("`")
        if content.startswith("json"):
            content = content[4:]
        content = content.strip()
    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        raise LLMResponseError(
            f"Model returned malformed JSON for {output_model.__name__}"
        ) from exc
    try:
        return output_model.model_validate(data)
    except ValidationError as exc:
        raise LLMResponseError(
            f"Model output failed validation for {output_model.__name__}: {exc}"
        ) from exc