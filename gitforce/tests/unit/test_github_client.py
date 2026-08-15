from __future__ import annotations

import httpx
import pytest

from gitforce.app.github.client import (
    GitHubClient,
    GitHubRepositoryRef,
    parse_repository_url,
)


class _FakeTransport(httpx.AsyncBaseTransport):
    """Minimal GitHub REST fake: returns canned JSON for delivery calls."""

    def __init__(self, responses: dict[tuple[str, str], dict]) -> None:
        self._responses = responses
        self.requests: list[tuple[str, str]] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        key = (request.method, request.url.path)
        self.requests.append(key)
        body = self._responses.get(key)
        if body is None:
            return httpx.Response(404, request=request, text="{}")
        return httpx.Response(200, json=body, request=request)


@pytest.fixture
def ref() -> GitHubRepositoryRef:
    return parse_repository_url("https://github.com/org/proj")


async def test_create_fork(ref):
    transport = _FakeTransport(
        {("POST", "/repos/org/proj/forks"): {
            "full_name": "me/proj", "clone_url": "https://github.com/me/proj",
            "default_branch": "main",
        }}
    )
    async with GitHubClient() as client:
        client._client._transport = transport  # noqa: SLF001
        fork = await client.create_fork(ref)
    assert fork["full_name"] == "me/proj"


async def test_create_branch(ref):
    transport = _FakeTransport(
        {
            ("GET", "/repos/org/proj"): {
                "full_name": "org/proj", "default_branch": "main",
                "clone_url": "x", "html_url": "y",
            },
            ("GET", "/repos/org/proj/git/refs/heads/main"): {
                "object": {"sha": "abc123"}
            },
            ("POST", "/repos/org/proj/git/refs"): {
                "ref": "refs/heads/forgeai/x",
            },
        }
    )
    async with GitHubClient() as client:
        client._client._transport = transport  # noqa: SLF001
        created = await client.create_branch(ref, "forgeai/x")
    assert created["ref"] == "refs/heads/forgeai/x"


async def test_create_pull_request(ref):
    transport = _FakeTransport(
        {("POST", "/repos/org/proj/pulls"): {
            "number": 12, "title": "T", "state": "open",
            "html_url": "https://github.com/org/proj/pull/12",
            "head": {"ref": "forgeai/x"}, "base": {"ref": "main"},
        }}
    )
    async with GitHubClient() as client:
        client._client._transport = transport  # noqa: SLF001
        pr = await client.create_pull_request(
            ref, title="T", body="B", head="me:forgeai/x", base="main"
        )
    assert pr["number"] == 12
    assert pr["html_url"].endswith("/pull/12")


async def test_update_pull_request(ref):
    transport = _FakeTransport(
        {("PATCH", "/repos/org/proj/pulls/12"): {
            "number": 12, "title": "Updated", "state": "open",
            "html_url": "https://github.com/org/proj/pull/12",
        }}
    )
    async with GitHubClient() as client:
        client._client._transport = transport  # noqa: SLF001
        pr = await client.update_pull_request(ref, 12, title="Updated", body="B")
    assert pr["number"] == 12
    assert pr["title"] == "Updated"


async def test_list_pull_request_comments(ref):
    transport = _FakeTransport(
        {("GET", "/repos/org/proj/pulls/42/comments"): [
            {"id": 1, "user": {"login": "alice"}, "body": "nits", "path": "src/app.py", "line": 3, "html_url": "u1", "created_at": "2025-01-01T00:00:00Z"},
        ]}
    )
    async with GitHubClient() as client:
        client._client._transport = transport  # noqa: SLF001
        comments = await client.list_pull_request_comments(ref, 42)
    assert comments[0]["id"] == 1
    assert comments[0]["user"] == "alice"
    assert comments[0]["path"] == "src/app.py"


async def test_list_issue_comments_for_pr(ref):
    transport = _FakeTransport(
        {("GET", "/repos/org/proj/issues/42/comments"): [
            {"id": 2, "user": {"login": "bob"}, "body": "Looks good", "html_url": "u2", "created_at": "2025-01-02T00:00:00Z"},
        ]}
    )
    async with GitHubClient() as client:
        client._client._transport = transport  # noqa: SLF001
        comments = await client.list_issue_comments_for_pr(ref, 42)
    assert comments[0]["id"] == 2
    assert comments[0]["body"] == "Looks good"


async def test_comment_on_pull_request(ref):
    transport = _FakeTransport(
        {("POST", "/repos/org/proj/issues/12/comments"): {
            "id": 99, "html_url": "https://github.com/org/proj/pull/12#issuecomment-99",
        }}
    )
    async with GitHubClient() as client:
        client._client._transport = transport  # noqa: SLF001
        result = await client.comment_on_pull_request(ref, 12, "thanks!")
    assert result["id"] == 99
    transport = _FakeTransport(
        {("GET", "/repos/org/proj/pulls/12"): {
            "number": 12, "title": "T", "state": "open", "mergeable": True,
            "merged": False, "additions": 3, "deletions": 1,
        }}
    )
    async with GitHubClient() as client:
        client._client._transport = transport  # noqa: SLF001
        pr = await client.get_pull_request(ref, 12)
    assert pr["number"] == 12
    assert pr["mergeable"] is True