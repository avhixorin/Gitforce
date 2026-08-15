from __future__ import annotations

import re
from collections import Counter

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gitforce.app.config.settings import Settings, get_settings
from gitforce.app.database.models import DocumentChunk
from gitforce.app.rag.embeddings import (
    EmbeddingProvider,
    create_embedding_provider,
)
from gitforce.app.rag.reranker import Reranker, ScoredChunk

RetrievedChunk = ScoredChunk


class Retriever:
    """Hybrid retrieval: vector + keyword search merged and reranked (11.3)."""

    def __init__(
        self,
        session: AsyncSession,
        embeddings: EmbeddingProvider | None = None,
        reranker: Reranker | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._session = session
        self._settings = settings or get_settings()
        self._embeddings = embeddings or create_embedding_provider(
            self._settings
        )
        self._reranker = reranker or Reranker(self._settings)

    async def retrieve(
        self,
        repository_url: str,
        query: str,
        *,
        commit_sha: str | None = None,
        top_k: int = 8,
        filters: dict | None = None,
    ) -> list[RetrievedChunk]:
        stmt = select(DocumentChunk).where(
            DocumentChunk.repository_url == repository_url
        )
        if commit_sha:
            stmt = stmt.where(DocumentChunk.commit_sha == commit_sha)
        filters = filters or {}
        if filters.get("path"):
            stmt = stmt.where(DocumentChunk.path.like(filters["path"]))
        if filters.get("chunk_type"):
            stmt = stmt.where(DocumentChunk.chunk_type == filters["chunk_type"])
        if filters.get("language"):
            stmt = stmt.where(DocumentChunk.language == filters["language"])

        rows = list(
            (await self._session.execute(stmt)).scalars().all()
        )
        if not rows:
            return []

        query_vector = (await self._embeddings.embed([query]))[0]

        # Vector search
        vector_scored = [
            (_cosine(query_vector, row.embedding), row)
            for row in rows
            if row.embedding
        ]
        vector_scored.sort(key=lambda t: t[0], reverse=True)

        # Keyword search
        keyword_scored = _keyword_search(rows, query)

        # Merge via reciprocal rank fusion
        fused: dict[int, float] = {}
        for rank, (_, vrow) in enumerate(vector_scored):
            fused[id(vrow)] = fused.get(id(vrow), 0.0) + 1.0 / (60 + rank)
        for rank, (_, krow) in enumerate(keyword_scored):
            fused[id(krow)] = fused.get(id(krow), 0.0) + 1.0 / (60 + rank)

        by_id = {id(row): row for row in rows}
        candidates: list[RetrievedChunk] = []
        for chunk_id, _ in sorted(
            fused.items(), key=lambda t: t[1], reverse=True
        )[: top_k * 4]:
            row = by_id.get(chunk_id)
            if row is None:
                continue
            if filters.get("symbol") and row.symbol != filters["symbol"]:
                continue
            v_score = next(
                (s for s, r in vector_scored if id(r) == chunk_id), 0.0
            )
            k_score = next(
                (s for s, r in keyword_scored if id(r) == chunk_id), 0.0
            )
            candidates.append(
                ScoredChunk(
                    path=row.path,
                    symbol=row.symbol,
                    chunk_type=row.chunk_type,
                    start_line=row.start_line,
                    end_line=row.end_line,
                    content=row.content,
                    vector_score=v_score,
                    keyword_score=k_score,
                )
            )

        reranked = self._reranker.rerank(query, candidates)
        for chunk in reranked:
            chunk.score = chunk.final_score
        return reranked[:top_k]

    def assemble_context(
        self, chunks: list[RetrievedChunk], max_chars: int = 8000
    ) -> str:
        """Context assembly: format chunks into a prompt-ready block (11.3)."""
        parts: list[str] = []
        used = 0
        for chunk in chunks:
            header = (
                f"## {chunk.path}:{chunk.start_line}-{chunk.end_line}"
                f" ({chunk.symbol or chunk.chunk_type})\n"
            )
            block = header + chunk.content + "\n"
            if used + len(block) > max_chars:
                break
            parts.append(block)
            used += len(block)
        return "\n".join(parts)


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = sum(x * x for x in a) ** 0.5 or 1.0
    nb = sum(y * y for y in b) ** 0.5 or 1.0
    return dot / (na * nb)


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", text.lower())


def _keyword_search(
    rows: list[DocumentChunk], query: str
) -> list[tuple[float, DocumentChunk]]:
    terms = _tokenize(query)
    if not terms:
        return []
    doc_terms: list[Counter[str]] = [
        Counter(_tokenize(row.content)) for row in rows
    ]
    doc_freq: Counter[str] = Counter()
    for counter in doc_terms:
        doc_freq.update(set(counter))
    n = len(rows)
    scored: list[tuple[float, DocumentChunk]] = []
    for row, counter in zip(rows, doc_terms, strict=True):
        total = sum(counter.values()) or 1
        score = 0.0
        for term in terms:
            idf = (n / (1 + doc_freq[term])) + 1.0
            score += (counter.get(term, 0) / total) * idf
        scored.append((score, row))
    scored.sort(key=lambda t: t[0], reverse=True)
    return scored
