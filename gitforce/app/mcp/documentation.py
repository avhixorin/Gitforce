from __future__ import annotations

import re
from pathlib import Path

from gitforce.app.mcp.base import MCPServer, ToolInput
from gitforce.app.mcp.permissions import PermissionLevel

_DOC_PATTERNS = (
    "README*",
    "docs/**/*.md",
    "docs/**/*.rst",
    "*.md",
    "*.rst",
)


class SearchDocsArgs(ToolInput):
    query: str
    max_results: int = 10


class FetchDocsArgs(ToolInput):
    path: str


class DocumentationMCPServer(MCPServer):
    """Documentation MCP server: search and fetch repository docs
    (section 17: search_documentation, fetch_documentation)."""

    name = "documentation"

    def __init__(self, repo_dir: str | Path) -> None:
        self._repo = Path(repo_dir).resolve()
        super().__init__()

    def _register_tools(self) -> None:
        self._tool(
            "search_documentation",
            "Search documentation files for a query.",
            PermissionLevel.READ,
            self._search,
            SearchDocsArgs,
        )
        self._tool(
            "fetch_documentation",
            "Fetch the contents of a documentation file.",
            PermissionLevel.READ,
            self._fetch,
            FetchDocsArgs,
        )

    def _doc_files(self) -> list[Path]:
        files: list[Path] = []
        for pattern in _DOC_PATTERNS:
            files.extend(self._repo.glob(pattern))
        # dedupe, keep stable order
        return list(dict.fromkeys(files))

    async def _search(self, query: str, max_results: int) -> dict:
        terms = [t.lower() for t in re.findall(r"\w+", query)]
        hits: list[dict] = []
        for file_path in self._doc_files():
            if not file_path.is_file():
                continue
            try:
                text = file_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            lower = text.lower()
            score = sum(lower.count(t) for t in terms)
            if score > 0:
                hits.append(
                    {
                        "path": str(file_path.relative_to(self._repo)),
                        "score": score,
                    }
                )
        hits.sort(key=lambda h: h["score"], reverse=True)
        return {"results": hits[:max_results]}

    async def _fetch(self, path: str) -> dict:
        target = (self._repo / path).resolve()
        try:
            target.relative_to(self._repo)
        except ValueError:
            return {"error": f"Path escapes repository: {path}"}
        if not target.exists() or not target.is_file():
            return {"error": f"No such documentation file: {path}"}
        try:
            content = target.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            return {"error": str(exc)}
        return {"path": path, "content": content}
