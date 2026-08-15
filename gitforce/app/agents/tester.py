from __future__ import annotations

import re
from pathlib import Path

from gitforce.app.agents.base import AgentBase
from gitforce.app.agents.models import TestResults
from gitforce.app.execution.sandbox import ExecutionResult, Sandbox
from gitforce.app.llm.providers import BaseLLMProvider

_PYTEST_SUMMARY = re.compile(
    r"^(\d+) (passed|failed|error)"
)
_PYTEST_HEADER = re.compile(r"^(\d+) passed(?:, (\d+) failed)?")
_PYTEST_ALL = re.compile(
    r"^(\d+) passed(?:, (\d+) (?:failed|error))?"
)


class TesterAgent:
    """Runs the repository's tests and static checks inside a sandbox (section 19)."""

    def __init__(
        self, provider: BaseLLMProvider, sandbox: Sandbox
    ) -> None:
        self._provider = provider
        self._sandbox = sandbox
        self._agent = AgentBase(provider)

    def discover_tests(self, repo_dir: Path) -> list[str]:
        test_dirs = {repo_dir / "tests", repo_dir / "test"}
        found: list[str] = []
        for base in test_dirs:
            if not base.exists():
                continue
            for path in sorted(base.rglob("test_*.py")):
                found.append(str(path.relative_to(repo_dir)))
            for path in sorted(base.rglob("*_test.py")):
                found.append(str(path.relative_to(repo_dir)))
        return found

    async def _run(
        self,
        argv: list[str],
        repo_dir: Path,
        timeout: int = 600,
    ) -> ExecutionResult:
        return await self._sandbox.run(
            argv, purpose="test", cwd=repo_dir, timeout_seconds=timeout
        )

    async def run(self, repo_dir: Path) -> TestResults:
        tests = self.discover_tests(repo_dir)
        results = TestResults()
        if not tests:
            results.failures.append("No test files found in repo")
            results.passed = False
            return results

        # 1) Run the relevant/full suite first.
        output = await self._run(
            ["python", "-m", "pytest", "--tb=short", "-q", "."], repo_dir
        )
        results.tests_run, results.tests_passed, results.tests_failed = (
            self._parse_pytest(output)
        )
        if not output.succeeded or results.tests_failed:
            results.passed = False
            results.failures.append(
                self._tail(output.stderr or output.stdout, 2000)
            )
        else:
            results.passed = True

        # 2) Lint (optional: continue if the tool is missing).
        lint = await self._run(
            ["python", "-m", "ruff", "check", "."], repo_dir, timeout=300
        )
        if lint.returncode != 0 and "No module named" not in lint.stderr:
            results.lint_passed = False
            results.passed = False

        # 3) Typecheck (optional).
        mypy = await self._run(
            ["python", "-m", "mypy", "--ignore-missing-imports", "."],
            repo_dir,
            timeout=300,
        )
        if mypy.returncode != 0 and "No module named" not in mypy.stderr:
            results.typecheck_passed = False
            results.passed = False

        return results

    def _parse_pytest(
        self, result: ExecutionResult
    ) -> tuple[int, int, int]:
        text = (result.stdout or "") + (result.stderr or "")
        for line in reversed(text.splitlines()):
            line = line.strip()
            match = _PYTEST_SUMMARY.match(line)
            if match:
                count = int(match.group(1))
                kind = match.group(2)
                if kind == "passed":
                    return count, count, 0
                if kind == "failed":
                    return count, 0, count
                return count, 0, count
            match = _PYTEST_ALL.match(line)
            if match:
                passed = int(match.group(1))
                failed = int(match.group(2) or 0)
                return passed + failed, passed, failed
        return 0, 0, 1

    @staticmethod
    def _tail(text: str, length: int) -> str:
        return text[-length:] if text else "(no output)"
