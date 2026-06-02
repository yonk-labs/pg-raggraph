"""Integration tests for RRF fusion (issue #57). Requires PG on :5434."""

import pytest

from pg_raggraph import GraphRAG

pytestmark = pytest.mark.integration

TEST_DSN = "postgresql://postgres:postgres@localhost:5434/pg_raggraph"


@pytest.fixture
async def seeded_rag():
    """GraphRAG with pre-seeded chunks/entities/relationships (no LLM needed).

    Self-contained copy adapted from tests/integration/test_retrieval.py so the
    RRF integration tests do not depend on a fixture defined in another module.
    """
    rag = GraphRAG(dsn=TEST_DSN, namespace="test_rrf_fusion")
    await rag.connect()

    from pg_raggraph.embedding import get_embedding_provider

    embedder = get_embedding_provider(rag.config)
    ns = "test_rrf_fusion"

    doc_id = await rag.db.insert_returning_id(
        "INSERT INTO documents (namespace, content_hash, source_path) "
        "VALUES (%s, %s, %s) RETURNING id",
        (ns, "test_hash_rrf", "test/rrf.md"),
    )

    chunk_texts = [
        "PostgreSQL is a powerful open source database with pgvector for vector search.",
        "LightRAG uses dual-level retrieval with entity and topic keywords.",
        "Microsoft GraphRAG costs $33,000 for large datasets due to community summaries.",
        "Apache AGE was rejected because it only works on Azure managed PostgreSQL.",
    ]
    embeddings = await embedder.embed(chunk_texts)
    chunk_ids = []
    for text, emb in zip(chunk_texts, embeddings):
        cid = await rag.db.insert_returning_id(
            "INSERT INTO chunks (document_id, content, embedding, token_count) "
            "VALUES (%s, %s, %s, %s) RETURNING id",
            (doc_id, text, emb, len(text.split())),
        )
        chunk_ids.append(cid)

    entity_data = [
        ("PostgreSQL", "technology", "Open source relational database"),
        ("LightRAG", "technology", "Lightweight GraphRAG framework"),
        ("Microsoft GraphRAG", "technology", "Original GraphRAG implementation"),
        ("pgvector", "technology", "Vector similarity search for PostgreSQL"),
    ]
    entity_ids = {}
    for name, etype, desc in entity_data:
        emb = (await embedder.embed([f"{name} {desc}"]))[0]
        eid = await rag.db.insert_returning_id(
            "INSERT INTO entities (namespace, name, entity_type, description, embedding) "
            "VALUES (%s, %s, %s, %s, %s) RETURNING id",
            (ns, name, etype, desc, emb),
        )
        entity_ids[name] = eid

    rels = [
        ("PostgreSQL", "pgvector", "HAS_EXTENSION", "pgvector extends PostgreSQL"),
        ("LightRAG", "PostgreSQL", "USES", "LightRAG has a PostgreSQL backend"),
        ("Microsoft GraphRAG", "LightRAG", "INSPIRED", "LightRAG is an alternative"),
    ]
    for src, dst, rtype, desc in rels:
        rid = await rag.db.insert_returning_id(
            "INSERT INTO relationships (namespace, src_id, dst_id, rel_type, description) "
            "VALUES (%s, %s, %s, %s, %s) RETURNING id",
            (ns, entity_ids[src], entity_ids[dst], rtype, desc),
        )
        await rag.db.execute(
            "INSERT INTO relationship_chunks (relationship_id, chunk_id) "
            "VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (rid, chunk_ids[0]),
        )

    entity_chunk_map = {
        "PostgreSQL": [0, 3],
        "LightRAG": [1],
        "Microsoft GraphRAG": [2],
        "pgvector": [0],
    }
    for ename, cidxs in entity_chunk_map.items():
        for cidx in cidxs:
            await rag.db.execute(
                "INSERT INTO entity_chunks (entity_id, chunk_id) "
                "VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (entity_ids[ename], chunk_ids[cidx]),
            )

    yield rag

    await rag.delete("test_rrf_fusion")
    await rag.close()


