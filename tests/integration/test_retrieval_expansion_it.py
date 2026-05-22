"""Integration: retrieval_expansion / alias_map change WHICH chunks are retrieved.

Proves via rank comparison that:
1. retrieval_alias_map bridges a geographic term gap — without the alias the
   target doc does NOT rank first; with it, it does.
2. retrieval_expansion="moderate" bridges a synonym gap — without expansion
   the target doc does NOT rank first; with WordNet synonyms it does.

Strategy
--------
With mode="naive" on a 3-doc corpus, top_k=10 returns all 3 chunks on every
query, so set-difference assertions are meaningless.  We assert on RANK
(chunks[0].document_source) instead — a binding guarantee that the feature
actually changes scoring, not just membership.

We zero out w_sem so that BM25 is the sole ranking signal and the feature
under test is the unambiguous causal lever.  At w_sem=0.0, the embedding
is embedded in the SQL but multiplied by zero, making the score purely:

    score = w_bm25 * ts_rank(search_vector, tsquery)

Corpus design is deliberately discriminating:
  - Alias test: without the alias, the query's key term ("Brooklyn") matches
    only the competitor doc; the alias adds multiple terms ("Kings County",
    "civic center", etc.) that all appear in the target doc, flipping rank.
  - Synonym test: without expansion, the query term ("motorcar") appears in
    neither doc literally; the competitor wins on two other shared terms.
    With moderate expansion, "automobile" / "auto" / "car" are added to the
    tsquery; all three appear in the target doc, flipping rank.
"""

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
    pytest.mark.skipif(not _deps(), reason="lede/lede-spacy/en_core_web_sm not available"),
]

# ---------------------------------------------------------------------------
# Corpus A — alias_map proof
#
# Query: "Brooklyn information request"
#   tsquery without alias: "brooklyn | information | request"
#     mh.txt: has "brooklyn" + "information" + "request" → 3 hits → wins
#     kc.txt: has "kings county civic center public services administrative" → 0 hits
#   tsquery with alias Brooklyn->["Kings County","civic center","public services","admin"]:
#     brooklyn|information|request|kings|county|civic|center|public|services|admin
#     kc.txt: matches "kings county civic center public services administrative" → 6 hits → wins
#     mh.txt: "brooklyn information request" → 3 hits, but ts_rank penalises it
#             relative to the longer tsquery (denominator grows) → drops below kc.txt
# ---------------------------------------------------------------------------
_ALIAS_CORPUS = [
    {
        "text": (
            "Kings County civic center provides public services and administrative "
            "support for all county residents."
        ),
        "source_id": "kc.txt",
    },
    {
        "text": (
            "Brooklyn community hub offers information and local request "
            "processing to neighbourhood residents."
        ),
        "source_id": "mh.txt",
    },
    {
        "text": "The quarterly financial audit revealed areas requiring improvement this year.",
        "source_id": "noise.txt",
    },
]

# ---------------------------------------------------------------------------
# Corpus B — synonym expansion proof
#
# Query: "motorcar inspection fee schedule"
#   tsquery without expansion: "motorcar | inspection | fee | schedule"
#     comp.txt: "Inspection procedures … fee schedule … city services" → 3 hits → wins
#     auto.txt: "Automobile auto car registration and fee schedule …" → 2 hits
#   tsquery with moderate expansion: adds "automobile | auto | car" (motorcar synonyms)
#     auto.txt: "automobile" + "auto" + "car" + "fee" + "schedule" → 5 matches → wins
#     comp.txt: "inspection" + "fee" + "schedule" → 3 matches, but ts_rank now lower
#               because the full tsquery is longer (more terms, same doc coverage)
# ---------------------------------------------------------------------------
_SYNONYM_CORPUS = [
    {
        "text": (
            "Automobile auto car registration and fee schedule for all new "
            "vehicle owners in the county."
        ),
        "source_id": "auto.txt",
    },
    {
        "text": (
            "Inspection procedures follow a strict fee schedule for all "
            "city services rendered to the public."
        ),
        "source_id": "comp.txt",
    },
    {
        "text": "Library membership renewal is available online or at any branch location.",
        "source_id": "noise.txt",
    },
]


