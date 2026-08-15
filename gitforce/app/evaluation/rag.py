from __future__ import annotations

from gitforce.app.evaluation.models import RetrievalQuality
from gitforce.app.rag.retriever import Retriever


async def evaluate_retrieval(
    retriever: Retriever,
    *,
    repository_url: str,
    commit_sha: str | None = None,
    queries: list[tuple[str, list[str]]],
    top_k: int = 8,
) -> RetrievalQuality:
    """Evaluate retrieval quality for a set of (query, relevant_paths)
    pairs, reporting recall@k and precision@k (section 42).

    Each query maps to the set of repository paths a correct retrieval
    should return. recall@k = fraction of relevant paths retrieved;
    precision@k = fraction of retrieved chunks whose path is relevant.
    """
    quality = RetrievalQuality(queries=len(queries))
    for query, relevant_paths in queries:
        chunks = await retriever.retrieve(
            repository_url,
            query,
            commit_sha=commit_sha,
            top_k=top_k,
        )
        retrieved_paths = {c.path for c in chunks}
        hits = len(retrieved_paths & set(relevant_paths))

        quality.relevant_retrieved += hits
        if relevant_paths:
            quality.recall_at_k += hits / len(relevant_paths)
        if chunks:
            relevant_in_result = sum(
                1 for c in chunks if c.path in relevant_paths
            )
            quality.precision_at_k += relevant_in_result / len(chunks)

    if queries:
        quality.recall_at_k = round(quality.recall_at_k / len(queries), 4)
        quality.precision_at_k = round(quality.precision_at_k / len(queries), 4)
    return quality
