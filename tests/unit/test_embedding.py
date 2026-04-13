"""Tests for embedding module (mocked — no model download in unit tests)."""

import pytest

from pg_raggraph.embedding import EmbeddingProvider


class MockEmbeddingProvider:
    """Mock embedding provider for testing."""

    def __init__(self, dim: int = 384):
        self._dim = dim

    @property
    def dimension(self) -> int:
        return self._dim

    async def embed(self, texts: list[str]) -> list[list[float]]:
        # Return deterministic fake embeddings based on text length
        return [[float(len(t) % 10) / 10.0] * self._dim for t in texts]


def test_mock_provider_implements_protocol():
    provider = MockEmbeddingProvider(384)
    assert isinstance(provider, EmbeddingProvider)


@pytest.mark.asyncio
async def test_mock_embed_returns_correct_dimensions():
    provider = MockEmbeddingProvider(384)
    results = await provider.embed(["hello", "world"])
    assert len(results) == 2
    assert len(results[0]) == 384
    assert len(results[1]) == 384


@pytest.mark.asyncio
async def test_mock_embed_empty_list():
    provider = MockEmbeddingProvider(384)
    results = await provider.embed([])
    assert results == []


def test_dimension_property():
    p384 = MockEmbeddingProvider(384)
    p768 = MockEmbeddingProvider(768)
    assert p384.dimension == 384
    assert p768.dimension == 768
