from __future__ import annotations

import asyncio
import hashlib
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

from gitforce.app.orchestration.failure import (
    FailureCategory,
    categorize_exception,
    is_retryable,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass
class RetryResult:
    ok: bool
    value: Any = None
    attempts: int = 0
    error: str = ""
    category: str = ""

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "attempts": self.attempts,
            "error": self.error,
            "category": self.category,
        }


class TransientRetryPolicy:
    """Exponential-backoff retry for transient failures (section 46).

    Retries only exceptions categorized TRANSIENT (timeouts, 5xx, 429,
    network errors). Permanent and security failures fail fast.
    """

    def __init__(
        self,
        max_attempts: int = 3,
        base_delay: float = 0.5,
        max_delay: float = 8.0,
    ) -> None:
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.max_delay = max_delay

    async def run(
        self, fn: Callable[..., Awaitable[T]], *args: Any, **kwargs: Any
    ) -> RetryResult:
        last_error = ""
        last_category = FailureCategory.PERMANENT
        for attempt in range(1, self.max_attempts + 1):
            try:
                value = await fn(*args, **kwargs)
                return RetryResult(ok=True, value=value, attempts=attempt)
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
                category = categorize_exception(exc)
                last_category = category
                if not is_retryable(category) or attempt == self.max_attempts:
                    return RetryResult(
                        ok=False,
                        attempts=attempt,
                        error=last_error,
                        category=category.value,
                    )
                delay = min(self.base_delay * (2 ** (attempt - 1)), self.max_delay)
                logger.warning(
                    "transient failure on attempt %s/%s (%s); retrying in %.1fs: %s",
                    attempt,
                    self.max_attempts,
                    category.value,
                    delay,
                    last_error,
                )
                await asyncio.sleep(delay)
        return RetryResult(
            ok=False,
            attempts=self.max_attempts,
            error=last_error,
            category=last_category.value,
        )


@dataclass
class IdempotencyKeyStore:
    """In-process idempotency tracking (Phase 12).

    Keys on a deterministic hash of (operation, task_id, input) so
    duplicate submissions are detected and do not re-run.
    """

    _seen: set[str] = field(default_factory=set)

    @staticmethod
    def key(operation: str, task_id: str, *inputs: Any) -> str:
        digest = hashlib.sha256()
        digest.update(operation.encode("utf-8"))
        digest.update(task_id.encode("utf-8"))
        for item in inputs:
            digest.update(repr(item).encode("utf-8"))
        return digest.hexdigest()

    def is_new(self, key: str) -> bool:
        return key not in self._seen

    def mark(self, key: str) -> None:
        self._seen.add(key)

    def check_and_mark(self, key: str) -> bool:
        if key in self._seen:
            return False
        self._seen.add(key)
        return True


idempotency_store = IdempotencyKeyStore()


def retry_transient(
    max_attempts: int = 3,
    base_delay: float = 0.5,
    max_delay: float = 8.0,
) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[T]]]:
    """Decorator that retries transient failures on an async function."""

    def decorator(fn: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        policy = TransientRetryPolicy(max_attempts, base_delay, max_delay)

        async def wrapper(*args: Any, **kwargs: Any) -> T:
            result = await policy.run(fn, *args, **kwargs)
            if not result.ok:
                raise RuntimeError(
                    f"{fn.__name__} failed after {result.attempts} "
                    f"attempts: {result.error}"
                )
            return result.value

        return wrapper

    return decorator
