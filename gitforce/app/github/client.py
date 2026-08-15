from __future__ import annotations

import logging
import re
from urllib.parse import urlparse

import httpx

from gitforce.app.config.settings import get_settings

logger = logging.getLogger(__name__)

# e.g. https://github.com/org/repo or /issues/123
_REPO_RE = re.compile(r"^github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/?$", re.I)
_ISSUE_RE = re.compile(
    r"^github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/issues/(?P<number>\d+)/?$",
    re.I,
)


class GitHubValidationError(ValueError):
    pass


class GitHubRepositoryRef:
    def __init__(self, owner: str, repo: str) -> None:
        self.owner = owner
        self.repo = repo

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.repo}"


class GitHubIssueRef(GitHubRepositoryRef):
    def __init__(self, owner: str, repo: str, number: int) -> None:
        super().__init__(owner, repo)
        self.number = number


def parse_repository_url(url: str) -> GitHubRepositoryRef:
    parsed = urlparse(url.rstrip("/"))
    if parsed.scheme not in {"http", "https"} or parsed.netloc.lower() != "github.com":
        raise GitHubValidationError(f"Not a GitHub URL: {url}")
    match = _REPO_RE.match(f"{parsed.netloc}{parsed.path}")
    if not match:
        raise GitHubValidationError(f"Invalid GitHub repository URL: {url}")
    return GitHubRepositoryRef(match.group("owner"), match.group("repo"))


def parse_issue_url(url: str) -> GitHubIssueRef:
    parsed = urlparse(url.rstrip("/"))
    if parsed.scheme not in {"http", "https"} or parsed.netloc.lower() != "github.com":
        raise GitHubValidationError(f"Not a GitHub URL: {url}")
    match = _ISSUE_RE.match(f"{parsed.netloc}{parsed.path}")
    if not match:
        raise GitHubValidationError(f"Invalid GitHub issue URL: {url}")
    return GitHubIssueRef(
        match.group("owner"), match.group("repo"), int(match.group("number"))
    )


async def resolve_github_token() -> str | None:
    """Resolve the best available GitHub token (Phase 12): an installation
    token when the GitHub App is configured, else the classic token."""
    from gitforce.app.github.app_auth import GitHubAppAuthenticator

    async with GitHubAppAuthenticator() as auth:
        return await auth.get_token()


