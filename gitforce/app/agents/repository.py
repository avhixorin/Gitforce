from __future__ import annotations

import asyncio
from pathlib import Path

import httpx

from gitforce.app.agents.base import AgentBase
from gitforce.app.agents.models import RepositoryAnalysis
from gitforce.app.config.settings import get_settings
from gitforce.app.llm.models import LLMTaskType
from gitforce.app.llm.providers import BaseLLMProvider
from gitforce.prompts.loader import load_prompt

# Top-level files/dirs that tell us a lot but should not be chunked.
_IGNORED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "target",
    "dist",
    "build",
    ".next",
    ".gradle",
    ".tox",
}
_CONFIG_FILES = {
    "pyproject.toml": "python",
    "setup.py": "python",
    "setup.cfg": "python",
    "requirements.txt": "python",
    "Pipfile": "python",
    "package.json": "javascript/typescript",
    "package-lock.json": "javascript/typescript",
    "yarn.lock": "javascript/typescript",
    "pnpm-lock.yaml": "javascript/typescript",
    "Cargo.toml": "rust",
    "go.mod": "go",
    "pom.xml": "java",
    "build.gradle": "java",
    "build.gradle.kts": "java",
    "Gopkg.toml": "go",
    "composer.json": "php",
    "Gemfile": "ruby",
}


class RepositoryAnalysisError(Exception):
    pass


class RepositoryAnalysisAgent(AgentBase):
    task_type = LLMTaskType.CLASSIFICATION

    def __init__(self, provider: BaseLLMProvider) -> None:
        super().__init__(provider)

    async def analyze(self, repository_url: str, workspace: Path) -> RepositoryAnalysis:
        if not workspace.exists() or not any(workspace.iterdir()):
            raise RepositoryAnalysisError(
                "Workspace is empty; clone the repository first"
            )
        snapshot = self._build_snapshot(workspace)
        prompt = (
            load_prompt("repository", "analyze")
            .replace("{{repository_snapshot}}", snapshot)
            .replace("{{issue_summary}}", "Provide a general repository analysis.")
        )
        return await self.run_structured(
            prompt,
            RepositoryAnalysis,
            task_type=LLMTaskType.CLASSIFICATION,
            max_tokens=1500,
        )

    def _build_snapshot(self, root: Path, max_files: int = 120) -> str:
        lines: list[str] = []
        config_found: list[str] = []
        test_dirs: list[str] = []
        source_dirs: list[str] = []
        total_files = 0

        for path in sorted(root.rglob("*")):
            if path.is_dir():
                if path.name in _IGNORED_DIRS or any(
                    part in _IGNORED_DIRS for part in path.relative_to(root).parts
                ):
                    continue
                continue
            if any(part in _IGNORED_DIRS for part in path.relative_to(root).parts):
                continue
            total_files += 1
            rel = str(path.relative_to(root))
            if path.name in _CONFIG_FILES:
                config_found.append(rel)
            lower = rel.lower()
            if "/test" in lower or "/tests" in lower or path.name.startswith("test_"):
                test_dirs.append(rel)
            elif lower.endswith(
                (".py", ".js", ".ts", ".go", ".rs", ".java", ".rb", ".php")
            ):
                source_dirs.append(rel)

        lines.append(f"Total files: {total_files}")
        lines.append(f"Config files: {', '.join(config_found) or 'none'}")
        lines.append(f"Test files/dirs: {', '.join(test_dirs[:30]) or 'none'}")
        lines.append(
            f"Source files (sample): {', '.join(source_dirs[:60]) or 'none'}"
        )

        readme = root / "README.md"
        if readme.exists():
            content = readme.read_text(errors="replace")
            lines.append("--- README.md (first 1500 chars) ---")
            lines.append(content[:1500])
        return "\n".join(lines)


class RepositoryCloner:
    """Clones a repository into a per-task workspace using controlled git."""

    def __init__(self) -> None:
        self._settings = get_settings()

    async def clone(
        self,
        url: str,
        workspace: Path,
        *,
        branch: str | None = None,
        depth: int = 1,
    ) -> Path:
        workspace.mkdir(parents=True, exist_ok=True)
        repo_dir = workspace / "repo"
        argv = [
            "git",
            "clone",
            "--depth",
            str(depth),
        ]
        if branch:
            argv += ["--branch", branch]
        argv += [url, str(repo_dir)]
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RepositoryAnalysisError(
                f"git clone failed: {stderr.decode(errors='replace').strip()}"
            )
        return repo_dir


async def fetch_issue(
    owner: str, repo: str, number: int, token: str | None = None
) -> dict:
    """Fetch an issue via the REST API (used when no local task issue dict)."""
    settings = get_settings()
    headers = {"Accept": "application/vnd.github+json"}
    if token or settings.github_token:
        headers["Authorization"] = (
            f"Bearer {token or settings.github_token}"
        )
    async with httpx.AsyncClient(
        base_url="https://api.github.com", headers=headers, timeout=30
    ) as client:
        resp = await client.get(f"/repos/{owner}/{repo}/issues/{number}")
        resp.raise_for_status()
        return resp.json()