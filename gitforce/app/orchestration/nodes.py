from __future__ import annotations

import functools
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

from langgraph.types import interrupt

from gitforce.app.agents.coder import CoderAgent, PlannerAgent
from gitforce.app.agents.failure import FailureAnalyzer
from gitforce.app.agents.feedback import FeedbackAnalyzer
from gitforce.app.agents.repository import (
    RepositoryAnalysisAgent,
    RepositoryCloner,
)
from gitforce.app.agents.requirements import RequirementsAgent
from gitforce.app.agents.reviewer import JudgeAgent, ReviewAgent
from gitforce.app.agents.security import SecurityAgent
from gitforce.app.agents.tester import TesterAgent
from gitforce.app.config.settings import get_settings
from gitforce.app.execution.factory import create_sandbox
from gitforce.app.github.client import GitHubClient, GitHubRepositoryRef
from gitforce.app.github.git import GitError, GitWorktree
from gitforce.app.harness.executor import AgentHarness
from gitforce.app.harness.permissions import AgentPermissions, Permission
from gitforce.app.llm.providers import BaseLLMProvider
from gitforce.app.mcp.client import MCPClient
from gitforce.app.mcp.permissions import PermissionLevel
from gitforce.app.orchestration.state import ForgeState
from gitforce.app.services.tasks import TaskService

logger = logging.getLogger(__name__)

WORKSPACES_ROOT = Path("workspaces")

F = TypeVar("F", bound=Callable[..., Awaitable[Any]])


def traced_node(name: str) -> Callable[[F], F]:
    """Decorator that wraps a graph node in an OpenTelemetry span so the
    dashboard can visualize the agent execution timeline (Phase 11)."""

    def decorator(fn: F) -> F:
        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            from gitforce.app.observability.tracing import start_span

            task_id = ""
            if args and isinstance(args[0], dict):
                task_id = str(args[0].get("task_id") or "")
            with start_span(
                f"node.{name}",
                {"task_id": task_id, "node": name},
            ) as span:
                try:
                    result = await fn(*args, **kwargs)
                    span.set_attribute("outcome", "completed")
                    return result
                except Exception as exc:  # noqa: BLE001
                    span.record_exception(exc)
                    span.set_attribute("outcome", "failed")
                    raise

        return wrapper  # type: ignore[return-value]

    return decorator


@dataclass
class AgentContext:
    """Shared dependencies injected into every graph node."""

    task_service: TaskService
    provider: BaseLLMProvider
    cloner: RepositoryCloner | None = None

    @property
    def workspace_root(self) -> Path:
        root = get_settings().workspace_root or WORKSPACES_ROOT
        return Path(root)

    def workspace_for(self, task_id: str) -> Path:
        return self.workspace_root / task_id

    def repo_dir(self, task_id: str) -> Path:
        return self.workspace_for(task_id) / "repo"

    def harness_for(
        self,
        task_id: str,
        agent: str,
        permissions: AgentPermissions | None = None,
        *,
        max_tokens: int | None = None,
        max_iterations: int | None = None,
        timeout_seconds: int | None = None,
    ) -> AgentHarness:
        """Build an AgentHarness bound to a task's audit log (section 15)."""
        from gitforce.app.harness.audit import AuditService
        from gitforce.app.harness.budgets import ExecutionBudget
        from gitforce.app.harness.executor import AgentHarness
        from gitforce.app.harness.permissions import permissions_for
        from gitforce.app.harness.retries import RetryPolicy
        from gitforce.app.harness.usage import UsageService

        settings = get_settings()
        audit = AuditService().make_handler(task_id)
        usage_sink = UsageService().make_handler(task_id)
        return AgentHarness(
            agent=agent,
            permissions=permissions or permissions_for(agent),
            budget=ExecutionBudget.with_limits(
                max_tokens=max_tokens,
                max_iterations=max_iterations
                or settings.agent_max_iterations,
                timeout_seconds=timeout_seconds
                or settings.agent_timeout_seconds,
            ),
            retry_policy=RetryPolicy(max_attempts=3),
            audit=audit,
            usage_sink=usage_sink,
            task_id=task_id,
        )

    def wrapped_provider_for(
        self, task_id: str, agent: str
    ) -> BaseLLMProvider:
        """Return an LLM provider wrapped by the harness so every call is
        budgeted, redacted, and recorded for cost tracking (sections 15,
        41, 44). Agents constructed with this provider report per-call
        usage through the harness usage sink.
        """
        return self.harness_for(task_id, agent).wrap_provider(self.provider)

    def mcp_for(
        self, task_id: str, agent: str, *, execution: PermissionLevel | None = None
    ) -> MCPClient:
        """Permission-bound MCP client for a graph agent (section 17).

        Every tool call made through this client passes the permission
        model; the coder cannot, e.g., push changes or reply on GitHub.
        The MCP grants are derived from the harness permission set so the
        MCP layer cannot exceed what the harness allows (section 17).
        """
        from gitforce.app.harness.permissions import (
            mcp_permissions_from,
            permissions_for,
        )
        from gitforce.app.mcp.client import MCPClient
        from gitforce.app.mcp.factory import build_registry

        registry = build_registry(
            repo_dir=self.repo_dir(task_id),
            workspace=self.workspace_for(task_id),
            provider=self.provider,
            execution_backend=get_settings().sandbox_backend,
            include_execution=execution is not None,
        )
        harness_perms = permissions_for(agent)
        perms = mcp_permissions_from(harness_perms)
        return MCPClient(registry, perms)


