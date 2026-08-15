from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from pydantic import BaseModel


class ExecutionResult(BaseModel):
    command: str
    returncode: int
    stdout: str
    stderr: str
    duration_ms: float
    timed_out: bool = False

    @property
    def succeeded(self) -> bool:
        return self.returncode == 0 and not self.timed_out


class SandboxError(Exception):
    """Raised when the sandbox itself cannot run a command."""


class Sandbox(ABC):
    """Isolated execution boundary for generated code (section 18).

    Implementations must enforce resource limits, timeouts, network
    restrictions, and deny dangerous commands.
    """

    def __init__(
        self,
        workspace: str | Path,
        timeout_seconds: int = 600,
        cpu_limit: float = 2.0,
        memory_limit: str = "2g",
        network_enabled: bool = False,
    ) -> None:
        self.workspace = Path(workspace)
        self.timeout_seconds = timeout_seconds
        self.cpu_limit = cpu_limit
        self.memory_limit = memory_limit
        self.network_enabled = network_enabled

    @abstractmethod
    async def run(
        self,
        command: str | list[str],
        *,
        purpose: str = "test",
        cwd: str | Path | None = None,
        timeout_seconds: int | None = None,
    ) -> ExecutionResult:
        """Run a command inside the sandbox and return its result.

        Raises CommandDeniedError for non-allowlisted commands.
        """

    @abstractmethod
    async def close(self) -> None: ...

    async def __aenter__(self) -> Sandbox:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()