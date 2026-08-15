from __future__ import annotations

from pathlib import Path

from gitforce.app.llm.providers import BaseLLMProvider
from gitforce.app.mcp.documentation import DocumentationMCPServer
from gitforce.app.mcp.execution import ExecutionMCPServer
from gitforce.app.mcp.github import GitHubMCPServer
from gitforce.app.mcp.registry import MCPRegistry
from gitforce.app.mcp.repository import RepositoryMCPServer


def build_registry(
    *,
    repo_dir: str | Path,
    workspace: str | Path,
    provider: BaseLLMProvider | None = None,
    github_client=None,
    execution_backend: str | None = None,
    include_execution: bool = True,
) -> MCPRegistry:
    """Assemble the four standard ForgeAI MCP servers (section 17)."""
    servers = [
        RepositoryMCPServer(repo_dir),
        DocumentationMCPServer(repo_dir),
    ]
    if github_client is not None:
        servers.insert(0, GitHubMCPServer(github_client))
    if include_execution and provider is not None:
        servers.append(
            ExecutionMCPServer(
                provider, workspace, backend=execution_backend
            )
        )
    return MCPRegistry(servers)