@traced_node("repository")
async def repository_node(state: ForgeState, ctx: AgentContext) -> dict:
    task = await ctx.task_service.get_task(state["task_id"])
    repo_dir = ctx.workspace_for(state["task_id"]) / "repo"
    if not repo_dir.exists() or not any(repo_dir.iterdir()):
        cloner = ctx.cloner or RepositoryCloner()
        await ctx.task_service.emit(state["task_id"], "repository.clone.started")
        repo_dir = await cloner.clone(
            task.repository_url,
            ctx.workspace_for(state["task_id"]),
            branch=task.target_branch,
        )
        await ctx.task_service.emit(state["task_id"], "repository.clone.completed")

    agent = RepositoryAnalysisAgent(
        ctx.wrapped_provider_for(state["task_id"], "repository")
    )
    await ctx.task_service.emit(state["task_id"], "agent.repository.started")
    analysis = await agent.analyze(task.repository_url, repo_dir)
    await ctx.task_service.emit(state["task_id"], "agent.repository.completed")

    commit_sha = await _index_repository(task.repository_url, repo_dir)
    return {
        "repository_analysis": analysis,
        "commit_sha": commit_sha or "",
    }


async def _index_repository(repository_url: str, repo_dir: Path) -> str | None:
    """Background RAG index of the cloned repo (Phase 5, section 11.1).

    Uses its own DB session (matching the background-run pattern) so the
    graph node never blocks on a session owned by the task service.
    """
    from gitforce.app.database.session import SessionLocal
    from gitforce.app.rag.indexer import RepositoryIndexer

    try:
        async with SessionLocal() as session:
            result = await RepositoryIndexer(session).index(
                repository_url, repo_dir
            )
        return result.commit_sha
    except Exception:  # noqa: BLE001
        # Indexing is best-effort; a failure must not block the workflow.
        return None


@traced_node("requirements")
async def requirements_node(state: ForgeState, ctx: AgentContext) -> dict:
    agent = RequirementsAgent(
        ctx.wrapped_provider_for(state["task_id"], "requirements")
    )
    feedback = [
        a.model_dump() for a in (state.get("feedback_analyses") or [])
    ]
    await ctx.task_service.emit(state["task_id"], "agent.requirements.started")
    requirements = await agent.analyze(
        state.get("issue") or {},
        state.get("issue_comments") or [],
        feedback=feedback,
    )
    await ctx.task_service.emit(state["task_id"], "agent.requirements.completed")
    return {"requirements": requirements}


@traced_node("planner")
async def planner_node(state: ForgeState, ctx: AgentContext) -> dict:
    task_id = state["task_id"]
    agent = PlannerAgent(ctx.wrapped_provider_for(task_id, "planner"))
    await ctx.task_service.emit(task_id, "agent.planner.started")

    retrieved = await _retrieve_relevant_code(
        ctx,
        state.get("repository_url") or "",
        state.get("commit_sha"),
        state["requirements"].problem,
    )

    plan = await agent.create_plan(
        state["repository_analysis"].model_dump(),
        state["requirements"].model_dump(),
        retrieved_context=retrieved,
    )
    await ctx.task_service.emit(task_id, "agent.planner.completed")
    return {"plan": plan, "retrieved_context": retrieved}


