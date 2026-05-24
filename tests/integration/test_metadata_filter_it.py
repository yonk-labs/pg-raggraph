"""Integration: soft metadata bias reorders; hard structured filter excludes."""

from __future__ import annotations

import pytest

from pg_raggraph import GraphRAG

_DSN = "postgresql://postgres:postgres@localhost:5434/pg_raggraph"
pytestmark = pytest.mark.integration

CORPUS = [
    {
        "text": "Quarterly revenue rose sharply this period.",
        "source_id": "fin1",
        "metadata": {"category": "finance", "source": "reports"},
    },
    {
        "text": "Quarterly revenue figures were reviewed by staff.",
        "source_id": "hr1",
        "metadata": {"category": "hr", "source": "memos"},
    },
]


@pytest.fixture
async def rag():
    ns = "test_meta_filter"
    g = GraphRAG(dsn=_DSN, namespace=ns, structured_metadata_fields=["source", "category"])
    await g.connect()
    await g.delete(ns)
    await g.ingest_records(CORPUS, namespace=ns)
    g._ns = ns
    try:
        yield g
    finally:
        await g.delete(ns)
        await g.close()


async def test_soft_bias_keeps_all_chunks(rag):
    res = await rag.query(
        "quarterly revenue",
        mode="naive",
        namespace=rag._ns,
        metadata_filters={"soft": {"category": "finance"}},
    )
    assert len(res.chunks) == 2  # SC-302: nothing excluded by a soft filter


async def test_hard_structured_filter_excludes(rag):
    res = await rag.query(
        "quarterly revenue",
        mode="naive",
        namespace=rag._ns,
        metadata_filters={"hard": {"source": "reports"}},
    )
    assert len(res.chunks) == 1  # SC-303: only the reports-source chunk survives


async def test_hard_filter_on_freetext_field_raises(rag):
    with pytest.raises(ValueError, match="not a structured field"):
        await rag.query(
            "revenue",
            mode="naive",
            namespace=rag._ns,
            metadata_filters={"hard": {"keywords": "finance"}},
        )


async def test_nested_json_metadata_generated_column_for_lede_report():
    ns = "test_meta_lede_generated"
    g = GraphRAG(
        dsn=_DSN,
        namespace=ns,
        skip_extraction=True,
        llm_base_url="",
        document_metadata_generated_columns={
            "lede_term": {
                "type": "text",
                "path": ["lede_report", "attributes", "term", "value"],
            }
        },
    )
    await g.connect()
    await g.delete(ns)
    try:
        await g.ingest_records(
            [
                {
                    "text": "The court decided a narrow administrative law question.",
                    "source_id": "scotus:term-test",
                    "metadata": {
                        "lede_report": {
                            "attributes": {
                                "term": {
                                    "value": "2023",
                                    "type": "year",
                                }
                            }
                        }
                    },
                    "skip_llm": True,
                }
            ],
            namespace=ns,
        )
        row = await g.db.fetch_one(
            "SELECT meta_lede_term FROM documents WHERE namespace = %s",
            (ns,),
        )
        assert row["meta_lede_term"] == "2023"
    finally:
        await g.delete(ns)
        await g.close()
