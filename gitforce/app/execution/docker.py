from __future__ import annotations

import asyncio
from pathlib import Path

from gitforce.app.execution.commands import parse_command
from gitforce.app.execution.sandbox import (
    ExecutionResult,
    Sandbox,
    SandboxError,
)


class DockerSandbox(Sandbox):
    """Runs commands inside an isolated disposable Docker container (section 18).

    Enforces CPU/memory limits, a hard timeout, and disables network unless
    explicitly enabled. The workspace is bind-mounted read-write into the
    container.
    """

    def __init__(
        self,
        workspace: str | Path,
        image: str = "python:3.12-slim",
        *args,
        **kwargs,
    ) -> None:
        super().__init__(workspace, *args, **kwargs)
        self.image = image
        self._container_name: str | None = None

    async def run(
        self,
        command: str | list[str],
        *,
        purpose: str = "test",
        cwd: str | Path | None = None,
        timeout_seconds: int | None = None,
    ) -> ExecutionResult:
        argv = parse_command(command, purpose=purpose)
        timeout = timeout_seconds or self.timeout_seconds
        rel_cwd = (
            str(Path(cwd).relative_to(self.workspace)) if cwd else "."
        )

        network = "default" if self.network_enabled else "none"
        docker_args = [
            "docker",
            "run",
            "--rm",
            f"--network={network}",
            f"--cpus={self.cpu_limit}",
            f"--memory={self.memory_limit}",
            # Phase 12 hardening: read-only rootfs + no new privileges
            # so the container cannot escalate or modify its base image.
            "--read-only",
            "--security-opt=no-new-privileges",
            "--pids-limit=512",
            f"--workdir=/workspace/{rel_cwd.lstrip('/')}",
            f"--volume={self.workspace}:/workspace",
            self.image,
            *argv,
        ]
        try:
            proc = await asyncio.create_subprocess_exec(
                *docker_args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
        except TimeoutError as exc:
            raise SandboxError("Sandbox command timed out") from exc
        except FileNotFoundError as exc:
            raise SandboxError(
                "Docker is not available on this host"
            ) from exc

        return ExecutionResult(
            command=" ".join(argv),
            returncode=proc.returncode or 1,
            stdout=stdout.decode(errors="replace"),
            stderr=stderr.decode(errors="replace"),
            duration_ms=0.0,
        )

    async def close(self) -> None:
        return None