@pytest.fixture
async def alias_rag():
    """GraphRAG loaded with the alias-test corpus, pure-BM25 weights."""
    ns = "test_retr_alias"
    g = GraphRAG(dsn=_DSN, namespace=ns, fact_extractor="lede_spacy", llm_base_url="")
    await g.connect()
    await g.delete(ns)
    await g.ingest_records(_ALIAS_CORPUS, namespace=ns)
    # Zero semantic weight → BM25 is the sole ranking signal.
    # This isolates the alias_map as the causal lever.
    g.config.w_sem = 0.0
    g.config.w_bm25 = 1.0
    g._ns = ns
    try:
        yield g
    finally:
        await g.delete(ns)
        await g.close()


@pytest.fixture
async def synonym_rag():
    """GraphRAG loaded with the synonym-test corpus, pure-BM25 weights."""
    ns = "test_retr_synonym"
    g = GraphRAG(dsn=_DSN, namespace=ns, fact_extractor="lede_spacy", llm_base_url="")
    await g.connect()
    await g.delete(ns)
    await g.ingest_records(_SYNONYM_CORPUS, namespace=ns)
    g.config.w_sem = 0.0
    g.config.w_bm25 = 1.0
    g._ns = ns
    try:
        yield g
    finally:
        await g.delete(ns)
        await g.close()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_alias_map_bridges_geographic_gap(alias_rag):
    """retrieval_alias_map flips the top-ranked chunk from mh.txt to kc.txt.

    Mechanism: "Brooklyn" → ["Kings County", "civic center", "public services",
    "administrative"] adds six BM25-matchable tokens to the tsquery that all
    appear in kc.txt, giving it a higher ts_rank than mh.txt under the
    expanded query.

    Proof: rank comparison under pure BM25 (w_sem=0.0).
    """
    rag = alias_rag
    query = "Brooklyn information request"
    alias_map = {"Brooklyn": ["Kings County", "civic center", "public services", "administrative"]}

    # Baseline — no alias
    rag.config.retrieval_alias_map = {}
    without = await rag.query(query, mode="naive", namespace=rag._ns)

    # With alias
    rag.config.retrieval_alias_map = alias_map
    with_alias = await rag.query(query, mode="naive", namespace=rag._ns)

    # kc.txt must be top-ranked WITH alias ON
    assert with_alias.chunks, "alias query returned no chunks"
    assert with_alias.chunks[0].document_source == "kc.txt", (
        f"Expected kc.txt at rank 0 with alias ON, "
        f"got {with_alias.chunks[0].document_source!r}. "
        f"Full ranking: {[c.document_source for c in with_alias.chunks]}"
    )

    # kc.txt must NOT be top-ranked with alias OFF (mh.txt wins on 'brooklyn')
    assert without.chunks, "baseline query returned no chunks"
    assert without.chunks[0].document_source != "kc.txt", (
        f"kc.txt ranked first even WITHOUT alias — BM25 signal not discriminating. "
        f"Full ranking: {[c.document_source for c in without.chunks]}"
    )


async def test_synonym_expansion_changes_top_rank(synonym_rag):
    """retrieval_expansion='moderate' flips the top-ranked chunk from comp.txt to auto.txt.

    Mechanism: lede_spacy's WordNet synonyms expand "motorcar" to "automobile",
    "auto", "car".  All three appear in auto.txt; none in comp.txt.  Adding them
    to the OR-tsquery gives auto.txt a higher ts_rank than comp.txt (which only
    matches on "inspection", "fee", "schedule" from the original terms).

    Proof: rank comparison under pure BM25 (w_sem=0.0).
    """
    rag = synonym_rag
    query = "motorcar inspection fee schedule"

    # Baseline — no expansion
    rag.config.retrieval_expansion = "off"
    base = await rag.query(query, mode="naive", namespace=rag._ns)

    # Expanded — moderate tier: lemma + WordNet synonyms
    rag.config.retrieval_expansion = "moderate"
    expanded = await rag.query(query, mode="naive", namespace=rag._ns)

    # auto.txt must be top-ranked WITH expansion ON
    assert expanded.chunks, "expansion query returned no chunks"
    assert expanded.chunks[0].document_source == "auto.txt", (
        f"Expected auto.txt at rank 0 with expansion='moderate', "
        f"got {expanded.chunks[0].document_source!r}. "
        f"Full ranking: {[c.document_source for c in expanded.chunks]}. "
        f"Check that 'automobile'/'auto'/'car' were added to the tsquery via motorcar synonyms."
    )

    # auto.txt must NOT be top-ranked with expansion OFF
    assert base.chunks, "baseline query returned no chunks"
    assert base.chunks[0].document_source != "auto.txt", (
        f"auto.txt ranked first even WITHOUT expansion — corpus not discriminating enough. "
        f"Full ranking: {[c.document_source for c in base.chunks]}"
    )
