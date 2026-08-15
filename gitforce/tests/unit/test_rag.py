from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from gitforce.app.config.settings import get_settings
from gitforce.app.database import models as db_models
from gitforce.app.database.session import SessionLocal, engine
from gitforce.app.rag.chunker import chunk_source, is_indexable
from gitforce.app.rag.embeddings import HashEmbeddingProvider
from gitforce.app.rag.indexer import RepositoryIndexer
from gitforce.app.rag.reranker import Reranker, ScoredChunk
from gitforce.app.rag.retriever import Retriever

PYTHON_SRC = '''"""demo module"""
import os


class Greeter:
    def hello(self, name: str) -> str:
        return f"Hello, {name}"


def square(x: int) -> int:
    return x * x
'''


@pytest.fixture(autouse=True)
async def _db():
    async with engine.begin() as conn:
        await conn.run_sync(db_models.Base.metadata.drop_all)
        await conn.run_sync(db_models.Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(db_models.Base.metadata.drop_all)


def _git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "proj"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "greeter.py").write_text(PYTHON_SRC)
    (repo / "README.md").write_text("# Demo\nA demo project.\n")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-q", "-m", "init"], check=True
    )
    return repo


def test_chunker_splits_python_into_symbols() -> None:
    chunks = chunk_source("src/greeter.py", PYTHON_SRC)
    symbols = {c.symbol for c in chunks}
    assert "Greeter" in symbols
    assert "hello" in symbols
    assert "square" in symbols
    by_symbol = {c.symbol: c for c in chunks}
    assert by_symbol["hello"].chunk_type == "method"
    assert by_symbol["square"].chunk_type == "function"


def test_chunker_ignores_binary_and_venv() -> None:
    assert not is_indexable("a.png")
    assert not is_indexable("node_modules/x/y.js")
    assert is_indexable("src/app.py")


def test_hash_embeddings_deterministic() -> None:
    provider = HashEmbeddingProvider(get_settings(), dimensions=128)
    a = provider._embed_one("def greet(name): return name")
    b = provider._embed_one("def greet(name): return name")
    c = provider._embed_one("def square(x): return x")
    assert a == b
    assert a != c


async def test_index_and_hybrid_retrieve(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    async with SessionLocal() as session:
        result = await RepositoryIndexer(session).index(str(repo), repo)
        assert result.files_indexed >= 2
        assert result.chunks_created >= 4  # class + method + function + readme

        retriever = Retriever(session)
        hits = await retriever.retrieve(
            str(repo), "square function", top_k=3
        )
        assert hits
        top = hits[0]
        assert "square" in top.content

        context = retriever.assemble_context(hits)
        assert top.path in context


async def test_index_is_version_aware(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    async with SessionLocal() as session:
        first = await RepositoryIndexer(session).index(str(repo), repo)
        second = await RepositoryIndexer(session).index(str(repo), repo)
        assert second.chunks_deleted == first.chunks_created
        assert second.chunks_created == first.chunks_created


def test_reranker_boosts_symbol_matches() -> None:
    reranker = Reranker(get_settings(), symbol_boost=0.5)
    candidates = [
        ScoredChunk(
            path="a.py",
            symbol="greet",
            chunk_type="function",
            start_line=1,
            end_line=2,
            content="def greet(): pass",
            vector_score=0.5,
            keyword_score=0.5,
        ),
        ScoredChunk(
            path="b.py",
            symbol="other",
            chunk_type="function",
            start_line=1,
            end_line=2,
            content="def other(): pass",
            vector_score=0.9,
            keyword_score=0.9,
        ),
    ]
    ranked = reranker.rerank("greet", candidates)
    assert ranked[0].path == "a.py"  # symbol boost overtakes higher scores
