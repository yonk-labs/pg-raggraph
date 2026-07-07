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


_PROSE_DOCS = [
    {
        "text": (
            "Greta Reyes said she has been craving gumbo lately. "
            "She chatted with Marcus about fantasy football."
        ),
        "source_id": "chat:greta",
    },
    {
        "text": (
            "The seafood gumbo at Bayou Belle in New Orleans is incredible. "
            "Bayou Belle serves classic Cajun dishes."
        ),
        "source_id": "review:bayou",
    },
]


async def _edge_pairs(rag, ns):
    rows = await rag.db.fetch_all(
        "SELECT e1.name AS src, e2.name AS dst, r.rel_type "
        "FROM relationships r JOIN entities e1 ON e1.id = r.src_id "
        "JOIN entities e2 ON e2.id = r.dst_id WHERE r.namespace = %s",
        (ns,),
    )
    return {frozenset((r["src"], r["dst"])) for r in rows}, {r["rel_type"] for r in rows}


@pytest.mark.skipif(
    not _model_available(),
    reason="lede / lede-spacy / en_core_web_sm not available",
)
async def test_lede_prose_ingest_builds_join_path_without_llm():
    """lede_prose lifts common-noun entities and links the multi-hop join path
    (person—craving, dish—venue, venue—city) with head-lemma canonicalization
    ("The seafood gumbo" lands on node "gumbo")."""
    ns = "test_lede_prose_it"
    rag = GraphRAG(dsn=_DSN, namespace=ns, fact_extractor="lede_prose", llm_base_url="")
    await rag.connect()
    try:
        await rag.ingest_records(_PROSE_DOCS, namespace=ns)
        names = {
            r["name"]
            for r in await rag.db.fetch_all("SELECT name FROM entities WHERE namespace=%s", (ns,))
        }
        assert {"Greta Reyes", "gumbo", "Bayou Belle", "New Orleans"} <= names, names
        assert "seafood gumbo" not in names  # canonicalized onto "gumbo"
        pairs, _ = await _edge_pairs(rag, ns)
        assert frozenset(("Greta Reyes", "gumbo")) in pairs
        assert frozenset(("gumbo", "Bayou Belle")) in pairs
        assert frozenset(("Bayou Belle", "New Orleans")) in pairs
    finally:
        await rag.delete(ns)
        await rag.close()


class _FakeLLM:
    """Typed extraction for any chunk; JSON-mode response shape."""

    async def complete(self, messages):
        import json

        return json.dumps(
            {
                "entities": [
                    {"name": "Greta Reyes", "entity_type": "person", "description": ""},
                    {"name": "Gumbo", "entity_type": "food", "description": "a stew"},
                ],
                "relationships": [
                    {
                        "source": "Greta Reyes",
                        "target": "Gumbo",
                        "rel_type": "LIKES",
                        "description": "craving gumbo",
                        "weight": 0.9,
                    }
                ],
            }
        )

    async def complete_text(self, messages, temperature=0.2):
        return "ok"

    async def aclose(self):
        pass


@pytest.mark.skipif(
    not _model_available(),
    reason="lede / lede-spacy / en_core_web_sm not available",
)
async def test_llm_lede_union_deferred_drain():
    """llm+lede through the deferred path: ingest defers, the backfill drain
    runs the union — typed LLM edges AND the deterministic co-occurrence net
    land, and all docs flip to ready."""
    from pg_raggraph.backfill import claim_pending, extract_documents

    ns = "test_union_drain_it"
    rag = GraphRAG(
        dsn=_DSN, namespace=ns, fact_extractor="llm+lede", llm_base_url="http://fake:1/v1"
    )
    rag._llm = _FakeLLM()  # injected so the drain never dials the fake URL
    await rag.connect()
    try:
        # The extraction cache keys on chunk content + prompt name, not on the
        # provider — wipe it so a prior run's fake-LLM response can't shadow
        # this run's _FakeLLM output.
        await rag.db.execute("DELETE FROM pgrg_llm_cache")
        await rag.ingest_records(_PROSE_DOCS, namespace=ns, defer_extraction=True)
        ent = await rag.db.fetch_one(
            "SELECT COUNT(*) AS n FROM entities WHERE namespace=%s", (ns,)
        )
        assert ent["n"] == 0, "deferred ingest must not extract synchronously"

        doc_ids = await claim_pending(rag.db, ns, 10)
        stats = await extract_documents(rag, doc_ids, namespace=ns)
        assert stats.failed == 0, stats.errors
        assert stats.ready == len(_PROSE_DOCS)

        _, rel_types = await _edge_pairs(rag, ns)
        assert "LIKES" in rel_types, rel_types  # typed LLM edge
        assert "RELATED_TO" in rel_types, rel_types  # deterministic net
        statuses = {
            r["graph_status"]
            for r in await rag.db.fetch_all(
                "SELECT DISTINCT graph_status FROM documents WHERE namespace=%s", (ns,)
            )
        }
        assert statuses == {"ready"}, statuses
    finally:
        await rag.delete(ns)
        await rag.close()
