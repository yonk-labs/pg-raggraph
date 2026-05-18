"""Integration: fact_extractor='lede_spacy' builds a graph with no LLM."""

import pytest

from pg_raggraph import GraphRAG

_DSN = "postgresql://postgres:postgres@localhost:5434/pg_raggraph"

_DOC = (
    "# Apollo Program\n\n"
    "NASA launched the Saturn V rocket from Kennedy Space Center. "
    "Neil Armstrong and Buzz Aldrin walked on the Moon while Michael "
    "Collins orbited. Congress funded NASA throughout the decade."
)


def _model_available() -> bool:
    try:
        import lede  # noqa: F401
        import lede_spacy  # noqa: F401
        import spacy

        spacy.load("en_core_web_sm")
        return True
    except Exception:
        return False


@pytest.mark.skipif(
    not _model_available(),
    reason="lede / lede-spacy / en_core_web_sm not available",
)
async def test_lede_spacy_ingest_builds_graph_without_llm():
    ns = "test_lede_it"
    rag = GraphRAG(
        dsn=_DSN,
        namespace=ns,
        fact_extractor="lede_spacy",
        llm_base_url="",  # explicitly no LLM
    )
    await rag.connect()
    try:
        await rag.ingest_records([{"text": _DOC, "source_id": "apollo:1"}], namespace=ns)
        ent = await rag.db.fetch_one(
            "SELECT COUNT(*) AS n FROM entities WHERE namespace=%s", (ns,)
        )
        rel = await rag.db.fetch_one(
            "SELECT COUNT(*) AS n FROM relationships WHERE namespace=%s", (ns,)
        )
        assert ent["n"] > 0, "lede_spacy must populate entities without an LLM"
        assert rel["n"] > 0, "co-occurrence must populate relationships"
    finally:
        await rag.delete(ns)
        await rag.close()
