"""Integration tests for the BM25 lexical backend (issue #96).

Requires PG on :5434 (override with PGRG_TEST_DSN). Covers: identifier
lexemes surviving tokenization, incremental stats maintenance across
insert / update / delete (document-cascade path included), rebuild
equivalence, and the acceptance case — an exact-identifier question ranks
the defining chunk first under BM25 while IDF-less ts_rank lets tf-heavy
prose outrank it.
"""

from __future__ import annotations

import os
import uuid

import pytest

from pg_raggraph import GraphRAG
from pg_raggraph.config import PGRGConfig
from pg_raggraph.lexical import lexical_score_sql
from pg_raggraph.retrieval import _to_or_tsquery

pytestmark = pytest.mark.integration

DSN = os.environ.get("PGRG_TEST_DSN", "postgresql://postgres:postgres@localhost:5434/pg_raggraph")
NS = "test_bm25_lexical"

QUESTION = "how does validate_billing_archive work"

CODE_CHUNK = (
    "def validate_billing_archive(records):\n"
    '    """Check every record before the archive rollover."""\n'
    "    return all(r.ok for r in records)"
)
# tf-heavy prose over the question's common terms — exactly the chunks an
# IDF-less lexical leg over-ranks.
PROSE_CHUNKS = [
    "The billing team does valid work. Work on billing is careful work, and the work is valid.",
    "How the billing work is organized: valid billing records make the work easier for the team.",
    "Valid work on billing needs more billing work every quarter, and the work never stops.",
    "Some unrelated notes about gardening, the weather, and a long walk in the park.",
]


async def _recomputed_stats(db, ns):
    """Ground truth recomputed directly from chunks — what the incremental
    tables must always equal."""
    lex = await db.fetch_all(
        """
        SELECT t.lexeme, count(*) AS df
        FROM chunks c
        JOIN documents d ON d.id = c.document_id
        CROSS JOIN LATERAL unnest(c.search_vector) t
        WHERE d.namespace = %s
        GROUP BY t.lexeme
        ORDER BY t.lexeme
        """,
        (ns,),
    )
    corpus = await db.fetch_one(
        """
        SELECT count(c.id) AS chunk_count,
               COALESCE(sum(pgrg_lexeme_len(c.search_vector)), 0) AS total_len
        FROM chunks c
        JOIN documents d ON d.id = c.document_id
        WHERE d.namespace = %s
        """,
        (ns,),
    )
    return {(r["lexeme"]): r["df"] for r in lex}, corpus


async def _stored_stats(db, ns):
    lex = await db.fetch_all(
        "SELECT lexeme, df FROM lexeme_stats WHERE namespace = %s AND df > 0 ORDER BY lexeme",
        (ns,),
    )
    corpus = await db.fetch_one(
        "SELECT chunk_count, total_len FROM lexical_corpus_stats WHERE namespace = %s",
        (ns,),
    )
    return {r["lexeme"]: r["df"] for r in lex}, corpus


async def _assert_stats_consistent(db, ns):
    want_lex, want_corpus = await _recomputed_stats(db, ns)
    got_lex, got_corpus = await _stored_stats(db, ns)
    assert got_lex == want_lex
    if want_corpus["chunk_count"] == 0:
        assert got_corpus is None or got_corpus["chunk_count"] == 0
    else:
        assert got_corpus is not None
        assert got_corpus["chunk_count"] == want_corpus["chunk_count"]
        assert got_corpus["total_len"] == want_corpus["total_len"]


@pytest.fixture
async def seeded_rag():
    """Namespace with one code doc + one prose doc, embeddings included."""
    rag = GraphRAG(dsn=DSN, namespace=NS)
    await rag.connect()
    await rag.delete(NS)

    from pg_raggraph.embedding import get_embedding_provider

    embedder = get_embedding_provider(rag.config)
    texts = [CODE_CHUNK] + PROSE_CHUNKS
    embeddings = await embedder.embed(texts)

    code_doc = await rag.db.insert_returning_id(
        "INSERT INTO documents (namespace, content_hash, source_path) "
        "VALUES (%s, %s, %s) RETURNING id",
        (NS, uuid.uuid4().hex, "src/billing.py"),
    )
    prose_doc = await rag.db.insert_returning_id(
        "INSERT INTO documents (namespace, content_hash, source_path) "
        "VALUES (%s, %s, %s) RETURNING id",
        (NS, uuid.uuid4().hex, "docs/billing.md"),
    )
    chunk_ids = []
    for i, text in enumerate(texts):
        doc = code_doc if i == 0 else prose_doc
        cid = await rag.db.insert_returning_id(
            "INSERT INTO chunks (document_id, content, embedding, token_count) "
            "VALUES (%s, %s, %s, %s) RETURNING id",
            (doc, text, embeddings[i], len(text.split())),
        )
        chunk_ids.append(cid)

    try:
        yield rag, code_doc, prose_doc, chunk_ids
    finally:
        await rag.delete(NS)
        await rag.close()


async def _lexical_leg_scores(db, cfg: PGRGConfig, question: str) -> list[dict]:
    """Score every chunk in the namespace by the configured lexical leg only
    — no embedding noise, pure backend comparison."""
    sql = (
        f"SELECT c.id, c.content, {lexical_score_sql(cfg, 'c')} AS s "
        "FROM chunks c JOIN documents d ON d.id = c.document_id "
        "WHERE d.namespace = %(namespace)s ORDER BY s DESC, c.id"
    )
    return await db.fetch_all(
        sql,
        {
            "namespace": NS,
            "query": question,
            "tsquery": _to_or_tsquery(question),
            "bm25_k1": cfg.bm25_k1,
            "bm25_b": cfg.bm25_b,
        },
    )


