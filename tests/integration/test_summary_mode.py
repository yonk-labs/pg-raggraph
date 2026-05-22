"""Integration tests for mode='summary' (requires Postgres on 5434)."""

from __future__ import annotations

import pytest

from pg_raggraph import GraphRAG

_DSN = "postgresql://postgres:postgres@localhost:5434/pg_raggraph"

CORPUS = [
    {
        "text": "John Smith lives in Cook County. He runs a small business and pays county taxes.",
        "source_id": "smith.txt",
    },
    {
        "text": "Mary Jones lives in Lake County. She is a teacher and serves on the school board.",
        "source_id": "jones.txt",
    },
    {
        "text": "The county council approved the annual budget. Cook County raised property taxes by two percent.",
        "source_id": "budget.txt",
    },
]


def _deps_available() -> bool:
    try:
        import lede  # noqa: F401
        import lede_spacy  # noqa: F401
        import spacy

        spacy.load("en_core_web_sm")
        return True
    except Exception:
        return False


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not _deps_available(), reason="lede/lede-spacy/en_core_web_sm not available"
    ),
]


@pytest.fixture
async def rag():
    ns = "test_summary_mode"
    g = GraphRAG(dsn=_DSN, namespace=ns, fact_extractor="lede_spacy", llm_base_url="")
    await g.connect()
    await g.delete(ns)  # clear any leftover state from a prior run
    await g.ingest_records(CORPUS, namespace=ns)
    g._test_ns = ns
    try:
        yield g
    finally:
        await g.delete(ns)
        await g.close()


async def test_summary_mode_returns_nonempty_summary_with_citations(rag):
    result = await rag.query(
        "What county does John Smith live in?",
        mode="summary",
        namespace=rag._test_ns,
    )
    assert result.query_mode == "summary"
    assert result.summary  # SC-001: non-empty summary
    assert result.chunks  # SC-001: chunks preserved
    assert all(c.document_source for c in result.chunks)  # source attribution
