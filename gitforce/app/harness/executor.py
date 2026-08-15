from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from gitforce.app.harness.budgets import ExecutionBudget
from gitforce.app.harness.guardrails import SecretRedactor
from gitforce.app.harness.permissions import (
    AgentPermissions,
    Permission,
)
from gitforce.app.harness.retries import RetryPolicy
from gitforce.app.llm.models import Usage
from gitforce.app.llm.providers import BaseLLMProvider

logger = logging.getLogger(__name__)


def _run_span(name: str, attributes: dict):
    from gitforce.app.observability.tracing import start_span

    return start_span(name, attributes)


def _record_agent_metrics(
    agent: str, elapsed_ms: float, tokens: int, usage: list
) -> None:
    from gitforce.app.observability.metrics import metrics

    cost = sum(float(u.estimated_cost_usd or 0.0) for u in usage)
    metrics.agent_completed(
        agent, elapsed_ms=elapsed_ms, tokens=tokens or 0, cost=cost
    )


@dataclass
class TraceEvent:
    """One step in a harnessed agent run (section 40)."""

    kind: str
    message: str
    elapsed_ms: float = 0.0

    def to_dict(self) -> dict:
        return {"kind": self.kind, "message": self.message, "elapsed_ms": self.elapsed_ms}


@dataclass
class HarnessResult:
    """Structured result of a harnessed agent execution (section 15)."""

    agent: str
    ok: bool
    value: Any = None
    error: str = ""
    attempts: int = 0
    tokens_used: int = 0
    elapsed_ms: float = 0.0
    trace: list[TraceEvent] = field(default_factory=list)
    usage: list[Usage] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "agent": self.agent,
            "ok": self.ok,
            "error": self.error,
            "attempts": self.attempts,
            "tokens_used": self.tokens_used,
            "elapsed_ms": round(self.elapsed_ms, 2),
            "trace": [t.to_dict() for t in self.trace],
            "usage": [u.model_dump() for u in self.usage],
        }


class HarnessProvider(BaseLLMProvider):
    """Provider wrapper that enforces budgets + secret redaction on every
    LLM call and reports usage back to the harness."""

    def __init__(
        self,
        inner: BaseLLMProvider,
        budget: ExecutionBudget,
        redactor: SecretRedactor,
        usage_sink: Callable[[Usage], Awaitable[None] | None] | None = None,
    ) -> None:
        super().__init__(inner._settings)  # noqa: SLF001
        self._inner = inner
        self._budget = budget
        self._redactor = redactor
        self._usage_sink = usage_sink

    @property
    def name(self):
        return self._inner.name

    async def complete(self, request):
        budget = self._budget
        # Never allow secrets to reach the model (section 44).
        messages = request.model_dump()
        for message in messages["messages"]:
            message["content"] = self._redactor.redact(message["content"])
        safe_request = type(request).model_validate(messages)
        budget.tick_iteration()
        response = await self._inner.complete(safe_request)
        budget.add_tokens(response.input_tokens + response.output_tokens)
        if self._usage_sink is not None:
            result = self._usage_sink(
                Usage(
                    model=response.model,
                    provider=response.provider,
                    input_tokens=response.input_tokens,
                    output_tokens=response.output_tokens,
                    total_tokens=response.input_tokens + response.output_tokens,
                    estimated_cost_usd=response.estimated_cost_usd,
                    latency_ms=response.latency_ms,
                )
            )
            if result is not None:
                try:
                    await result
                except Exception as exc:  # noqa: BLE001
                    logger.warning("usage sink failed: %s", exc)
        return response


