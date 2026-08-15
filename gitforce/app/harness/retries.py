from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass, field

from gitforce.app.harness.budgets import BudgetExceeded


class RetryableError(Exception):
    """Base class for errors worth retrying (section 46)."""


@dataclass
class RetryPolicy:
    """Exponential backoff retry policy (sections 15, 46).

    Retries are attempted for the given retryable exceptions. Budget
    exhaustion, permission denials, and guardrail violations are never
    retried (they will not succeed on a retry).
    """

    max_attempts: int = 3
    base_delay: float = 0.2
    max_delay: float = 4.0
    retryable: set[type[BaseException]] = field(
        default_factory=lambda: {TimeoutError, RetryableError}
    )

    def delay_for(self, attempt: int) -> float:
        delay = min(self.base_delay * (2 ** max(0, attempt - 1)), self.max_delay)
        return delay + random.uniform(0, delay * 0.25)  # noqa: S311

    def should_retry(self, exc: BaseException) -> bool:
        if isinstance(exc, (BudgetExceeded, PermissionError)):
            return False
        return any(isinstance(exc, cls) for cls in self.retryable)

    async def run(self, coro_factory, budget=None) -> object:
        """Run coro_factory until success or max_attempts, with backoff."""
        last_exc: BaseException | None = None
        for attempt in range(1, self.max_attempts + 1):
            if budget is not None:
                budget.tick_iteration()
            try:
                return await coro_factory()
            except asyncio.CancelledError:
                raise
            except BaseException as exc:  # noqa: BLE001
                last_exc = exc
                if attempt >= self.max_attempts or not self.should_retry(exc):
                    raise
                await asyncio.sleep(self.delay_for(attempt))
        assert last_exc is not None  # noqa: S101
        raise last_exc
