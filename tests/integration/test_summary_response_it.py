"""Integration: ask(mode='summary') response shape + caching (SC-201..203)."""

from __future__ import annotations

import pytest

from pg_raggraph import GraphRAG

_DSN = "postgresql://postgres:postgres@localhost:5434/pg_raggraph"


def _deps() -> bool:
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
    pytest.mark.skipif(not _deps(), reason="deps not available"),
]

CORPUS = [
    {"text": "John Smith lives in Cook County and pays county taxes.", "source_id": "a.txt"},
    {"text": "The county council raised property taxes by two percent.", "source_id": "b.txt"},
]


@pytest.fixture
async def rag():
    ns = "test_summary_response"
    g = GraphRAG(dsn=_DSN, namespace=ns, fact_extractor="lede_spacy", llm_base_url="")
    await g.connect()
    await g.delete(ns)
    await g.ingest_records(CORPUS, namespace=ns)
    g._ns = ns
    try:
        yield g
    finally:
        await g.delete(ns)
        await g.close()


async def test_ask_summary_sets_answer_id_and_escalation(rag):
    res = await rag.ask("What county does John Smith live in?", mode="summary", namespace=rag._ns)
    assert res.answer
    assert res.summary and res.summary in res.answer
    assert res.result_id
    assert res.result_id in res.answer  # SC-203 affordance references the id


async def test_cached_result_returns_full_chunks(rag):
    res = await rag.ask("county taxes", mode="summary", namespace=rag._ns)
    cached = rag.get_cached_result(res.result_id)
    assert cached is not None
    assert [c.chunk_id for c in cached.chunks] == [c.chunk_id for c in res.chunks]


async def test_escalation_off_when_disabled(rag):
    rag.config.summary_escalation = False
    res = await rag.ask("county taxes", mode="summary", namespace=rag._ns)
    assert res.answer == res.summary  # no escalation line appended
