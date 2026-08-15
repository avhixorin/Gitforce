from __future__ import annotations

import asyncio

import pytest

from gitforce.app.mcp.client import MCPClient
from gitforce.app.mcp.documentation import DocumentationMCPServer
from gitforce.app.mcp.factory import build_registry
from gitforce.app.mcp.permissions import (
    MCPPermissionError,
    PermissionCategory,
    PermissionLevel,
    agent_with_extra,
    check_tool,
    default_permissions,
)
from gitforce.app.mcp.registry import MCPRegistry
from gitforce.app.mcp.repository import RepositoryMCPServer


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text(
        "def add(a: int, b: int) -> int:\n    return a + b\n\n"
        "class Calculator:\n    def multiply(self, a, b):\n        return a * b\n"
    )
    (tmp_path / "README.md").write_text(
        "# Demo\n\nThe calculator supports addition.\n"
    )
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname = \"demo\"\nversion = \"0.1.0\"\n"
        "dependencies = [\"httpx>=0.27\"]\n"
    )
    return tmp_path


async def _run(coro):
    return await asyncio.wait_for(coro, timeout=10)


async def test_repository_list_files(repo):
    server = RepositoryMCPServer(repo)
    result = await server.call("list_files", {"recursive": True})
    assert result.ok
    assert "src/main.py" in result.data["files"]


async def test_repository_read_file(repo):
    server = RepositoryMCPServer(repo)
    result = await server.call("read_file", {"path": "src/main.py"})
    assert result.ok
    assert "def add" in result.data["content"]


async def test_repository_path_traversal_blocked(repo):
    server = RepositoryMCPServer(repo)
    result = await server.call("read_file", {"path": "../secret.txt"})
    assert not result.ok


async def test_repository_inspect_symbols(repo):
    server = RepositoryMCPServer(repo)
    result = await server.call("inspect_symbols", {"path": "src/main.py"})
    assert result.ok
    symbols = {s["symbol"]: s["type"] for s in result.data["symbols"]}
    assert symbols["add"] == "function"
    assert symbols["Calculator"] == "class"


async def test_repository_get_dependencies(repo):
    server = RepositoryMCPServer(repo)
    result = await server.call("get_dependencies", {})
    assert result.ok
    assert "httpx>=0.27" in result.data["dependencies"]["pyproject.toml"]


async def test_documentation_search_and_fetch(repo):
    server = DocumentationMCPServer(repo)
    search = await server.call("search_documentation", {"query": "addition"})
    assert search.ok
    assert search.data["results"]
    fetch = await server.call("fetch_documentation", {"path": "README.md"})
    assert fetch.ok
    assert "calculator" in fetch.data["content"].lower()


async def test_permission_model_default_read_only(repo):
    from gitforce.app.config.settings import get_settings
    from gitforce.app.llm.providers import MockProvider
    from gitforce.app.mcp.execution import ExecutionMCPServer
    from gitforce.app.mcp.github import GitHubMCPServer
    from gitforce.app.mcp.registry import MCPRegistry

    settings = get_settings()
    provider = MockProvider(settings)
    github = GitHubMCPServer()
    try:
        registry = MCPRegistry(
            [
                github,
                RepositoryMCPServer(repo),
                ExecutionMCPServer(provider, repo),
            ]
        )
        perms = default_permissions("coder")
        client = MCPClient(registry, perms)

        # read tools are allowed
        result = await client.call("read_file", {"path": "README.md"})
        assert result.ok

        # execution tools are NOT allowed for a default read-only agent
        blocked = await client.call("run_tests", {})
        assert not blocked.ok
        assert "not permitted" in blocked.error

        # high-impact tools are always blocked even with write permission
        write_perms = agent_with_extra(
            "delivery", execution=PermissionLevel.EXECUTE
        )
        write_perms.allowed[PermissionCategory.GITHUB] = PermissionLevel.WRITE
        check = await client.bind(write_perms).call("push_changes", {})
        assert not check.ok
        assert "not permitted" in check.error
    finally:
        await github.aclose()


async def test_registry_unknown_tool(repo):
    registry = MCPRegistry([RepositoryMCPServer(repo)])
    result = await registry.call("nope", {})
    assert not result.ok
    assert "Unknown tool" in result.error


async def test_check_tool_raises():
    perms = default_permissions("tester")
    with pytest.raises(MCPPermissionError):
        check_tool(
            perms,
            "run_tests",
            PermissionCategory.EXECUTION,
            PermissionLevel.EXECUTE,
        )


async def test_client_lists_tools(repo):
    registry = build_registry(repo_dir=repo, workspace=repo)
    names = {t["name"] for t in MCPClient(registry).list_tools()}
    assert {
        "list_files",
        "read_file",
        "search_files",
        "inspect_symbols",
        "get_dependencies",
        "search_documentation",
        "fetch_documentation",
    }.issubset(names)
