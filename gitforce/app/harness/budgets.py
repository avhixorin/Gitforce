from __future__ import annotations

import time
from dataclasses import dataclass, field


class BudgetExceeded(Exception):
    """Raised when an execution budget (tokens/iterations/cost/time) is hit."""


@dataclass
class TokenBudget:
    """Tracks cumulative token usage against a hard cap (section 15)."""

    max_tokens: int | None = None
    _used: int = field(default=0, init=False)

    def add(self, tokens: int) -> None:
        self._used += max(0, tokens)
        if self.max_tokens is not None and self._used > self.max_tokens:
            raise BudgetExceeded(
                f"Token budget exceeded: {self._used} > {self.max_tokens}"
            )

    @property
    def used(self) -> int:
        return self._used

    @property
    def remaining(self) -> int | None:
        if self.max_tokens is None:
            return None
        return max(0, self.max_tokens - self._used)


@dataclass
class IterationBudget:
    """Caps the number of execution attempts/iterations (section 15)."""

    max_iterations: int | None = None
    _count: int = field(default=0, init=False)

    def tick(self) -> None:
        self._count += 1
        if self.max_iterations is not None and self._count > self.max_iterations:
            raise BudgetExceeded(
                f"Iteration budget exceeded: {self._count} > {self.max_iterations}"
            )

    @property
    def count(self) -> int:
        return self._count

    @property
    def remaining(self) -> int | None:
        if self.max_iterations is None:
            return None
        return max(0, self.max_iterations - self._count)


@dataclass
class ExecutionBudget:
    """Combined budget: tokens, iterations, elapsed wall-clock (section 15)."""

    token_budget: TokenBudget = field(default_factory=TokenBudget)
    iteration_budget: IterationBudget = field(default_factory=IterationBudget)
    timeout_seconds: int | None = None
    _started: float = field(default=0.0, init=False)

    def __post_init__(self) -> None:
        self._started = 0.0

    @classmethod
    def with_limits(
        cls,
        *,
        max_tokens: int | None = None,
        max_iterations: int | None = None,
        timeout_seconds: int | None = None,
    ) -> ExecutionBudget:
        return cls(
            token_budget=TokenBudget(max_tokens=max_tokens),
            iteration_budget=IterationBudget(max_iterations=max_iterations),
            timeout_seconds=timeout_seconds,
        )

    def start(self) -> None:
        self._started = time.monotonic()

    @property
    def elapsed_seconds(self) -> float:
        return time.monotonic() - self._started if self._started else 0.0

    def check_timeout(self) -> None:
        if self.timeout_seconds is not None and self.elapsed_seconds > self.timeout_seconds:
            raise BudgetExceeded(
                f"Execution timeout exceeded: {self.elapsed_seconds:.1f}s "
                f"> {self.timeout_seconds}s"
            )

    def add_tokens(self, tokens: int) -> None:
        self.token_budget.add(tokens)
        self.check_timeout()

    def tick_iteration(self) -> None:
        self.iteration_budget.tick()
        self.check_timeout()