@pytest.fixture
async def seeded_rag_evolution():
    """GraphRAG with evolution_tier='structural' on a distinct namespace.

    Proves the RRF outer SELECT keeps d.effective_from / d.created_at in scope
    when the evolution re-join is active (SC-005).
    """
    rag = GraphRAG(dsn=TEST_DSN, namespace="test_rrf_evolution", evolution_tier="structural")
    await rag.connect()

    from pg_raggraph.embedding import get_embedding_provider

    embedder = get_embedding_provider(rag.config)
    ns = "test_rrf_evolution"

    doc_id = await rag.db.insert_returning_id(
        "INSERT INTO documents (namespace, content_hash, source_path) "
        "VALUES (%s, %s, %s) RETURNING id",
        (ns, "test_hash_rrf_evo", "test/rrf_evo.md"),
    )

    chunk_texts = [
        "On 2024-01-01 the policy rate was set to 5 percent, a dated fact.",
        "The migration completed and the dated fact about the rate changed.",
    ]
    embeddings = await embedder.embed(chunk_texts)
    for text, emb in zip(chunk_texts, embeddings):
        await rag.db.insert_returning_id(
            "INSERT INTO chunks (document_id, content, embedding, token_count) "
            "VALUES (%s, %s, %s, %s) RETURNING id",
            (doc_id, text, emb, len(text.split())),
        )

    yield rag

    await rag.delete("test_rrf_evolution")
    await rag.close()


async def test_naive_rrf_runs_via_public_api(seeded_rag):
    """SC-002/SC-003: naive RRF runs end-to-end through the public override."""
    rag = seeded_rag
    linear = await rag.query("PostgreSQL vector search", mode="naive", fusion="linear")
    rrf = await rag.query("PostgreSQL vector search", mode="naive", fusion="rrf")
    assert linear.chunks
    assert rrf.chunks


async def test_hybrid_rrf_runs_via_public_api(seeded_rag):
    """SC-004: hybrid RRF path executes and returns ranked chunks."""
    res = await seeded_rag.query("GraphRAG frameworks", mode="hybrid", fusion="rrf")
    assert res.chunks
    assert all(c.score is not None for c in res.chunks)


async def test_ask_forwards_fusion(seeded_rag):
    """ask() forwards the fusion override down to retrieval without error."""
    res = await seeded_rag.ask("PostgreSQL vector search", mode="naive", fusion="rrf")
    assert res is not None


async def test_naive_rrf_with_evolution_on(seeded_rag_evolution):
    """SC-005: naive RRF executes under evolution_tier='structural'.

    Executing without a SQL error proves the d.effective_from / d.created_at
    columns from the evolution re-join resolve in the RRF outer SELECT.
    """
    res = await seeded_rag_evolution.query("a dated fact", mode="naive", fusion="rrf")
    assert res is not None  # executing without SQL error is the assertion


# --- Correctness tests (added after honest gap review) ---------------------
#
# The smoke tests above prove RRF *runs*. The three below prove it is
# *correct*: every naive RRF builder actually executes against Postgres
# (incl. pre_filter / vector_first, which no other test exercised), the
# single-pass RRF SQL computes the exact RRF formula, and the evolution
# re-join actually applies temporal decay (not just "doesn't crash").


@pytest.mark.parametrize("strategy", ["weighted", "pre_filter", "vector_first"])
async def test_naive_rrf_every_strategy_executes(seeded_rag, strategy):
    """Each retrieval_strategy drives a different naive RRF SQL builder.

    'weighted' + default two_stage=True -> two-stage builder; 'pre_filter' ->
    pre_filter builder; 'vector_first' -> vector_first builder. Before this,
    pre_filter and vector_first RRF SQL had NEVER touched Postgres — a syntax
    or column error in those f-strings would have shipped undetected.
    """
    res = await seeded_rag.query(
        "PostgreSQL pgvector database",
        mode="naive",
        fusion="rrf",
        retrieval_strategy=strategy,
    )
    assert res.chunks, f"strategy={strategy} returned no chunks"
    scores = [c.score for c in res.chunks]
    assert scores == sorted(scores, reverse=True), f"strategy={strategy} not ordered by score"


async def test_naive_rrf_single_pass_executes(seeded_rag):
    """The single-pass naive RRF builder (two_stage=False) executes.

    The default config uses two_stage=True, so without this the single-pass
    _build_naive_query_rrf SQL would only ever be unit-tested as a string.
    """
    seeded_rag.config.two_stage_retrieval = False
    res = await seeded_rag.query(
        "PostgreSQL pgvector database",
        mode="naive",
        fusion="rrf",
        retrieval_strategy="weighted",
    )
    assert res.chunks
    scores = [c.score for c in res.chunks]
    assert scores == sorted(scores, reverse=True)


