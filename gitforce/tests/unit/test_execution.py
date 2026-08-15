from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from gitforce.app.execution.commands import (
    CommandDeniedError,
    parse_command,
    validate_command,
)
from gitforce.app.execution.local import LocalSandbox


class TestCommandAllowlist:
    def test_allowed_test_command(self) -> None:
        argv = parse_command("pytest tests -q", purpose="test")
        assert argv == ["pytest", "tests", "-q"]

    def test_denied_shell_operator(self) -> None:
        with pytest.raises(CommandDeniedError):
            parse_command("pytest && rm -rf /", purpose="test")

    def test_denied_shell_pipe(self) -> None:
        with pytest.raises(CommandDeniedError):
            validate_command(["python", "-c", "x", "|", "sh"], purpose="test")

    def test_denied_unlisted_binary(self) -> None:
        with pytest.raises(CommandDeniedError):
            validate_command(["rm", "-rf", "/"], purpose="test")

    def test_denied_command_substitution(self) -> None:
        with pytest.raises(CommandDeniedError):
            validate_command(["echo", "`", "id", "`"], purpose="test")

    def test_inspect_purpose_allows_read_only(self) -> None:
        parse_command("cat file.txt", purpose="inspect")


class TestLocalSandbox:
    def test_runs_command(self, tmp_path: Path) -> None:
        async def _run() -> str:
            sandbox = LocalSandbox(tmp_path, timeout_seconds=10)
            result = await sandbox.run(
                ["python", "-c", "print('hello')"], purpose="inspect"
            )
            return result.stdout.strip()

        assert asyncio.run(_run()) == "hello"

    def test_rejects_dangerous_command(self, tmp_path: Path) -> None:
        async def _run() -> None:
            sandbox = LocalSandbox(tmp_path)
            await sandbox.run(["rm", "-rf", "/"], purpose="test")

        with pytest.raises(CommandDeniedError):
            asyncio.run(_run())

    def test_cwd_is_workspace(self, tmp_path: Path) -> None:
        (tmp_path / "marker.txt").write_text("x")

        async def _run() -> str:
            sandbox = LocalSandbox(tmp_path)
            result = await sandbox.run(
                ["ls", "marker.txt"], purpose="inspect"
            )
            return result.stdout.strip()

        assert asyncio.run(_run()) == "marker.txt"