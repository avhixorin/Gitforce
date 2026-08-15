from __future__ import annotations

import pytest

from gitforce.app.harness.budgets import (
    BudgetExceeded,
    ExecutionBudget,
    TokenBudget,
)
from gitforce.app.harness.executor import AgentHarness, HarnessProvider
from gitforce.app.harness.guardrails import (
    CommandAllowlist,
    GuardrailViolation,
    PathGuardrail,
    SecretRedactor,
)
from gitforce.app.harness.permissions import (
    DANGEROUS,
    AgentPermissions,
    Permission,
    PermissionDenied,
    mcp_permissions_from,
    permissions_for,
)
from gitforce.app.harness.retries import RetryableError, RetryPolicy


async def test_token_budget_raises():
    budget = TokenBudget(max_tokens=10)
    budget.add(4)
    budget.add(4)
    assert budget.used == 8
    assert budget.remaining == 2
    with pytest.raises(BudgetExceeded):
        budget.add(10)


async def test_iteration_budget_raises():
    budget = ExecutionBudget()
    budget.iteration_budget.max_iterations = 2
    budget.start()
    budget.tick_iteration()
    budget.tick_iteration()
    with pytest.raises(BudgetExceeded):
        budget.tick_iteration()


async def test_execution_timeout_budget():
    budget = ExecutionBudget(timeout_seconds=0)
    budget.start()
    with pytest.raises(BudgetExceeded):
        budget.check_timeout()


async def test_dangerous_permissions_stripped():
    perms = AgentPermissions(
        agent="x", granted={Permission.REPO_MERGE, Permission.REPO_READ}
    )
    assert not perms.grants(Permission.REPO_MERGE)
    assert perms.grants(Permission.REPO_READ)
    assert Permission.REPO_MERGE in DANGEROUS


async def test_permission_require_raises():
    perms = permissions_for("coder")
    perms.require(Permission.WORKSPACE_WRITE)
    with pytest.raises(PermissionDenied):
        perms.require(Permission.TESTS_EXECUTE)


async def test_harness_run_success():
    harness = AgentHarness(agent="coder", permissions=permissions_for("coder"))

    async def add(a: int, b: int) -> int:
        return a + b

    result = await harness.run(add, 1, 2, require=Permission.WORKSPACE_WRITE)
    assert result.ok
    assert result.value == 3
    assert result.attempts >= 1


async def test_harness_wrapped_provider_records_usage():
    from gitforce.app.config.settings import get_settings
    from gitforce.app.llm.models import LLMMessage, LLMRequest
    from gitforce.app.llm.providers import MockProvider

    settings = get_settings()
    inner = MockProvider(settings)
    budget = ExecutionBudget.with_limits(max_tokens=1000, timeout_seconds=30)
    harness = AgentHarness(
        agent="coder",
        permissions=permissions_for("coder"),
        budget=budget,
        redactor=SecretRedactor(),
    )
    wrapped = harness.wrap_provider(inner)

    async def call_llm(prompt: str) -> str:
        response = await wrapped.complete(
            LLMRequest(
                messages=[
                    LLMMessage(role="user", content=f"reply to: {prompt}")
                ]
            )
        )
        return response.content

    result = await harness.run(call_llm, "hello")
    assert result.ok
    assert result.usage, "wrapped provider calls must record Usage"
    usage = result.usage[0]
    assert usage.total_tokens > 0
    assert usage.input_tokens > 0
    assert usage.estimated_cost_usd is not None
    assert budget.token_budget.used > 0


async def test_harness_usage_sink_receives_per_call_usage():
    from gitforce.app.config.settings import get_settings
    from gitforce.app.llm.models import LLMMessage, LLMRequest
    from gitforce.app.llm.providers import MockProvider

    settings = get_settings()
    inner = MockProvider(settings)
    sink_calls: list = []

    def sink(usage) -> None:
        sink_calls.append(usage)

    harness = AgentHarness(agent="coder", usage_sink=sink)
    wrapped = harness.wrap_provider(inner)

    await wrapped.complete(
        LLMRequest(
            messages=[LLMMessage(role="user", content="do the thing")]
        )
    )
    assert len(sink_calls) == 1
    assert sink_calls[0].total_tokens > 0


async def test_harness_permission_denied():
    harness = AgentHarness(agent="tester", permissions=permissions_for("tester"))

    async def touch() -> str:
        return "written"

    result = await harness.run(
        touch, require=Permission.WORKSPACE_WRITE
    )
    assert not result.ok
    assert "not granted" in result.error


async def test_harness_retries_then_succeeds():
    harness = AgentHarness(agent="planner", permissions=permissions_for("planner"))
    attempts = {"n": 0}

    async def flaky() -> str:
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise RetryableError("boom")
        return "ok"

    result = await harness.run(flaky)
    assert result.ok
    assert result.value == "ok"
    assert attempts["n"] == 3


async def test_harness_gives_up_after_retries():
    harness = AgentHarness(
        agent="planner",
        permissions=permissions_for("planner"),
        retry_policy=RetryPolicy(max_attempts=2, base_delay=0.001),
    )

    async def always_fails() -> str:
        raise RetryableError("boom")

    result = await harness.run(always_fails)
    assert not result.ok
    assert "boom" in result.error