@pytest.mark.asyncio
async def test_identifier_survives_tokenization(seeded_rag):
    """'validate_billing_archive' must be a searchable lexeme on the code
    chunk (the parser splits underscores; migration 016 re-injects the whole
    identifier) and absent from prose that merely says valid/billing."""
    rag, _, _, chunk_ids = seeded_rag
    rows = await rag.db.fetch_all(
        "SELECT id, search_vector @@ 'validate_billing_archive'::tsquery AS hit "
        "FROM chunks WHERE id = ANY(%s) ORDER BY id",
        (chunk_ids,),
    )
    hits = {r["id"]: r["hit"] for r in rows}
    assert hits[chunk_ids[0]] is True
    assert all(hits[cid] is False for cid in chunk_ids[1:])


@pytest.mark.asyncio
async def test_stats_maintained_incrementally(seeded_rag):
    """After plain INSERTs the trigger-maintained stats equal a from-scratch
    recount; then update / direct chunk delete / document-cascade delete all
    keep them exact (the delete path DECREMENTS — no drift by design)."""
    rag, code_doc, prose_doc, chunk_ids = seeded_rag
    db = rag.db
    await _assert_stats_consistent(db, NS)

    # UPDATE path: content change regenerates search_vector + stats.
    await db.execute(
        "UPDATE chunks SET content = %s WHERE id = %s",
        ("Completely different words about lighthouses.", chunk_ids[-1]),
    )
    await _assert_stats_consistent(db, NS)

    # Direct chunk delete (documents row still present).
    await db.execute("DELETE FROM chunks WHERE id = %s", (chunk_ids[1],))
    await _assert_stats_consistent(db, NS)

    # Document delete → FK cascade to chunks (the path where the chunk-level
    # trigger cannot see the namespace; documents trigger covers it).
    await rag.delete_document("docs/billing.md", NS)
    await _assert_stats_consistent(db, NS)

    # Namespace wipe.
    await rag.delete(NS)
    await _assert_stats_consistent(db, NS)


@pytest.mark.asyncio
async def test_rebuild_matches_incremental(seeded_rag):
    """rag.rebuild_lexical_stats() must reproduce exactly what the triggers
    maintained incrementally (the backfill story for pre-016 corpora)."""
    rag, *_ = seeded_rag
    before_lex, before_corpus = await _stored_stats(rag.db, NS)
    # Simulate a pre-016 corpus: stats missing while chunks exist.
    await rag.db.execute("DELETE FROM lexeme_stats WHERE namespace = %s", (NS,))
    await rag.db.execute("DELETE FROM lexical_corpus_stats WHERE namespace = %s", (NS,))

    result = await rag.rebuild_lexical_stats(NS)
    assert result["chunks"] == before_corpus["chunk_count"]

    after_lex, after_corpus = await _stored_stats(rag.db, NS)
    assert after_lex == before_lex
    assert after_corpus == before_corpus


@pytest.mark.asyncio
async def test_bm25_leg_wins_identifier_query_ts_rank_loses(seeded_rag):
    """Acceptance (#96): on an exact-identifier question, the BM25 leg ranks
    the defining chunk first with clear separation. The IDF-less ts_rank leg
    lets tf-heavy prose match it or beat it — the documented defect."""
    rag, _, _, chunk_ids = seeded_rag
    code_id = chunk_ids[0]

    bm25 = await _lexical_leg_scores(rag.db, PGRGConfig(lexical_backend="bm25"), QUESTION)
    assert bm25[0]["id"] == code_id
    runner_up = bm25[1]["s"]
    assert bm25[0]["s"] > 1.5 * runner_up  # rare-identifier IDF dominates

    ts = await _lexical_leg_scores(rag.db, PGRGConfig(), QUESTION)
    ts_by_id = {r["id"]: r["s"] for r in ts}
    best_prose = max(s for cid, s in ts_by_id.items() if cid != code_id)
    # ts_rank gives the code chunk no rare-term advantage: prose matches it
    # or beats it (no 1.5x separation like BM25 achieves above).
    assert ts_by_id[code_id] <= 1.5 * best_prose


@pytest.mark.asyncio
async def test_full_query_bm25_rrf_ranks_code_chunk_first(seeded_rag):
    """End-to-end acceptance: naive mode with lexical_backend='bm25' under
    the default rrf fusion returns the defining chunk first."""
    _, _, _, chunk_ids = seeded_rag
    rag = GraphRAG(dsn=DSN, namespace=NS, lexical_backend="bm25")
    await rag.connect()
    try:
        result = await rag.query(QUESTION, mode="naive")
        assert result.chunks, "expected results"
        assert result.chunks[0].chunk_id == chunk_ids[0]
    finally:
        await rag.close()


@pytest.mark.asyncio
async def test_full_query_bm25_linear_still_works(seeded_rag):
    """The linear fusion path stays available for A/B with the bm25 backend
    (scores are unbounded — this only asserts the SQL executes and returns)."""
    _, _, _, chunk_ids = seeded_rag
    rag = GraphRAG(dsn=DSN, namespace=NS, lexical_backend="bm25", fusion="linear")
    await rag.connect()
    try:
        result = await rag.query(QUESTION, mode="naive")
        assert result.chunks
    finally:
        await rag.close()