async def test_naive_rrf_score_matches_formula(seeded_rag):
    """The naive RRF SQL computes score = w_sem/(k+vec_rank) + w_bm25/(k+bm25_rank).

    Execute the single-pass builder's SQL directly, recompute the SQL rank()
    values in Python from the returned per-leg scores (rank() = 1 + count of
    strictly-greater rows, which matches SQL tie semantics), and verify each
    row's fused score. The corpus (4 chunks) is smaller than top_k, so the
    returned set == the full scored set and the recomputed ranks are exact.
    """
    from pg_raggraph.embedding import get_embedding_provider
    from pg_raggraph.retrieval import _build_naive_query_rrf, _to_or_tsquery

    rag = seeded_rag
    cfg = rag.config
    cfg.two_stage_retrieval = False  # exercise the single-pass RRF builder
    q = "PostgreSQL pgvector database"
    embedder = get_embedding_provider(cfg)
    q_emb = (await embedder.embed([q]))[0]

    sql, extra = _build_naive_query_rrf(cfg)  # evolution_tier 'off' -> base only
    params = {
        "embedding": q_emb,
        "tsquery": _to_or_tsquery(q),
        "namespace": "test_rrf_fusion",
        "top_k": 50,
        "w_sem": cfg.w_sem,
        "w_bm25": cfg.w_bm25,
        "rrf_k": cfg.rrf_k,
        **extra,
    }
    rows = await rag.db.fetch_all(sql, params)
    assert rows, "RRF SQL returned no rows"

    def sql_rank(row, key):
        v = float(row[key])
        return 1 + sum(1 for o in rows if float(o[key]) > v)

    for row in rows:
        vec_rank = sql_rank(row, "vec_score")
        bm25_rank = sql_rank(row, "bm25_score")
        expected = cfg.w_sem / (cfg.rrf_k + vec_rank) + cfg.w_bm25 / (cfg.rrf_k + bm25_rank)
        assert abs(float(row["score"]) - expected) < 1e-6, (
            f"RRF score mismatch: got {row['score']}, expected {expected} "
            f"(vec_rank={vec_rank}, bm25_rank={bm25_rank})"
        )


@pytest.fixture
async def seeded_rag_evolution_dated():
    """Two documents with identical chunk content but different effective_from.

    Identical content -> identical embedding -> identical vec/bm25 -> identical
    RRF base. So any ranking difference is attributable solely to the temporal
    boost, which is exactly what we want to assert.
    """
    from datetime import datetime, timezone

    rag = GraphRAG(dsn=TEST_DSN, namespace="test_rrf_dated", evolution_tier="structural")
    await rag.connect()

    from pg_raggraph.embedding import get_embedding_provider

    embedder = get_embedding_provider(rag.config)
    ns = "test_rrf_dated"
    text = "The quarterly revenue figure for the reporting period under review."
    emb = (await embedder.embed([text]))[0]

    for label, eff in (
        ("old.md", datetime(2018, 1, 1, tzinfo=timezone.utc)),
        ("new.md", datetime(2025, 1, 1, tzinfo=timezone.utc)),
    ):
        doc_id = await rag.db.insert_returning_id(
            "INSERT INTO documents (namespace, content_hash, source_path, effective_from) "
            "VALUES (%s, %s, %s, %s) RETURNING id",
            (ns, f"hash_{label}", label, eff),
        )
        await rag.db.insert_returning_id(
            "INSERT INTO chunks (document_id, content, embedding, token_count) "
            "VALUES (%s, %s, %s, %s) RETURNING id",
            (doc_id, text, emb, len(text.split())),
        )

    yield rag

    await rag.delete("test_rrf_dated")
    await rag.close()


async def test_naive_rrf_evolution_applies_temporal_decay(seeded_rag_evolution_dated):
    """Correctness for the locked design decision: RRF ranks the base legs,
    then evolution applies decay as an outer term.

    Two chunks with identical content (identical RRF base) but different
    effective_from must reorder by recency — proving the temporal boost is
    actually applied on top of the RRF score, not merely that the query runs.
    """
    rag = seeded_rag_evolution_dated
    res = await rag.query(
        "quarterly revenue figure reporting period",
        mode="naive",
        fusion="rrf",
    )
    assert len(res.chunks) == 2, "expected both dated chunks"
    # Newer effective_from -> larger temporal boost -> higher fused score -> first.
    assert res.chunks[0].document_source == "new.md", (
        "evolution decay not applied under RRF: the newer chunk did not rank "
        f"first (got order: {[c.document_source for c in res.chunks]})"
    )
    assert res.chunks[0].score > res.chunks[1].score
