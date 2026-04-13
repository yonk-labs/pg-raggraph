"""Tests for config module."""

from pg_raggraph.config import PGRGConfig


def test_defaults():
    config = PGRGConfig()
    assert config.dsn == "postgresql://postgres:postgres@localhost:5434/pg_raggraph"
    assert config.namespace == "default"
    assert config.embedding_dim == 384
    assert config.max_hops == 2
    assert config.top_k == 10


def test_override():
    config = PGRGConfig(dsn="postgresql://other:5433/test", namespace="prod", embedding_dim=768)
    assert config.dsn == "postgresql://other:5433/test"
    assert config.namespace == "prod"
    assert config.embedding_dim == 768


def test_resolution_defaults():
    config = PGRGConfig()
    assert config.resolution_threshold == 0.85
    assert config.trgm_weight == 0.4
    assert config.vec_weight == 0.6
    assert abs(config.trgm_weight + config.vec_weight - 1.0) < 0.001
