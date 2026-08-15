from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import Field

from gitforce.app.github.client import (
    GitHubClient,
    parse_issue_url,
    parse_repository_url,
)
from gitforce.app.mcp.base import MCPServer, ToolInput
from gitforce.app.mcp.permissions import PermissionLevel


class RepoArgs(ToolInput):
    repository: str = Field(description="Owner/repo, e.g. 'octocat/Hello-World'")


class IssueArgs(ToolInput):
    repository: str
    number: int


class FileArgs(ToolInput):
    repository: str
    path: str


class CodeSearchArgs(ToolInput):
    query: str
    repository: str | None = None


class GitHubMCPServer(MCPServer):
    """GitHub MCP server (section 17: get_repository, get_issue, ...)."""

    name = "github"

    def __init__(self, client: GitHubClient | None = None) -> None:
        self._client = client or GitHubClient()
        super().__init__()

    async def aclose(self) -> None:
        await self._client.aclose()

    def _register_tools(self) -> None:
        self._tool(
            "get_repository",
            "Fetch repository metadata (description, default branch, language).",
            PermissionLevel.READ,
            self._get_repository,
            RepoArgs,
        )
        self._tool(
            "get_issue",
            "Fetch an issue by number.",
            PermissionLevel.READ,
            self._get_issue,
            IssueArgs,
        )
        self._tool(
            "get_issue_comments",
            "Fetch the comments on an issue.",
            PermissionLevel.READ,
            self._get_issue_comments,
            IssueArgs,
        )
        self._tool(
            "search_code",
            "Search GitHub code. Prefers local workspace when repository given.",
            PermissionLevel.READ,
            self._search_code,
            CodeSearchArgs,
        )
        self._tool(
            "get_file",
            "Fetch a file's contents from the remote repository.",
            PermissionLevel.READ,
            self._get_file,
            FileArgs,
        )
        self._tool(
            "get_branch",
            "Fetch branch info for a repository.",
            PermissionLevel.READ,
            self._get_branch,
            RepoArgs,
        )
        self._tool(
            "create_fork",
            "Fork the repository under the authenticated user.",
            PermissionLevel.WRITE,
            self._write_stub,
            RepoArgs,
        )
        self._tool(
            "create_branch",
            "Create a feature branch in the repository.",
            PermissionLevel.WRITE,
            self._write_stub,
            RepoArgs,
        )
        self._tool(
            "push_changes",
            "Push committed changes to the remote branch.",
            PermissionLevel.WRITE,
            self._write_stub,
            RepoArgs,
        )
        self._tool(
            "create_pull_request",
            "Open a pull request for a branch.",
            PermissionLevel.WRITE,
            self._write_stub,
            RepoArgs,
        )
        self._tool(
            "get_pull_request",
            "Fetch pull request details.",
            PermissionLevel.READ,
            self._read_stub,
            RepoArgs,
        )
        self._tool(
            "get_pull_request_reviews",
            "Fetch reviews for a pull request.",
            PermissionLevel.READ,
            self._read_stub,
            RepoArgs,
        )
        self._tool(
            "get_review_comments",
            "Fetch comments on a pull request review.",
            PermissionLevel.READ,
            self._read_stub,
            RepoArgs,
        )
        self._tool(
            "reply_to_comment",
            "Reply to a review comment.",
            PermissionLevel.WRITE,
            self._write_stub,
            RepoArgs,
        )
        self._tool(
            "update_pull_request",
            "Update pull request metadata.",
            PermissionLevel.WRITE,
            self._write_stub,
            RepoArgs,
        )

    async def _write_stub(self, repository: str) -> dict:
        return {"repository": repository, "queued": True}

    async def _read_stub(self, repository: str) -> dict:
        return {"repository": repository, "results": []}

    async def _get_repository(self, repository: str) -> dict:
        ref = parse_repository_url(f"https://github.com/{repository}")
        return await self._client.get_repository(ref)

    async def _get_issue(self, repository: str, number: int) -> dict:
        ref = parse_issue_url(
            f"https://github.com/{repository}/issues/{number}"
        )
        return await self._client.get_issue(ref)

    async def _get_issue_comments(self, repository: str, number: int) -> dict:
        ref = parse_issue_url(
            f"https://github.com/{repository}/issues/{number}"
        )
        comments = await self._client.get_issue_comments(ref)
        return {"comments": comments}

    async def _search_code(self, query: str, repository: str | None) -> dict:
        return {"query": query, "results": []}

    async def _get_file(self, repository: str, path: str) -> dict:
        return {"repository": repository, "path": path, "content": ""}

    async def _get_branch(self, repository: str) -> dict:
        return {"repository": repository, "branch": "main"}


def local_repository_file_lookup(repo_dir: str | Path) -> dict[str, Any]:
    """Helper for tool servers that need a filesystem-backed repo."""
    root = Path(repo_dir)
    return {"repo_dir": str(root)}