class AgentHarness:
    """Wraps every agent execution with the section 15 responsibilities:

    - tool permission enforcement (via AgentPermissions)
    - token / iteration / timeout budgets (ExecutionBudget)
    - retry policy (RetryPolicy, exponential backoff)
    - secret guardrails (SecretRedactor)
    - structured outputs (HarnessResult)
    - tracing + audit events
    """

    def __init__(
        self,
        agent: str,
        permissions: AgentPermissions | None = None,
        budget: ExecutionBudget | None = None,
        retry_policy: RetryPolicy | None = None,
        redactor: SecretRedactor | None = None,
        audit=None,
        usage_sink: Callable[[Usage], Awaitable[None] | None] | None = None,
        task_id: str | None = None,
    ) -> None:
        self.agent = agent
        self.task_id = task_id or ""
        self.permissions = permissions or AgentPermissions(agent=agent)
        self.budget = budget or ExecutionBudget()
        self.retry_policy = retry_policy or RetryPolicy()
        self.redactor = redactor or SecretRedactor()
        self._audit = audit
        self._last_audit_error: str = ""
        self._usage_sink = usage_sink
        self._usage: list[Usage] = []

    def wrap_provider(self, provider: BaseLLMProvider) -> BaseLLMProvider:
        return HarnessProvider(
            provider, self.budget, self.redactor, usage_sink=self._on_usage
        )

    def _on_usage(self, usage: Usage) -> None:
        self._usage.append(usage)
        if self._usage_sink is not None:
            try:
                result = self._usage_sink(usage)
                if result is not None:
                    # Fire-and-forget: DB writes must not block the LLM call.
                    asyncio.ensure_future(result)
            except Exception as exc:  # noqa: BLE001
                # Usage tracking must never break an agent run.
                logger.warning("usage sink failed: %s", exc)

    async def _audit_event(self, kind: str, message: str) -> None:
        if self._audit is None:
            return
        try:
            await self._audit(self.agent, kind, message)
        except Exception as exc:  # noqa: BLE001
            # Auditing must never break an agent run.
            self._last_audit_error = str(exc)

    async def run(
        self,
        fn: Callable[..., Awaitable[Any]],
        *args: Any,
        require: Permission | None = None,
        **kwargs: Any,
    ) -> HarnessResult:
        """Execute an agent callable under the harness. Returns a
        HarnessResult; the wrapped value is in ``result.value``.

        Mirrors the section 15 example:
        ``harness.execute(agent=..., task=..., permissions=[...],
        max_iterations=..., timeout_seconds=...)``.
        """
        if require is not None:
            try:
                self.permissions.require(require)
            except PermissionError as exc:
                await self._audit_event("permission_denied", str(exc))
                return HarnessResult(
                    agent=self.agent, ok=False, error=str(exc)
                )

        start = time.monotonic()
        self.budget.start()
        self._usage = []
        attempts = 0
        tokens_used = 0
        trace: list[TraceEvent] = []

        async def attempt() -> Any:
            nonlocal tokens_used
            self.budget.tick_iteration()
            result = await fn(*args, **kwargs)
            if isinstance(result, tuple):
                return result
            # Harvest token usage from pydantic LLM responses if returned.
            tokens_used = self._harvest_tokens(result)
            return result

        with _run_span(
            f"agent.{self.agent}.run",
            {"agent": self.agent, "task_id": self.task_id},
        ) as span:
            try:
                async def coro_factory() -> Any:
                    return await attempt()

                value = await asyncio.wait_for(
                    self.retry_policy.run(coro_factory, budget=self.budget),
                    timeout=self.budget.timeout_seconds,
                )
                attempts = self.budget.iteration_budget.count
                trace.append(TraceEvent("success", f"{self.agent} completed"))
                await self._audit_event(
                    "agent.completed",
                    f"{self.agent} ok after {attempts} attempt(s)",
                )
                elapsed_ms = (time.monotonic() - start) * 1000
                _record_agent_metrics(
                    self.agent, elapsed_ms, tokens_used, self._usage
                )
                span.set_attribute("outcome", "completed")
                span.set_attribute("attempts", attempts)
                span.set_attribute("tokens_used", tokens_used)
                return HarnessResult(
                    agent=self.agent,
                    ok=True,
                    value=value,
                    attempts=attempts,
                    tokens_used=tokens_used,
                    elapsed_ms=elapsed_ms,
                    trace=trace,
                    usage=list(self._usage),
                )
            except Exception as exc:  # noqa: BLE001
                attempts = self.budget.iteration_budget.count
                trace.append(TraceEvent("error", str(exc)))
                await self._audit_event("agent.failed", f"{self.agent}: {exc}")
                elapsed_ms = (time.monotonic() - start) * 1000
                _record_agent_metrics(self.agent, elapsed_ms, 0, [])
                span.record_exception(exc)
                span.set_attribute("outcome", "failed")
                return HarnessResult(
                    agent=self.agent,
                    ok=False,
                    error=str(exc),
                    attempts=attempts,
                    tokens_used=tokens_used,
                    elapsed_ms=elapsed_ms,
                    trace=trace,
                    usage=list(self._usage),
                )

    @staticmethod
    def _harvest_tokens(result: Any) -> int:
        if isinstance(result, BaseModel) and hasattr(result, "total_tokens"):
            return int(result.total_tokens)  # type: ignore[attr-defined]
        if isinstance(result, dict):
            return int(result.get("total_tokens", 0) or 0)
        return 0
