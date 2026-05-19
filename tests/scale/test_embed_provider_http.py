"""Tests for dedicated HTTP embedding provider configuration."""

import pytest

from pg_raggraph.config import PGRGConfig
from pg_raggraph.embedding import HttpxEmbeddingProvider, get_embedding_provider


def test_embed_provider_http():
    cfg = PGRGConfig(
        embedding_provider="http",
        embedding_base_url="http://embeddings.internal/v1",
        embedding_api_key="secret-token",
        embedding_model="BAAI/bge-small-en-v1.5",
        embedding_dim=384,
        llm_base_url="http://should-not-be-used:11434/v1",
        llm_api_key="llm-key-must-not-leak",
    )
    provider = get_embedding_provider(cfg)

    assert isinstance(provider, HttpxEmbeddingProvider)
    assert provider._base_url == "http://embeddings.internal/v1"
    assert provider._api_key == "secret-token"
    assert provider.dimension == 384


def test_embed_provider_http_requires_base_url():
    cfg = PGRGConfig(embedding_provider="http")
    with pytest.raises(ValueError, match="embedding_base_url"):
        get_embedding_provider(cfg)


def test_embed_provider_back_compat_ollama_unchanged():
    cfg = PGRGConfig(
        embedding_provider="ollama",
        llm_base_url="http://ollama.internal:11434/v1",
        embedding_dim=384,
    )
    provider = get_embedding_provider(cfg)

    assert isinstance(provider, HttpxEmbeddingProvider)
    assert provider._base_url == "http://ollama.internal:11434/v1"