class GitHubClient:
    """Thin REST client for GitHub. Prefers an installation token from the
    GitHub App when configured (section 45), else the classic token."""

    BASE_URL = "https://api.github.com"

    def __init__(self, token: str | None = None) -> None:
        self._token = token or get_settings().github_token
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        self._client = httpx.AsyncClient(
            base_url=self.BASE_URL, headers=headers, timeout=30
        )

    async def refresh_auth(self) -> None:
        """Best-effort swap to an installation token when the GitHub App is
        configured. Falls back silently to the classic token on any error
        so delivery never fails solely because of app auth."""
        from gitforce.app.github.app_auth import GitHubAppAuthError

        try:
            token = await resolve_github_token()
        except GitHubAppAuthError as exc:
            logger.warning("GitHub App auth unavailable, using classic token: %s", exc)
            return
        if token:
            self._token = token
            self._client.headers["Authorization"] = f"Bearer {token}"

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> GitHubClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def get_repository(self, ref: GitHubRepositoryRef) -> dict:
        resp = await self._client.get(f"/repos/{ref.full_name}")
        resp.raise_for_status()
        data = resp.json()
        return {
            "full_name": data.get("full_name"),
            "description": data.get("description"),
            "default_branch": data.get("default_branch"),
            "language": data.get("language"),
            "clone_url": data.get("clone_url"),
            "html_url": data.get("html_url"),
            "stars": data.get("stargazers_count"),
            "topics": data.get("topics", []),
        }

    async def get_issue(self, ref: GitHubIssueRef) -> dict:
        resp = await self._client.get(
            f"/repos/{ref.full_name}/issues/{ref.number}"
        )
        resp.raise_for_status()
        data = resp.json()
        return {
            "number": data.get("number"),
            "title": data.get("title"),
            "state": data.get("state"),
            "body": data.get("body"),
            "labels": [label.get("name") for label in data.get("labels", [])],
            "assignees": [a.get("login") for a in data.get("assignees", [])],
            "created_at": data.get("created_at"),
            "updated_at": data.get("updated_at"),
            "html_url": data.get("html_url"),
        }

    async def get_issue_comments(self, ref: GitHubIssueRef) -> list[dict]:
        resp = await self._client.get(
            f"/repos/{ref.full_name}/issues/{ref.number}/comments"
        )
        resp.raise_for_status()
        return [
            {
                "id": c.get("id"),
                "user": (c.get("user") or {}).get("login"),
                "body": c.get("body"),
                "created_at": c.get("created_at"),
            }
            for c in resp.json()
        ]

    # ------------------------------------------------------------------
    # Phase 8 — PR delivery (fork/workspace, branch, push, PR)
    # ------------------------------------------------------------------

    async def create_fork(self, ref: GitHubRepositoryRef) -> dict:
        """Fork a repository under the authenticated user (Phase 8)."""
        resp = await self._client.post(f"/repos/{ref.full_name}/forks")
        resp.raise_for_status()
        data = resp.json()
        return {
            "full_name": data.get("full_name"),
            "clone_url": data.get("clone_url"),
            "default_branch": data.get("default_branch"),
        }

    async def create_branch(self, ref: GitHubRepositoryRef, branch: str) -> dict:
        """Create a branch in a repository from its default branch."""
        repo = await self.get_repository(ref)
        default_branch = repo.get("default_branch") or "main"
        base_sha = await self._default_branch_sha(ref, default_branch)
        resp = await self._client.post(
            f"/repos/{ref.full_name}/git/refs",
            json={"ref": f"refs/heads/{branch}", "sha": base_sha},
        )
        resp.raise_for_status()
        return resp.json()

    async def _default_branch_sha(self, ref: GitHubRepositoryRef, branch: str) -> str:
        resp = await self._client.get(
            f"/repos/{ref.full_name}/git/refs/heads/{branch}"
        )
        resp.raise_for_status()
        return resp.json()["object"]["sha"]

    async def create_pull_request(
        self,
        ref: GitHubRepositoryRef,
        *,
        title: str,
        body: str,
        head: str,
        base: str,
    ) -> dict:
        """Open a pull request (Phase 8). ``head`` may be ``user:branch``."""
        resp = await self._client.post(
            f"/repos/{ref.full_name}/pulls",
            json={
                "title": title,
                "body": body,
                "head": head,
                "base": base,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return {
            "number": data.get("number"),
            "title": data.get("title"),
            "state": data.get("state"),
            "html_url": data.get("html_url"),
            "head": (data.get("head") or {}).get("ref"),
            "base": (data.get("base") or {}).get("ref"),
        }

    async def get_pull_request(self, ref: GitHubRepositoryRef, number: int) -> dict:
        resp = await self._client.get(f"/repos/{ref.full_name}/pulls/{number}")
        resp.raise_for_status()
        data = resp.json()
        return {
            "number": data.get("number"),
            "title": data.get("title"),
            "state": data.get("state"),
            "html_url": data.get("html_url"),
            "mergeable": data.get("mergeable"),
            "merged": data.get("merged"),
            "additions": data.get("additions"),
            "deletions": data.get("deletions"),
        }

    # ------------------------------------------------------------------
    # Phase 9 — Reviewer feedback loop (poll + update PR)
    # ------------------------------------------------------------------

    async def list_pull_request_comments(
        self, ref: GitHubRepositoryRef, number: int
    ) -> list[dict]:
        """Review comments on a pull request (PR issues endpoint)."""
        resp = await self._client.get(
            f"/repos/{ref.full_name}/pulls/{number}/comments"
        )
        resp.raise_for_status()
        return [
            {
                "id": c.get("id"),
                "user": (c.get("user") or {}).get("login"),
                "body": c.get("body"),
                "path": c.get("path"),
                "line": c.get("line"),
                "html_url": c.get("html_url"),
                "created_at": c.get("created_at"),
            }
            for c in resp.json()
        ]

    async def list_issue_comments_for_pr(
        self, ref: GitHubRepositoryRef, number: int
    ) -> list[dict]:
        """General (non-code) comments on a pull request."""
        resp = await self._client.get(
            f"/repos/{ref.full_name}/issues/{number}/comments"
        )
        resp.raise_for_status()
        return [
            {
                "id": c.get("id"),
                "user": (c.get("user") or {}).get("login"),
                "body": c.get("body"),
                "html_url": c.get("html_url"),
                "created_at": c.get("created_at"),
            }
            for c in resp.json()
        ]

    async def update_pull_request(
        self,
        ref: GitHubRepositoryRef,
        number: int,
        *,
        title: str,
        body: str,
    ) -> dict:
        """Update a PR title/body after a re-planning cycle (Phase 9)."""
        resp = await self._client.patch(
            f"/repos/{ref.full_name}/pulls/{number}",
            json={"title": title, "body": body},
        )
        resp.raise_for_status()
        data = resp.json()
        return {
            "number": data.get("number"),
            "title": data.get("title"),
            "state": data.get("state"),
            "html_url": data.get("html_url"),
        }

    async def comment_on_pull_request(
        self, ref: GitHubRepositoryRef, number: int, body: str
    ) -> dict:
        """Leave a general comment on a pull request (Phase 9)."""
        resp = await self._client.post(
            f"/repos/{ref.full_name}/issues/{number}/comments",
            json={"body": body},
        )
        resp.raise_for_status()
        data = resp.json()
        return {"id": data.get("id"), "html_url": data.get("html_url")}