from __future__ import annotations

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
)


class Metrics:
    """Prometheus registry + convenience counters/histograms (Phase 11)."""

    def __init__(self, registry: CollectorRegistry | None = None) -> None:
        self.registry = registry or CollectorRegistry()

        self.tasks_total = Counter(
            "gitforce_tasks_total",
            "Tasks created",
            labelnames=["status"],
            registry=self.registry,
        )
        self.workflow_completed = Counter(
            "gitforce_workflow_completed_total",
            "Workflows completed",
            labelnames=["outcome"],
            registry=self.registry,
        )
        self.agent_calls = Counter(
            "gitforce_agent_calls_total",
            "Agent LLM calls",
            labelnames=["agent", "status"],
            registry=self.registry,
        )
        self.tokens_total = Counter(
            "gitforce_tokens_total",
            "LLM tokens consumed",
            labelnames=["agent"],
            registry=self.registry,
        )
        self.cost_total = Counter(
            "gitforce_cost_total_usd",
            "Estimated LLM cost in USD",
            labelnames=["agent"],
            registry=self.registry,
        )
        self.agent_duration = Histogram(
            "gitforce_agent_duration_seconds",
            "Agent execution duration",
            labelnames=["agent"],
            buckets=(0.1, 0.5, 1, 2, 5, 10, 30, 60, 120, 300, 600),
            registry=self.registry,
        )
        self.request_duration = Histogram(
            "gitforce_http_request_duration_seconds",
            "HTTP request duration",
            labelnames=["method", "path"],
            buckets=(0.01, 0.05, 0.1, 0.5, 1, 2, 5, 10),
            registry=self.registry,
        )
        self.trace_exported = Counter(
            "gitforce_trace_spans_total",
            "Spans recorded by the dashboard recorder",
            registry=self.registry,
        )

        self._tokens_by_agent: dict[str, int] = {}
        self._cost_by_agent: dict[str, float] = {}

    def task_created(self, status: str = "queued") -> None:
        self.tasks_total.labels(status=status).inc()

    def workflow_done(self, outcome: str) -> None:
        self.workflow_completed.labels(outcome=outcome).inc()

    def agent_completed(
        self, agent: str, *, elapsed_ms: float, tokens: int = 0, cost: float = 0.0
    ) -> None:
        self.agent_calls.labels(agent=agent, status="completed").inc()
        self.agent_duration.labels(agent=agent).observe(elapsed_ms / 1000.0)
        if tokens:
            self.tokens_total.labels(agent=agent).inc(tokens)
            self._tokens_by_agent[agent] = self._tokens_by_agent.get(agent, 0) + tokens
        if cost:
            self.cost_total.labels(agent=agent).inc(cost)
            self._cost_by_agent[agent] = self._cost_by_agent.get(agent, 0.0) + cost

    def agent_failed(self, agent: str, *, elapsed_ms: float) -> None:
        self.agent_calls.labels(agent=agent, status="failed").inc()
        self.agent_duration.labels(agent=agent).observe(elapsed_ms / 1000.0)

    def record_usage(self, agent: str, usage: dict) -> None:
        tokens = int(usage.get("total_tokens") or 0)
        cost = float(usage.get("estimated_cost_usd") or 0.0)
        if tokens:
            self.tokens_total.labels(agent=agent).inc(tokens)
        if cost:
            self.cost_total.labels(agent=agent).inc(cost)

    def observe_request(self, method: str, path: str, seconds: float) -> None:
        self.request_duration.labels(method=method, path=path).observe(seconds)

    def tokens_by_agent(self) -> dict[str, int]:
        return dict(self._tokens_by_agent)

    def cost_by_agent(self) -> dict[str, float]:
        return dict(self._cost_by_agent)

    def render(self) -> bytes:
        return generate_latest(self.registry)


metrics = Metrics()


def init_metrics() -> Metrics:
    return metrics