async def test_secret_redactor():
    redactor = SecretRedactor()
    text = "token=sk-abcdef1234567890 and api_key=supersecretvalue"
    redacted = redactor.redact(text)
    assert "sk-abcdef" not in redacted
    assert "supersecretvalue" not in redacted
    assert "[REDACTED]" in redacted


async def test_path_guardrail_blocks_escape(tmp_path):
    guard = PathGuardrail(tmp_path)
    (tmp_path / "ok.txt").write_text("x")
    assert guard.allow("ok.txt").exists()
    with pytest.raises(GuardrailViolation):
        guard.allow("../etc/passwd")


async def test_command_allowlist():
    allowlist = CommandAllowlist()
    assert allowlist.allow(["pytest", "-q"]) == ["pytest", "-q"]
    with pytest.raises(GuardrailViolation):
        allowlist.allow(["rm", "-rf", "/"])
    with pytest.raises(GuardrailViolation):
        allowlist.allow(["sudo", "reboot"])


async def test_harness_provider_redacts_and_budgets():
    from gitforce.app.config.settings import get_settings
    from gitforce.app.llm.models import LLMMessage, LLMRequest
    from gitforce.app.llm.providers import MockProvider

    settings = get_settings()
    inner = MockProvider(settings)
    budget = ExecutionBudget(token_budget=TokenBudget(max_tokens=1000))
    wrapped = HarnessProvider(inner, budget, SecretRedactor())
    request = LLMRequest(
        messages=[LLMMessage(role="user", content="password=hunter2hunter2")]
    )
    response = await wrapped.complete(request)
    assert response.content
    assert budget.token_budget.used > 0


async def test_mcp_permissions_derived_from_harness():
    coder = mcp_permissions_from(permissions_for("coder"))
    assert coder.agent == "coder"
    delivery = mcp_permissions_from(permissions_for("delivery"))
    assert delivery is not None


async def test_audit_handler_writes_db():
    from gitforce.app.database import models as db_models
    from gitforce.app.database.session import SessionLocal, engine
    from gitforce.app.harness.audit import AuditService

    async with engine.begin() as conn:
        await conn.run_sync(db_models.Base.metadata.create_all)

    service = AuditService()
    await service.log(agent="coder", action="agent.completed", task_id="t1")
    async with SessionLocal() as session:
        from gitforce.app.database.repositories import TaskRepository

        entries = await TaskRepository(session).list_audit(task_id="t1")
        assert any(e.agent == "coder" and e.action == "agent.completed" for e in entries)


async def test_usage_service_appends_to_task_state():
    from gitforce.app.database import models as db_models
    from gitforce.app.database.models import Task
    from gitforce.app.database.session import SessionLocal, engine
    from gitforce.app.harness.usage import UsageService

    async with engine.begin() as conn:
        await conn.run_sync(db_models.Base.metadata.create_all)

    async with SessionLocal() as session:
        task = Task(
            id="u1",
            issue_url="https://example.com/repo/issues/1",
            repository_url="https://example.com/repo.git",
            state={"usage": []},
        )
        session.add(task)
        await session.commit()

    service = UsageService()
    await service.record(
        "u1",
        {
            "model": "mock",
            "provider": "mock",
            "input_tokens": 10,
            "output_tokens": 5,
            "total_tokens": 15,
            "estimated_cost_usd": 0.01,
            "latency_ms": 12.0,
        },
    )

    async with SessionLocal() as session:
        task = await session.get(Task, "u1")
        assert task is not None
        usage = task.state["usage"]
        assert len(usage) == 1
        assert usage[0]["total_tokens"] == 15


async def test_usage_service_ignores_missing_task():
    from gitforce.app.database import models as db_models
    from gitforce.app.database.session import engine
    from gitforce.app.harness.usage import UsageService

    async with engine.begin() as conn:
        await conn.run_sync(db_models.Base.metadata.create_all)

    service = UsageService()
    await service.record("no-such-task", {"total_tokens": 1})


async def test_persist_workflow_state_preserves_usage():
    """Phase 10/12: mirroring the graph snapshot must not clobber usage
    records persisted by UsageService through its own session."""
    from gitforce.app.database import models as db_models
    from gitforce.app.database.models import Task
    from gitforce.app.database.session import SessionLocal, engine
    from gitforce.app.harness.usage import UsageService
    from gitforce.app.services.tasks import TaskService

    async with engine.begin() as conn:
        await conn.run_sync(db_models.Base.metadata.create_all)

    async with SessionLocal() as session:
        task = Task(
            id="u2",
            issue_url="https://example.com/repo/issues/1",
            repository_url="https://example.com/repo.git",
            state={"usage": []},
        )
        session.add(task)
        await session.commit()

    await UsageService().record("u2", {"total_tokens": 15, "model": "mock"})

    async with SessionLocal() as session:
        service = TaskService(session)
        await service.persist_workflow_state(
            "u2",
            {
                "status": "completed",
                "plan": {"summary": "p"},
                "test_results": {"passed": True},
            },
        )
        task = await service.get_task("u2")
        assert task.state["plan"] == {"summary": "p"}
        assert task.state["test_results"]["passed"] is True
        # Usage persisted by the separate UsageService session survives.
        assert len(task.state["usage"]) == 1
        assert task.state["usage"][0]["total_tokens"] == 15