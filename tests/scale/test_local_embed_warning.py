"""Tests for local embedding provider scale warning."""

import logging

import pg_raggraph.embedding as embedding_mod
from pg_raggraph.config import PGRGConfig
from pg_raggraph.embedding import _get_fastembed_model, get_embedding_provider


class DummyTextEmbedding:
    def __init__(self, *, model_name: str, threads: int | None = None):
        self.model_name = model_name
        self.threads = threads

    def embed(self, texts: list[str]):
        return [[0.0, 0.0, 0.0] for _ in texts]


def test_local_embedding_provider_warns_once(monkeypatch, caplog):
    _get_fastembed_model.cache_clear()
    embedding_mod._local_provider_warned = False
    monkeypatch.setattr("fastembed.TextEmbedding", DummyTextEmbedding)
    caplog.set_level(logging.WARNING, logger="pg_raggraph.embedding")

    cfg = PGRGConfig(
        dsn="postgresql://postgres:postgres@localhost:6543/not_default",
        embedding_provider="local",
    )
    get_embedding_provider(cfg)
    get_embedding_provider(cfg)

    warnings = [
        rec.message for rec in caplog.records if "Using local embedding provider" in rec.message
    ]
    assert len(warnings) == 1
    assert "docs/deployment-embedding-scaling.md" in warnings[0]
    assert "shared HTTP embedding endpoint" in warnings[0]

    _get_fastembed_model.cache_clear()
