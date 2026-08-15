from __future__ import annotations

import re
from pathlib import Path

from pydantic import Field

from gitforce.app.mcp.base import MCPServer, ToolInput
from gitforce.app.mcp.permissions import PermissionLevel
from gitforce.app.rag.chunker import chunk_source, is_indexable


class PathArgs(ToolInput):
    path: str = Field(default="", description="Relative path within the repo")


class ListArgs(ToolInput):
    path: str = ""
    recursive: bool = False


class SearchArgs(ToolInput):
    query: str
    path: str = ""
    max_results: int = 20


class RepositoryMCPServer(MCPServer):
    """Repository MCP server: filesystem tools over a cloned workspace
    (section 17: list_files, read_file, search_files, inspect_symbols,
    get_dependencies)."""

    name = "repository"

    def __init__(self, repo_dir: str | Path) -> None:
        self._repo = Path(repo_dir).resolve()
        super().__init__()

    def _safe(self, relative: str) -> Path | None:
        candidate = (self._repo / relative).resolve()
        try:
            candidate.relative_to(self._repo)
        except ValueError:
            return None
        return candidate

    def _register_tools(self) -> None:
        self._tool(
            "list_files",
            "List files in the repository (optionally recursive).",
            PermissionLevel.READ,
            self._list_files,
            ListArgs,
        )
        self._tool(
            "read_file",
            "Read a file's contents from the workspace.",
            PermissionLevel.READ,
            self._read_file,
            PathArgs,
        )
        self._tool(
            "search_files",
            "Search repository files for a substring/regex.",
            PermissionLevel.READ,
            self._search_files,
            SearchArgs,
        )
        self._tool(
            "inspect_symbols",
            "Return classes/functions/methods defined in a file.",
            PermissionLevel.READ,
            self._inspect_symbols,
            PathArgs,
        )
        self._tool(
            "get_dependencies",
            "Parse declared dependencies from package manifests.",
            PermissionLevel.READ,
            self._get_dependencies,
            PathArgs,
        )

    async def _list_files(self, path: str, recursive: bool) -> dict:
        target = self._safe(path) or self._repo
        if not target.is_dir():
            raise ValueError(f"Not a directory: {path}")
        pattern = "**/*" if recursive else "*"
        files = [
            str(p.relative_to(self._repo))
            for p in sorted(target.glob(pattern))
            if p.is_file() and is_indexable(str(p.relative_to(self._repo)))
        ]
        return {"files": files[:500], "count": len(files)}

    async def _read_file(self, path: str) -> dict:
        target = self._safe(path)
        if target is None:
            raise ValueError(f"Path escapes repository: {path}")
        if not target.exists() or not target.is_file():
            raise ValueError(f"No such file: {path}")
        try:
            content = target.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise ValueError(str(exc)) from exc
        return {
            "path": path,
            "content": content,
            "lines": len(content.splitlines()),
        }

    async def _search_files(self, query: str, path: str, max_results: int) -> dict:
        if not query.strip():
            raise ValueError("query must not be empty")
        pattern = re.compile(re.escape(query), re.IGNORECASE)
        base = self._safe(path) or self._repo
        matches: list[dict] = []
        for file_path in sorted(base.rglob("*")):
            if not file_path.is_file() or not is_indexable(
                str(file_path.relative_to(self._repo))
            ):
                continue
            try:
                lines = file_path.read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeDecodeError):
                continue
            for idx, line in enumerate(lines, start=1):
                if pattern.search(line):
                    matches.append(
                        {
                            "path": str(file_path.relative_to(self._repo)),
                            "line": idx,
                            "content": line.strip()[:200],
                        }
                    )
                    if len(matches) >= max_results:
                        return {"matches": matches, "count": len(matches)}
        return {"matches": matches, "count": len(matches)}

    async def _inspect_symbols(self, path: str) -> dict:
        target = self._safe(path)
        if target is None or not target.exists():
            raise ValueError(f"No such file: {path}")
        try:
            source = target.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise ValueError(str(exc)) from exc
        chunks = chunk_source(str(target.relative_to(self._repo)), source)
        symbols = [
            {
                "symbol": c.symbol,
                "type": c.chunk_type,
                "start_line": c.start_line,
                "end_line": c.end_line,
            }
            for c in chunks
            if c.symbol
        ]
        return {"path": path, "symbols": symbols}

    async def _get_dependencies(self, path: str) -> dict:
        target = self._safe(path)
        if target is None:
            target = self._repo
        deps: dict[str, list[str]] = {}
        for manifest in ("pyproject.toml", "requirements.txt"):
            candidate = target / manifest
            if candidate.exists():
                deps[manifest] = _parse_manifest(candidate)
        return {"dependencies": deps}


def _parse_manifest(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    if path.name == "requirements.txt":
        return [
            line.strip()
            for line in text.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
    # pyproject.toml: pull [project] dependencies if present.
    try:
        import tomllib
    except ImportError:  # pragma: no cover
        return []
    data = tomllib.loads(text)
    project = data.get("project", {})
    return list(project.get("dependencies", []))
