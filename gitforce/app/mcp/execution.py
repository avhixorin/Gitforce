from __future__ import annotations

from pathlib import Path

from pydantic import Field

from gitforce.app.agents.tester import TesterAgent
from gitforce.app.execution.factory import create_sandbox
from gitforce.app.execution.sandbox import ExecutionResult
from gitforce.app.llm.providers import BaseLLMProvider
from gitforce.app.mcp.base import MCPServer, ToolInput
from gitforce.app.mcp.permissions import PermissionLevel


class RunArgs(ToolInput):
    command: str = Field(description="Command to run, e.g. 'pytest -q'")
    timeout_seconds: int = 600


class TestArgs(ToolInput):
    path: str = "."
    timeout_seconds: int = 600


class ExecutionMCPServer(MCPServer):
    """Execution MCP server: run tests/linter/typecheck/build/security scan
    inside the sandbox (section 17)."""

    name = "execution"

    def __init__(
        self,
        provider: BaseLLMProvider,
        workspace: str | Path,
        *,
        backend: str | None = None,
    ) -> None:
        self._provider = provider
        self._workspace = Path(workspace)
        self._backend = backend
        super().__init__()

    def _sandbox(self, timeout: int):
        return create_sandbox(
            self._workspace, backend=self._backend
        )

    def _register_tools(self) -> None:
        self._tool(
            "run_tests",
            "Run the repository test suite.",
            PermissionLevel.EXECUTE,
            self._run_tests,
            TestArgs,
        )
        self._tool(
            "run_linter",
            "Run the configured linter over the repository.",
            PermissionLevel.EXECUTE,
            self._run_linter,
            TestArgs,
        )
        self._tool(
            "run_typecheck",
            "Run the type checker over the repository.",
            PermissionLevel.EXECUTE,
            self._run_typecheck,
            TestArgs,
        )
        self._tool(
            "run_build",
            "Run a build of the project.",
            PermissionLevel.EXECUTE,
            self._run_build,
            TestArgs,
        )
        self._tool(
            "run_security_scan",
            "Run the security scanner over the repository.",
            PermissionLevel.EXECUTE,
            self._run_security_scan,
            TestArgs,
        )

    async def _run_tests(self, path: str, timeout_seconds: int) -> dict:
        sandbox = self._sandbox(timeout_seconds)
        try:
            tester = TesterAgent(self._provider, sandbox)
            repo = self._workspace / path if path != "." else self._workspace
            results = await tester.run(Path(repo))
            return results.model_dump()
        finally:
            await sandbox.close()

    async def _run_linter(self, path: str, timeout_seconds: int) -> dict:
        return await self._run_cmd(["python", "-m", "ruff", "check", "."],
                                   path, timeout_seconds)

    async def _run_typecheck(self, path: str, timeout_seconds: int) -> dict:
        return await self._run_cmd(
            ["python", "-m", "mypy", "--ignore-missing-imports", "."],
            path, timeout_seconds)

    async def _run_build(self, path: str, timeout_seconds: int) -> dict:
        return await self._run_cmd(
            ["python", "-m", "build"], path, timeout_seconds
        )

    async def _run_security_scan(self, path: str, timeout_seconds: int) -> dict:
        return await self._run_cmd(
            ["python", "-m", "bandit", "-r", "."], path, timeout_seconds
        )

    async def _run_cmd(
        self, argv: list[str], path: str, timeout_seconds: int
    ) -> dict:
        sandbox = self._sandbox(timeout_seconds)
        try:
            repo = self._workspace / path if path != "." else self._workspace
            result: ExecutionResult = await sandbox.run(
                argv, purpose="test", cwd=repo,
                timeout_seconds=timeout_seconds,
            )
            return result.model_dump()
        finally:
            await sandbox.close()
