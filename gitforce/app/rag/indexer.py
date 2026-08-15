from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from gitforce.app.config.settings import Settings, get_settings
from gitforce.app.database.models import DocumentChunk
from gitforce.app.rag.chunker import Chunk, chunk_source, is_indexable
from gitforce.app.rag.embeddings import (
    EmbeddingProvider,
    create_embedding_provider,
)


@dataclass
class IndexResult:
    repository_url: str
    commit_sha: str
    files_indexed: int = 0
    chunks_created: int = 0
    chunks_deleted: int = 0


class RepositoryIndexer:
    """Indexes a cloned repository into code-aware, versioned chunks (11.1)."""

    def __init__(
        self,
        session: AsyncSession,
        embeddings: EmbeddingProvider | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._session = session
        self._settings = settings or get_settings()
        self._embeddings = embeddings or create_embedding_provider(
            self._settings
        )

    async def index(
        self,
        repository_url: str,
        repo_dir: str | Path,
        commit_sha: str | None = None,
    ) -> IndexResult:
        repo_dir = Path(repo_dir)
        commit_sha = commit_sha or _head_commit(repo_dir)
        if not commit_sha:
            raise ValueError(
                "Cannot index: no git commit found for repository"
            )

        chunks: list[Chunk] = []
        files = sorted(
            p.relative_to(repo_dir)
            for p in repo_dir.rglob("*")
            if p.is_file() and is_indexable(str(p.relative_to(repo_dir)))
        )
        for rel in files:
            path = repo_dir / rel
            try:
                source = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            chunks.extend(chunk_source(str(rel), source))

        # Version-aware: drop the previous index for this commit first.
        deleted = await self._session.execute(
            delete(DocumentChunk).where(
                DocumentChunk.repository_url == repository_url,
                DocumentChunk.commit_sha == commit_sha,
            )
        )
        chunks_deleted = int(getattr(deleted, "rowcount", 0) or 0)

        for chunk in chunks:
            embedding = (
                await self._embeddings.embed([chunk.content])
            )[0]
            self._session.add(
                DocumentChunk(
                    repository_url=repository_url,
                    commit_sha=commit_sha,
                    path=chunk.path,
                    language=chunk.language,
                    symbol=chunk.symbol,
                    chunk_type=chunk.chunk_type,
                    start_line=chunk.start_line,
                    end_line=chunk.end_line,
                    content=chunk.content,
                    embedding=embedding,
                )
            )
        await self._session.commit()

        return IndexResult(
            repository_url=repository_url,
            commit_sha=commit_sha,
            files_indexed=len(files),
            chunks_created=len(chunks),
            chunks_deleted=chunks_deleted,
        )


def _head_commit(repo_dir: Path) -> str | None:
    try:
        result = subprocess.run(  # noqa: S603
            ["git", "rev-parse", "HEAD"],  # noqa: S607
            cwd=str(repo_dir),
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):  # type: ignore[attr-defined]
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None
