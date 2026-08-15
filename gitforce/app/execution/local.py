from __future__ import annotations

import asyncio
import os
import resource
import time
from pathlib import Path

from gitforce.app.execution.commands import parse_command
from gitforce.app.execution.sandbox import (
    ExecutionResult,
    Sandbox,
    SandboxError,
)


class LocalSandbox(Sandbox):
    """In-process sandbox using subprocess + command allowlist.

    Suitable for development and tests. It enforces a timeout and a command
    allowlist, and (on POSIX) a virtual memory limit via setrlimit in a
    subprocess-pre-exec hook. It is NOT a security boundary like Docker.
    """

    async def run(
        self,
        command: str | list[str],
        *,
        purpose: str = "test",
        cwd: str | Path | None = None,
        timeout_seconds: int | None = None,
    ) -> ExecutionResult:
        argv = parse_command(command, purpose=purpose)
        run_cwd = Path(cwd) if cwd else self.workspace
        run_cwd.mkdir(parents=True, exist_ok=True)
        timeout = timeout_seconds or self.timeout_seconds

        mem_bytes = _memory_limit_bytes(self.memory_limit)
        start = time.perf_counter()

        def _pre_exec() -> None:
            if mem_bytes > 0:
                resource.setrlimit(
                    resource.RLIMIT_AS, (mem_bytes, mem_bytes)
                )

        env = os.environ.copy()
        if not self.network_enabled:
            # Best-effort: no new vars, the allowlist + timeout are the main
            # controls here; Docker is the real network isolation.
            pass

        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                cwd=str(run_cwd),
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                preexec_fn=_pre_exec,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )
                timed_out = False
            except TimeoutError:
                proc.kill()
                stdout, stderr = await proc.communicate()
                timed_out = True
        except FileNotFoundError as exc:
            raise SandboxError(f"Executable not found: {argv[0]}") from exc

        return ExecutionResult(
            command=" ".join(argv),
            returncode=(
                proc.returncode if proc.returncode is not None else 1
            ),
            stdout=stdout.decode(errors="replace"),
            stderr=stderr.decode(errors="replace"),
            duration_ms=(time.perf_counter() - start) * 1000,
            timed_out=timed_out,
        )

    async def close(self) -> None:
        return None


def _memory_limit_bytes(limit: str) -> int:
    """Parse a memory limit string like '2g' into bytes (0 = unlimited)."""
    limit = limit.strip().lower()
    if not limit or limit == "0":
        return 0
    multipliers = {"k": 1024, "m": 1024**2, "g": 1024**3, "t": 1024**4}
    if limit[-1] in multipliers:
        return int(float(limit[:-1]) * multipliers[limit[-1]])
    return int(float(limit))