async def _retrieve_relevant_code(
    ctx: AgentContext, repository_url: str, commit_sha: str | None, query: str
) -> str:
    """Hybrid retrieval over the indexed repo (Phase 5, section 11.3)."""
    from gitforce.app.database.session import SessionLocal
    from gitforce.app.rag.retriever import Retriever

    if not repository_url:
        return ""
    try:
        async with SessionLocal() as session:
            retriever = Retriever(session)
            chunks = await retriever.retrieve(
                repository_url, query, commit_sha=commit_sha, top_k=6
            )
            return retriever.assemble_context(chunks, max_chars=6000)
    except Exception:  # noqa: BLE001
        return ""


@traced_node("coder")
async def coder_node(state: ForgeState, ctx: AgentContext) -> dict:
    """Generate real file modifications and apply them to the workspace.

    Reuses the repository clone from the repository node and writes the
    implementation (section 12) before tests run against it.
    """
    task_id = state["task_id"]
    agent = CoderAgent(ctx.wrapped_provider_for(task_id, "coder"))
    await ctx.task_service.emit(task_id, "agent.coder.started")

    harness = ctx.harness_for(task_id, "coder")

    mcp = ctx.mcp_for(task_id, "coder")
    result = await mcp.call("list_files", {"recursive": True})
    existing_files = (
        result.data.get("files", []) if result.ok else _list_files(ctx.repo_dir(task_id))
    )
    intent_result = await harness.run(
        agent.plan,
        state["repository_analysis"].architecture_summary,
        state["requirements"].model_dump(),
        state["plan"].files_to_modify,
        require=Permission.WORKSPACE_READ,
    )
    if not intent_result.ok:
        raise RuntimeError(f"Coder plan failed: {intent_result.error}")
    intent = intent_result.value
    fix_value = state.get("fix_analysis")
    fix_analysis = fix_value.model_dump() if fix_value else None
    test_value = state.get("test_results")
    test_results = test_value.model_dump() if test_value else None

    impl_result = await harness.run(
        agent.implement,
        state["repository_analysis"].architecture_summary,
        state["requirements"].model_dump(),
        state["plan"].model_dump(),
        intent.model_dump(),
        existing_files,
        fix_analysis=fix_analysis,
        test_results=test_results,
        require=Permission.WORKSPACE_WRITE,
    )
    if not impl_result.ok:
        raise RuntimeError(f"Coder implement failed: {impl_result.error}")
    implementation = impl_result.value

    changes: list[dict] = []
    for change in implementation.files:
        if _write_change(ctx.repo_dir(task_id), change.path, change.content):
            changes.append({"path": change.path, "added_or_modified": True})
    await ctx.task_service.emit(
        task_id, "agent.coder.completed", metadata={"changes": changes}
    )
    return {
        "coding_intent": intent.model_dump(),
        "implementation": implementation,
        "changes": changes,
    }


@traced_node("tester")
async def tester_node(state: ForgeState, ctx: AgentContext) -> dict:
    """Run the repo's tests/lint/typecheck/build inside a sandbox (section 19)."""
    task_id = state["task_id"]
    await ctx.task_service.emit(task_id, "agent.tester.started")
    sandbox = create_sandbox(ctx.workspace_for(task_id))
    try:
        agent = TesterAgent(ctx.wrapped_provider_for(task_id, "tester"), sandbox)
        results = await agent.run(ctx.repo_dir(task_id))
    finally:
        await sandbox.close()
    await ctx.task_service.emit(task_id, "agent.tester.completed")
    return {"test_results": results}


@traced_node("failure_analyzer")
async def failure_analyzer_node(state: ForgeState, ctx: AgentContext) -> dict:
    """Identify the root cause of test failures before re-coding (section 20)."""
    task_id = state["task_id"]
    await ctx.task_service.emit(task_id, "agent.failure_analyzer.started")
    agent = FailureAnalyzer(ctx.wrapped_provider_for(task_id, "failure_analyzer"))
    analysis = await agent.analyze(
        state["requirements"].model_dump(),
        state["plan"].model_dump(),
        state["test_results"].model_dump(),
        state["implementation"].summary,
    )
    await ctx.task_service.emit(task_id, "agent.failure_analyzer.completed")
    return {
        "fix_analysis": analysis,
        "fix_analysis_steps": [analysis.model_dump()],
    }


