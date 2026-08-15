from __future__ import annotations

import hashlib
import math
from abc import ABC, abstractmethod

from gitforce.app.config.settings import Settings, get_settings


class EmbeddingError(Exception):
    pass


class EmbeddingProvider(ABC):
    """Produces vector embeddings for text (section 11)."""

    def __init__(self, dimensions: int) -> None:
        self.dimensions = dimensions

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """OpenAI text-embedding-3-small (or configured model) via the SDK."""

    def __init__(
        self, settings: Settings | None = None, dimensions: int | None = None
    ) -> None:
        settings = settings or get_settings()
        super().__init__(
            dimensions or settings.embedding_dimensions or 1536
        )
        self._model = settings.embedding_model or "text-embedding-3-small"
        self._api_key = settings.openai_api_key
        self._base_url = settings.local_llm_base_url
        self._client = None

    def _get_client(self):
        if self._client is None:
            try:
                from openai import AsyncOpenAI
            except ImportError as exc:  # pragma: no cover
                raise EmbeddingError(
                    "openai package is not installed"
                ) from exc
            self._client = AsyncOpenAI(
                api_key=self._api_key, base_url=self._base_url
            )
        return self._client

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            response = await self._get_client().embeddings.create(
                model=self._model, input=texts
            )
            return [item.embedding for item in response.data]
        except Exception as exc:  # noqa: BLE001
            raise EmbeddingError(f"Embedding request failed: {exc}") from exc


class HashEmbeddingProvider(EmbeddingProvider):
    """Deterministic, offline embeddings for tests and development.

    Maps token shingles into a fixed-dimension bag-of-words vector via SHA
    hashing. The model has no semantic power, but it is stable and lets the
    full RAG pipeline run without API keys — identical text always yields
    the same vector, so similarity ordering is reproducible.
    """

    def __init__(
        self, settings: Settings | None = None, dimensions: int | None = None
    ) -> None:
        settings = settings or get_settings()
        super().__init__(dimensions or settings.embedding_dimensions or 1536)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(t) for t in texts]

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        tokens = _tokenize(text)
        if not tokens:
            return vector
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            idx = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[idx] += sign
        norm = math.sqrt(sum(v * v for v in vector)) or 1.0
        return [v / norm for v in vector]


def _tokenize(text: str) -> list[str]:
    import re

    return re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*|[0-9]+", text.lower())


def create_embedding_provider(
    settings: Settings | None = None, *, provider: str | None = None
) -> EmbeddingProvider:
    """Build the configured embedding provider (default: hash, offline)."""
    settings = settings or get_settings()
    name = (provider or settings.embedding_provider or "hash").lower()
    if name in {"openai", "api"}:
        return OpenAIEmbeddingProvider(settings)
    if name in {"local", "custom"}:
        return OpenAIEmbeddingProvider(settings)
    return HashEmbeddingProvider(settings)