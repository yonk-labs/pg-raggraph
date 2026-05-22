"""Integration tests for mode='summary' (requires Postgres on 5434)."""

from __future__ import annotations

import time as _time

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


async def test_summary_base_mode_selects_substrate(rag):
    summ = await rag.query(
        "county taxes", mode="summary", summary_base_mode="naive", namespace=rag._test_ns
    )
    naive = await rag.query("county taxes", mode="naive", namespace=rag._test_ns)
    # SC-001b: summary substrate == the named base mode's chunk set
    assert [c.chunk_id for c in summ.chunks] == [c.chunk_id for c in naive.chunks]


async def test_smart_tier0_populates_summary_above_threshold(rag):
    rag.config.smart_summary_tier = True
    rag.config.summary_tier_threshold = 0.0  # force tier-0 on any high-confidence hit
    rag.config.boost_confidence_threshold = 0.0  # make naive top score "high"
    result = await rag.query(
        "What county does John Smith live in?",
        mode="smart",
        namespace=rag._test_ns,
    )
    assert result.query_mode == "smart[summary]"  # SC-006
    assert result.summary


async def test_smart_tier0_off_by_default(rag):
    result = await rag.query(
        "What county does John Smith live in?",
        mode="smart",
        namespace=rag._test_ns,
    )
    # Default config.smart_summary_tier is False — no summary path.
    assert result.query_mode != "smart[summary]"


async def test_summary_is_deterministic_across_runs(rag):
    q = "What county does John Smith live in?"
    r1 = await rag.query(q, mode="summary", namespace=rag._test_ns)
    r2 = await rag.query(q, mode="summary", namespace=rag._test_ns)
    assert r1.summary == r2.summary  # SC-004: byte-identical across runs


async def test_summary_with_expansion_off_is_deterministic(rag):
    rag.config.query_expansion = "off"
    q = "county taxes"
    r1 = await rag.query(q, mode="summary", namespace=rag._test_ns)
    r2 = await rag.query(q, mode="summary", namespace=rag._test_ns)
    assert r1.summary == r2.summary  # SC-004: no-expansion path is stable
    assert r1.summary


async def test_summary_mode_latency_budget(rag):
    q = "What county does John Smith live in?"
    await rag.query(q, mode="summary", namespace=rag._test_ns)  # warm caches
    start = _time.perf_counter()
    await rag.query(q, mode="summary", namespace=rag._test_ns)
    elapsed_ms = (_time.perf_counter() - start) * 1000
    # SC-010: loose budget on the dev machine; not a hard prod SLA.
    assert elapsed_ms < 250, f"summary mode took {elapsed_ms:.0f}ms (budget 250ms)"
