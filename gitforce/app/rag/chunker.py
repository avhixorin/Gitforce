from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

# File extensions we understand structurally; everything else falls back to
# line-based chunking.
_LANGUAGE_EXTENSIONS: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".jsx": "javascript",
    ".tsx": "typescript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".hpp": "cpp",
    ".cs": "csharp",
    ".rb": "ruby",
    ".php": "php",
    ".swift": "swift",
    ".kt": "kotlin",
    ".sql": "sql",
    ".html": "html",
    ".css": "css",
    ".md": "markdown",
    ".toml": "config",
    ".yaml": "config",
    ".yml": "config",
    ".json": "config",
    ".ini": "config",
    ".cfg": "config",
}

_BINARY_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg",
    ".pdf", ".zip", ".gz", ".tar", ".woff", ".woff2", ".ttf",
    ".pyc", ".pyo", ".so", ".dll", ".dylib", ".exe",
}

_SKIP_DIRS = {
    ".git", ".venv", "venv", "node_modules", "__pycache__",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox", "dist",
    "build", ".idea", ".vscode", "target", "vendor",
}

_SKIP_PATTERNS = re.compile(
    r"(^|/)(\.env(\.|$)|.*\.min\.(js|css)$)", re.IGNORECASE
)

_FALLBACK_CHUNK_SIZE = 60
_FALLBACK_OVERLAP = 10


@dataclass
class Chunk:
    path: str
    language: str
    symbol: str
    chunk_type: str
    start_line: int
    end_line: int
    content: str


def language_for(path: str) -> str:
    ext = Path(path).suffix.lower()
    return _LANGUAGE_EXTENSIONS.get(ext, "text")


def is_indexable(path: str) -> bool:
    """True if the file should be considered for indexing."""
    ext = Path(path).suffix.lower()
    if ext in _BINARY_EXTENSIONS:
        return False
    if any(f"/{d}/" in f"/{path}" for d in _SKIP_DIRS):
        return False
    if _SKIP_PATTERNS.search(path):
        return False
    return True


def chunk_source(path: str, source: str) -> list[Chunk]:
    """Code-aware chunking (section 11.2).

    Python files are split by AST into modules, classes, functions and
    methods; everything else uses a line-based fallback.
    """
    language = language_for(path)
    if language == "python":
        chunks = _chunk_python(path, source)
        if chunks:
            return chunks
    return _chunk_lines(path, source, language)


def _chunk_python(path: str, source: str) -> list[Chunk]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    lines = source.splitlines()
    chunks: list[Chunk] = []

    for node in ast.walk(tree):
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            start = max(node.lineno - 1, 0)
            end = min(getattr(node, "end_lineno", node.lineno), len(lines))
            content = "\n".join(lines[start:end])
            if not content.strip():
                continue
            chunks.append(
                Chunk(
                    path=path,
                    language="python",
                    symbol=node.name,
                    chunk_type=_node_type(node),
                    start_line=start + 1,
                    end_line=end,
                    content=content,
                )
            )
    return chunks


def _node_type(node: ast.AST) -> str:
    if isinstance(node, ast.ClassDef):
        return "class"
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return "method" if _is_method(node) else "function"
    return "module"


def _is_method(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return bool(
        node.args.args
        and node.args.args[0].arg in {"self", "cls"}
    )


def _chunk_lines(path: str, source: str, language: str) -> list[Chunk]:
    lines = source.splitlines()
    chunks: list[Chunk] = []
    step = _FALLBACK_CHUNK_SIZE - _FALLBACK_OVERLAP
    for start in range(0, max(len(lines), 1), step):
        end = min(start + _FALLBACK_CHUNK_SIZE, len(lines))
        if end <= start:
            break
        chunks.append(
            Chunk(
                path=path,
                language=language,
                symbol="",
                chunk_type="module",
                start_line=start + 1,
                end_line=end,
                content="\n".join(lines[start:end]),
            )
        )
        if end >= len(lines):
            break
    return chunks