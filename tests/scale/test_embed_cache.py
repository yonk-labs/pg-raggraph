"""Tests for process-level local embedding model caching."""

from pg_raggraph.embedding import FastEmbedProvider, _get_fastembed_model


class CountingTextEmbedding:
    calls = 0

    def __init__(self, *, model_name: str, threads: int | None = None):
        self.model_name = model_name
        self.threads = threads
        CountingTextEmbedding.calls += 1

    def embed(self, texts: list[str]):
        return [[0.0, 0.0, 0.0] for _ in texts]


def test_fastembed_model_cached_by_model_and_threads(monkeypatch):
    _get_fastembed_model.cache_clear()
    CountingTextEmbedding.calls = 0
    monkeypatch.setattr("fastembed.TextEmbedding", CountingTextEmbedding)

    first = FastEmbedProvider("BAAI/bge-small-en-v1.5", threads=1)
    second = FastEmbedProvider("BAAI/bge-small-en-v1.5", threads=1)
    other_threads = FastEmbedProvider("BAAI/bge-small-en-v1.5", threads=2)

    assert first.dimension == 3
    assert second.dimension == 3
    assert other_threads.dimension == 3
    assert CountingTextEmbedding.calls == 2

    _get_fastembed_model.cache_clear()
