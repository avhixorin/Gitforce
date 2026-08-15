from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

_TOKEN_RE = re.compile(
    r"(?P<scheme>https?://)[^/@\s]+@(?P<host>github\.com)",
    re.I,
)
_TOKEN_IN_PATH_RE = re.compile(r"(?i)(token[=:]\s*)\S+")


class GitError(Exception):
    """Raised when a git command fails."""


def _redact(text: str) -> str:
    """Strip credentials embedded in git URLs / errors so tokens never leak
    into logs (section 44)."""
    text = _TOKEN_RE.sub(r"\g<scheme>[REDACTED]@\g<host>", text)
    text = _TOKEN_IN_PATH_RE.sub(r"\g<1>[REDACTED]", text)
    return text


@dataclass
class GitCommandResult:
    stdout: str
    stderr: str
    returncode: int

    @property
    def ok(self) -> bool:
        return self.returncode == 0


class GitWorktree:
    """Runs git commands inside a repository checkout (Phase 8).

    Follows the existing sandbox-style subprocess pattern (see the RAG
    indexer's ``_head_commit``) while centralising branch/commit/push so the
    delivery node stays thin. ``base_url`` (default github.com) keeps push
    targets configurable for local/test remotes.
    """

    def __init__(
        self,
        repo_dir: str | Path,
        *,
        timeout_seconds: int = 60,
        base_url: str = "https://github.com",
    ) -> None:
        self._repo = Path(repo_dir)
        self._timeout = timeout_seconds
        self._base_url = base_url.rstrip("/")

    def _run(self, argv: list[str]) -> GitCommandResult:
        try:
            result = subprocess.run(  # noqa: S603
                ["git", *argv],  # noqa: S607
                cwd=str(self._repo),
                capture_output=True,
                text=True,
                timeout=self._timeout,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:  # type: ignore[attr-defined]
            raise GitError(
                f"git {_redact(' '.join(argv))} failed: {_redact(str(exc))}"
            ) from exc
        return GitCommandResult(
            stdout=result.stdout.strip(),
            stderr=result.stderr.strip(),
            returncode=result.returncode,
        )

    def current_branch(self) -> str:
        result = self._run(["rev-parse", "--abbrev-ref", "HEAD"])
        if not result.ok:
            raise GitError(f"Could not read current branch: {result.stderr}")
        return result.stdout

    def create_branch(self, branch: str) -> None:
        result = self._run(["checkout", "-b", branch])
        if not result.ok:
            raise GitError(f"Could not create branch '{branch}': {result.stderr}")

    def ensure_branch(self, branch: str) -> None:
        """Switch to an existing branch or create it from HEAD (Phase 9).

        On a re-planning cycle the ForgeAI branch already exists; we must
        resume it rather than error.
        """
        has = self._run(["rev-parse", "--verify", f"refs/heads/{branch}"])
        if has.ok:
            result = self._run(["checkout", branch])
            if not result.ok:
                raise GitError(
                    f"Could not checkout branch '{branch}': {result.stderr}"
                )
            return
        self.create_branch(branch)

    def has_changes(self) -> bool:
        result = self._run(["status", "--porcelain"])
        return bool(result.stdout.strip())

    def current_sha(self) -> str:
        result = self._run(["rev-parse", "HEAD"])
        if not result.ok:
            raise GitError(f"Could not read HEAD sha: {result.stderr}")
        return result.stdout

    def add_all(self) -> None:
        result = self._run(["add", "-A"])
        if not result.ok:
            raise GitError(f"git add failed: {result.stderr}")

    def commit(self, message: str) -> str:
        result = self._run(["commit", "-m", message])
        if not result.ok:
            raise GitError(f"git commit failed: {result.stderr}")
        sha = self._run(["rev-parse", "HEAD"])
        return sha.stdout

    def push(self, remote: str, branch: str) -> None:
        result = self._run(["push", "-u", remote, branch])
        if not result.ok:
            raise GitError(f"git push failed: {_redact(result.stderr)}")

    def remote_url(self, remote: str) -> str:
        result = self._run(["remote", "get-url", remote])
        if not result.ok:
            raise GitError(f"No remote '{remote}': {result.stderr}")
        return result.stdout

    def diff_stat(self) -> str:
        result = self._run(["diff", "--stat", "HEAD~1", "HEAD"])
        return result.stdout if result.ok else ""

    def diff(self) -> str:
        result = self._run(["diff", "HEAD~1", "HEAD"])
        return (result.stdout or "")[:20000]

    def set_remote(self, remote: str, url: str) -> None:
        result = self._run(["remote", "set-url", remote, url])
        if not result.ok:
            raise GitError(f"Could not set remote '{remote}': {result.stderr}")
