from __future__ import annotations

from gitforce.app.evaluation.models import AgentCost, CostSummary


def aggregate_usage(usage_records: list[dict]) -> CostSummary:
    """Aggregate raw ``task.state["usage"]`` records into a CostSummary.

    Each record is produced by the harness usage sink (Phase 10) and
    carries model/provider/token/cost fields.
    """
    summary = CostSummary()
    for record in usage_records:
        if not isinstance(record, dict):
            continue
        input_tokens = int(record.get("input_tokens") or 0)
        output_tokens = int(record.get("output_tokens") or 0)
        total = input_tokens + output_tokens
        if total == 0:
            total = int(record.get("total_tokens") or 0)
        cost = float(record.get("estimated_cost_usd") or 0.0)
        latency = float(record.get("latency_ms") or 0.0)
        if total == 0 and cost == 0.0:
            continue
        agent = str(record.get("agent") or "unknown")

        summary.total_tokens += total
        summary.total_cost_usd += cost
        summary.total_latency_ms += latency
        summary.calls += 1

        entry = summary.per_agent.setdefault(agent, AgentCost())
        entry.total_tokens += total
        entry.total_cost_usd += cost
        entry.calls += 1

    summary.total_cost_usd = round(summary.total_cost_usd, 6)
    summary.total_latency_ms = round(summary.total_latency_ms, 2)
    return summary