@traced_node("security")
async def security_node(state: ForgeState, ctx: AgentContext) -> dict:
    """Static security scan + LLM interpretation (section 21)."""
    task_id = state["task_id"]
    await ctx.task_service.emit(task_id, "agent.security.started")
    agent = SecurityAgent(ctx.wrapped_provider_for(task_id, "security"))
    files: dict[str, str] = {}
    for change in state.get("changes", []):
        content = _read_file(ctx.repo_dir(task_id), change["path"])
        if content is not None:
            files[change["path"]] = content
    scan_context = agent.static_scan(files)
    results = await agent.analyze(
        scan_context, list(files.keys()) or [c["path"] for c in state.get("changes", [])]
    )
    await ctx.task_service.emit(task_id, "agent.security.completed")
    return {"security_results": results}


@traced_node("reviewer")
async def reviewer_node(state: ForgeState, ctx: AgentContext) -> dict:
    """Independent code review of the generated changes (section 22)."""
    task_id = state["task_id"]
    await ctx.task_service.emit(task_id, "agent.reviewer.started")
    agent = ReviewAgent(ctx.wrapped_provider_for(task_id, "reviewer"))
    diff = _git_diff(ctx.repo_dir(task_id))
    results = await agent.review(
        state["requirements"].model_dump(),
        state["plan"].model_dump(),
        state["implementation"].summary,
        diff,
        state["test_results"].model_dump(),
        state["security_results"].model_dump(),
    )
    await ctx.task_service.emit(task_id, "agent.reviewer.completed")
    return {"review_results": results}


@traced_node("judge")
async def judge_node(state: ForgeState, ctx: AgentContext) -> dict:
    """LLM-as-Judge with an isolated, critical perspective (sections 23, 43)."""
    task_id = state["task_id"]
    await ctx.task_service.emit(task_id, "agent.judge.started")
    agent = JudgeAgent(ctx.wrapped_provider_for(task_id, "judge"))
    diff = _git_diff(ctx.repo_dir(task_id))
    results = await agent.judge(
        state.get("issue") or {},
        state["requirements"].model_dump(),
        state["plan"].model_dump(),
        diff,
        state["test_results"].model_dump(),
        state["security_results"].model_dump(),
        state["review_results"].model_dump(),
    )
    await ctx.task_service.emit(task_id, "agent.judge.completed")
    return {"judge_results": results}


def _list_files(repo_dir: Path) -> list[str]:
    if not repo_dir.exists():
        return []
    return [str(p.relative_to(repo_dir))
            for p in sorted(repo_dir.rglob("*"))
            if p.is_file() and ".git" not in p.parts][:200]


def _safe_target(repo_dir: Path, relative: str) -> Path | None:
    candidate = (repo_dir / relative).resolve()
    try:
        candidate.relative_to(repo_dir.resolve())
    except ValueError:
        return None
    return candidate


def _write_change(repo_dir: Path, relative: str, content: str) -> bool:
    target = _safe_target(repo_dir, relative)
    if target is None:
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return True


