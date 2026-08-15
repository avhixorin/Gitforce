from __future__ import annotations

from pathlib import Path

from gitforce.app.config.settings import Settings, get_settings
from gitforce.app.execution.docker import DockerSandbox
from gitforce.app.execution.local import LocalSandbox
from gitforce.app.execution.sandbox import Sandbox


def create_sandbox(
    workspace: str | Path,
    settings: Settings | None = None,
    *,
    backend: str | None = None,
) -> Sandbox:
    """Create a sandbox for a workspace.

    backend is one of "docker" | "local"; defaults to the configured
    SANDBOX_BACKEND (docker in production, local in development).
    """
    settings = settings or get_settings()
    backend = backend or settings.sandbox_backend
    ws = Path(workspace)
    timeout = settings.sandbox_timeout_seconds
    cpu = settings.sandbox_cpu_limit
    memory = settings.sandbox_memory_limit
    network = not settings.sandbox_network_restricted

    if backend == "local":
        return LocalSandbox(
            ws, timeout_seconds=timeout, cpu_limit=cpu,
            memory_limit=memory, network_enabled=network,
        )
    return DockerSandbox(
        ws,
        image=settings.sandbox_image,
        timeout_seconds=timeout,
        cpu_limit=cpu,
        memory_limit=memory,
        network_enabled=network,
    )