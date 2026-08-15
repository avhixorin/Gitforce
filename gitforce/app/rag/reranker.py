from __future__ import annotations

import math
import re
from collections.abc import Callable
from dataclasses import dataclass

from gitforce.app.config.settings import Settings, get_settings


@dataclass
class ScoredChunk:
    """A retrieval candidate with blended scores (section 11.3)."""

    path: str
    symbol: str
    chunk_type: str
    start_line: int
    end_line: int
    content: str
    score: float = 0.0
    vector_score: float = 0.0
    keyword_score: float = 0.0
    final_score: float = 0.0


class Reranker:
    """Combines hybrid retrieval scores and boosts exact symbol matches."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        vector_weight: float = 0.6,
        keyword_weight: float = 0.4,
        symbol_boost: float = 0.3,
    ) -> None:
        self._settings = settings or get_settings()
        self._vector_weight = vector_weight
        self._keyword_weight = keyword_weight
        self._symbol_boost = symbol_boost

    def rerank(
        self,
        query: str,
        candidates: list[ScoredChunk],
    ) -> list[ScoredChunk]:
        tokens = set(_tokenize(query))
        for chunk in candidates:
            chunk.final_score = (
                self._vector_weight * chunk.vector_score
                + self._keyword_weight * chunk.keyword_score
            )
            if chunk.symbol and chunk.symbol.lower() in tokens:
                chunk.final_score += self._symbol_boost
        return sorted(
            candidates, key=lambda c: c.final_score, reverse=True
        )


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*|[0-9]+", text.lower())


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


def make_reranker(settings: Settings | None = None) -> Callable[..., list[ScoredChunk]]:
    return Reranker(settings).rerank