"""Tests for GraphRAG embedder cleanup on close."""

import pytest

from pg_raggraph import GraphRAG


class _PlainEmbedder:
    pass


class _ClosableEmbedder:
    def __init__(self):
        self.closed = False

    async def aclose(self):
        self.closed = True


@pytest.mark.asyncio
async def test_close_always_clears_embedder_without_aclose():
    rag = GraphRAG(skip_extraction=True)
    rag._embedder = _PlainEmbedder()

    await rag.close()

    assert rag._embedder is None


@pytest.mark.asyncio
async def test_close_closes_and_clears_embedder_with_aclose():
    rag = GraphRAG(skip_extraction=True)
    embedder = _ClosableEmbedder()
    rag._embedder = embedder

    await rag.close()

    assert embedder.closed is True
    assert rag._embedder is None
