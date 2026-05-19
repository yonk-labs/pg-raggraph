"""Tests for bounding local embedding ONNX threads."""

from pg_raggraph.config import PGRGConfig
from pg_raggraph.embedding import FastEmbedProvider, get_embedding_provider


class DummyTextEmbedding:
    calls = []

    def __init__(self, *, model_name: str, threads: int | None = None):
        self.calls.append({"model_name": model_name, "threads": threads})

    def embed(self, texts: list[str]):
        return [[0.0, 0.0, 0.0] for _ in texts]


def test_fastembed_provider_passes_threads(monkeypatch):
    DummyTextEmbedding.calls = []
    monkeypatch.setattr("fastembed.TextEmbedding", DummyTextEmbedding)

    FastEmbedProvider("BAAI/bge-small-en-v1.5", threads=1)

    assert DummyTextEmbedding.calls == [
        {"model_name": "BAAI/bge-small-en-v1.5", "threads": 1}
    ]


def test_get_embedding_provider_passes_configured_threads(monkeypatch):
    DummyTextEmbedding.calls = []
    monkeypatch.setattr("fastembed.TextEmbedding", DummyTextEmbedding)

    provider = get_embedding_provider(
        PGRGConfig(
            embedding_provider="local",
            embedding_model="BAAI/bge-small-en-v1.5",
            embedding_threads=3,
        )
    )

    assert isinstance(provider, FastEmbedProvider)
    assert DummyTextEmbedding.calls == [
        {"model_name": "BAAI/bge-small-en-v1.5", "threads": 3}
    ]