def _read_file(repo_dir: Path, relative: str) -> str | None:
    target = _safe_target(repo_dir, relative)
    if target is None or not target.exists():
        return None
    try:
        return target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _git_diff(repo_dir: Path) -> str:
    try:
        import subprocess

        result = subprocess.run(  # noqa: S603
            ["git", "diff", "--", "."],  # noqa: S607
            cwd=repo_dir,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return (result.stdout or "")[:20000]
    except (OSError, subprocess.TimeoutExpired):  # type: ignore[attr-defined]
        return ""


@traced_node("needs_clarification")
async def needs_clarification_node(state: ForgeState, ctx: AgentContext) -> dict:
    """Human-in-the-loop: pause the workflow and wait for clarification.

    The graph is interrupted; the dashboard answers via
    ``POST /api/tasks/{id}/resume`` which re-invokes the graph with the
    human's answer.
    """
    task_id = state["task_id"]
    await ctx.task_service.pause_task(task_id)
    await ctx.task_service.emit(
        task_id,
        "workflow.human_clarification_required",
        metadata={"ambiguities": state["requirements"].ambiguities},
    )
    answer = interrupt(
        {"type": "clarification", "ambiguities": state["requirements"].ambiguities}
    )
    return {"metadata": {"clarification": answer}, "status": "running"}


@traced_node("finalize")
async def finalize_node(state: ForgeState, ctx: AgentContext) -> dict:
    task_id = state["task_id"]
    await ctx.task_service.complete_task(task_id)
    return {"status": "completed"}


@traced_node("failed")
async def failed_node(state: ForgeState, ctx: AgentContext) -> dict:
    """Failure terminal (section 20): the fix loop was exhausted without a
    passing test run, so the task fails with the last error detail."""
    task_id = state["task_id"]
    error = "Fix loop exhausted: tests never passed"
    test_results = state.get("test_results")
    if test_results is not None and test_results.failures:
        error = f"{error}: {test_results.failures[0][:500]}"
    await ctx.task_service.fail_task(task_id, error)
    return {"status": "failed"}


@traced_node("delivery")
async def delivery_node(state: ForgeState, ctx: AgentContext) -> dict:
    """Phase 8 PR delivery: build the report + PR description, then fork,
    branch, commit, push, and open a pull request.

    Runs through the harness under the ``delivery`` permission set so the
    git/PR actions are permission-gated and audited.
    """
    from gitforce.app.agents.delivery import DeliveryAgent
    from gitforce.app.services.report import build_task_report

    task_id = state["task_id"]
    task = await ctx.task_service.get_task(task_id)
    await ctx.task_service.emit(task_id, "agent.delivery.started")

    report = build_task_report(
        task_id=task_id,
        issue_url=task.issue_url,
        repository_analysis=state["repository_analysis"],
        requirements=state["requirements"],
        plan=state["plan"],
        implementation=state["implementation"],
        test_results=state["test_results"],
        security_results=state["security_results"],
        review_results=state["review_results"],
        judge_results=state["judge_results"],
        changes=state.get("changes", []),
    )

    harness = ctx.harness_for(task_id, "delivery")
    git = GitWorktree(ctx.repo_dir(task_id))
    agent = DeliveryAgent(ctx.wrapped_provider_for(task_id, "delivery"))

    pr = await harness.run(
        _deliver,
        git,
        agent,
        state,
        report,
        require=Permission.GIT_PUSH,
    )
    if not pr.ok:
        # Non-fatal: persist the report but do not fail the whole task.
        await ctx.task_service.emit(
            task_id, "agent.delivery.failed", metadata={"error": pr.error}
        )
        return {"report": report.to_dict(), "pr": None, "status": state.get("status")}

    await ctx.task_service.update_agent_result(task_id, "report", report.to_dict())
    await ctx.task_service.update_agent_result(task_id, "pr", pr.value)
    await ctx.task_service.emit(
        task_id,
        "agent.delivery.completed",
        metadata={"pr": pr.value.get("number"), "cycle": pr.value.get("cycle")},
    )
    plan = state.get("plan")
    requirements = state.get("requirements")
    iteration = {
        "cycle": pr.value.get("cycle", 1),
        "pr_number": pr.value.get("number"),
        "title": pr.value.get("title"),
        "branch": pr.value.get("branch"),
        "commit_sha": pr.value.get("commit_sha"),
        "plan": plan.model_dump() if plan else None,
        "requirements": requirements.model_dump() if requirements else None,
    }
    return {
        "report": report.to_dict(),
        "pr": pr.value,
        "pr_iterations": [iteration],  # section 29 iteration history
        "status": state.get("status"),
    }


@traced_node("feedback")
async def feedback_node(state: ForgeState, ctx: AgentContext) -> dict:
    """Phase 9 reviewer feedback loop: poll the PR, classify feedback.

    Pulls review + issue comments off the PR, runs the Feedback Analyzer,
    and decides whether a re-planning cycle is required. When the reviewer
    requests a meaningful change we return to the planner (via the graph
    router) rather than blindly patching (section 28).
    """
    from gitforce.app.github.client import parse_repository_url

    task_id = state["task_id"]
    pr = state.get("pr") or {}
    pr_number = pr.get("number")
    await ctx.task_service.emit(task_id, "feedback.poll.started")

    repository_url = state.get("repository_url") or ""
    try:
        ref = parse_repository_url(repository_url)
    except Exception:  # noqa: BLE001
        ref = None

    comments: list[dict] = []
    if pr_number and ref is not None:
        async with GitHubClient() as client:
            comments = await _fetch_pr_feedback(client, ref, pr_number)

    if not comments:
        await ctx.task_service.emit(task_id, "feedback.none")
        return {"pr_cycles": state.get("pr_cycles", 0)}

    await ctx.task_service.emit(
        task_id, "feedback.found", metadata={"count": len(comments)}
    )

    agent = FeedbackAnalyzer(ctx.wrapped_provider_for(task_id, "feedback"))
    analyses = []
    for comment in comments:
        analysis = await agent.analyze(
            comment=comment.get("body") or "",
            comment_url=comment.get("html_url") or "",
            requirements=state["requirements"].model_dump(),
            implementation_summary=state["implementation"].summary,
        )
        analyses.append(analysis)

    actionable = [a for a in analyses if a.actionable]
    await ctx.task_service.emit(
        task_id,
        "feedback.analyzed",
        metadata={
            "count": len(analyses),
            "actionable": len(actionable),
            "requires_replanning": any(a.requires_replanning for a in actionable),
        },
    )

    return {
        "reviewer_feedback": comments,
        "feedback_analyses": analyses,
        "pr_cycles": state.get("pr_cycles", 0) + 1,
    }


async def _fetch_pr_feedback(
    client: GitHubClient, ref: GitHubRepositoryRef, pr_number: int
) -> list[dict]:
    """Collect code review comments + general comments off the PR."""
    try:
        review = await client.list_pull_request_comments(ref, pr_number)
    except Exception:  # noqa: BLE001
        review = []
    try:
        general = await client.list_issue_comments_for_pr(ref, pr_number)
    except Exception:  # noqa: BLE001
        general = []
    return review + general


async def _deliver(
    git: GitWorktree,
    agent,
    state: ForgeState,
    report,
) -> dict:
    """Create the PR description, then commit and push the changes via a
    fork, and open the pull request."""
    from gitforce.app.github.client import parse_repository_url

    description = await agent.describe(
        issue_url=report.issue_url,
        task_id=report.task_id,
        repository_analysis=report.repository_analysis,
        requirements=report.requirements,
        plan=report.plan,
        implementation=report.implementation,
        test_results=report.test_results,
        security_results=report.security_results,
        review_results=report.review_results,
        judge_results=report.judge_results,
        diff_stat=git.diff_stat(),
        changes=report.changes,
    )

    repository_url = state.get("repository_url") or ""
    ref = parse_repository_url(repository_url)
    branch = f"forgeai/{report.task_id[:8]}"
    git.ensure_branch(branch)
    git.add_all()
    commit_sha = git.current_sha()
    if git.has_changes():
        commit_sha = git.commit(f"{description.title}\n\nForgeAI task {report.task_id}")
    diff = git.diff()

    async with GitHubClient() as client:
        await client.refresh_auth()
        token = client._token  # noqa: SLF001
        upstream = await client.get_repository(ref)
        existing = state.get("pr") or {}
        if existing.get("number") and existing.get("fork"):
            # Re-planning cycle: push fresh commits and update the PR that
            # is already open (sections 28, 29) instead of a blind patch.
            clone_url = existing.get("clone_url", "")
            if clone_url:
                _push_to_fork(git, {"clone_url": clone_url}, branch, token)
            pr = await client.update_pull_request(
                ref,
                existing["number"],
                title=description.title,
                body=description.body,
            )
            fork = {"full_name": existing["fork"], "clone_url": clone_url}
        else:
            fork = await client.create_fork(ref)
            _push_to_fork(git, fork, branch, token)
            owner = upstream.get("full_name", "").split("/")[0]
            pr = await client.create_pull_request(
                ref,
                title=description.title,
                body=description.body,
                head=f"{owner}:{branch}",
                base=upstream.get("default_branch") or "main",
            )

    return {
        "number": pr.get("number"),
        "title": description.title,
        "html_url": pr.get("html_url"),
        "branch": branch,
        "commit_sha": commit_sha,
        "diff": diff[:5000],
        "body": description.body[:5000],
        "fork": fork.get("full_name"),
        "clone_url": fork.get("clone_url", ""),
        "cycle": state.get("pr_cycles", 0) + 1,
    }

def _push_to_fork(git: GitWorktree, fork: dict, branch: str, token: str | None = None) -> None:
    """    Best-effort push to the forked clone URL (Phase 8/9).

    Real GitHub delivery pushes the branch so the PR tracks the work. In
    sandboxed/local environments no token is present so this is a no-op
    rather than a failure.
    """
    from gitforce.app.github.app_auth import resolve_github_token_sync

    token = token or resolve_github_token_sync()
    clone_url = fork.get("clone_url")
    if not token or not clone_url:
        return
    try:
        auth_url = clone_url.replace(
            "https://github.com/", f"https://x-access-token:{token}@github.com/"
        ) if clone_url.startswith("https://github.com/") else clone_url
        git.set_remote("origin", auth_url)
        git.push("origin", branch)
    except GitError as exc:  # noqa: BLE001
        logger.warning("push to fork failed for branch %s: %s", branch, exc)