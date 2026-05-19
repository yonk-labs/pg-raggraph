# tests/scale/test_twostage_retrieval.py
from uuid import uuid4

import pytest

from pg_raggraph import GraphRAG  # noqa: F401  (fixture provides instance)
from pg_raggraph.config import PGRGConfig
from pg_raggraph.evolution import evolution_bind_params
from pg_raggraph.retrieval import (
    _build_naive_query,
    _build_naive_query_twostage,
    _merge_params,
    _to_or_tsquery,
    query,
)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_twostage_uses_hnsw_and_preserves_topk(scale_rag):
    rows = [{"text": f"doc {i} about topic {i % 7}", "source_id": f"t{i}"} for i in range(5000)]
    await scale_rag.ingest_records(rows, namespace="ts")

    r = await scale_rag.query("topic 3", mode="naive", namespace="ts")
    assert len(r.chunks) > 0

    # The two-stage candidate CTE's bare-distance ORDER BY must be
    # served by the HNSW index idx_chunk_embed. We bind the probe vector
    # as a real parameter (NOT a `(SELECT embedding FROM chunks LIMIT 1)`
    # sub-select — that seed itself Seq-Scans chunks and would pollute a
    # blanket "Seq Scan" assertion with a false negative).
    probe = await scale_rag.db.fetch_one(
        "SELECT embedding FROM chunks c "
        "JOIN documents d ON d.id = c.document_id "
        "WHERE d.namespace = %(ns)s AND c.embedding IS NOT NULL LIMIT 1",
        {"ns": "ts"},
    )
    plan = await scale_rag.db.fetch_all(
        "EXPLAIN SELECT c.id FROM chunks c "
        "JOIN documents d ON d.id = c.document_id "
        "WHERE d.namespace = %(ns)s "
        "ORDER BY c.embedding <=> %(q)s::vector "
        "LIMIT 200",
        {"ns": "ts", "q": probe["embedding"]},
    )
    plan_text = "\n".join(str(row) for row in plan)
    # The ordering path must walk the HNSW index, not Seq-Scan + Sort it.
    assert "idx_chunk_embed" in plan_text
    assert "Order By: (embedding <=>" in plan_text
    assert "Sort Method" not in plan_text  # no full sort over the namespace


async def _build_params(scale_rag, question, namespace):
    """Reconstruct query()'s bind-param dict verbatim.

    Mirrors retrieval.query() lines ~371-393: same embedding call, same
    _to_or_tsquery, same effective_top_k / candidate_k / evolution binds.
    Using the production embedder + helpers (not a hand-rolled vector)
    is what makes the EXPLAIN below a real guard on the shipped path.
    """
    config = scale_rag.config
    embedder = scale_rag._get_embedder()
    q_embedding = (await embedder.embed([question]))[0]
    return {
        "embedding": q_embedding,
        "query": question,
        "tsquery": _to_or_tsquery(question),
        "namespace": namespace,
        "top_k": config.top_k,
        "candidate_k": max(config.retrieval_candidate_k, config.top_k),
        "seed_k": min(config.top_k, 5),
        "max_hops": config.max_hops,
        "w_sem": config.w_sem,
        "w_bm25": config.w_bm25,
        "w_graph": config.w_graph,
        **evolution_bind_params(config),
    }


@pytest.mark.integration
@pytest.mark.asyncio
async def test_real_builders_two_stage_uses_hnsw_single_stage_seqscans(scale_rag):
    """Regression guard on the GENERATED SQL, not a reference query.

    The spike-verbatim test above EXPLAINs a hand-written inline query and
    would pass even if _build_naive_query_twostage were deleted. This test
    EXPLAINs the exact SQL+params the real builders emit (called the same
    way retrieval.query() calls them) and asserts the flag actually flips
    the plan: two-stage walks idx_chunk_embed (HNSW), single-stage Seq-Scans.
    """
    ns = f"ts_guard_{uuid4().hex}"  # ts% prefix, fixture teardown owns it
    rows = [{"text": f"doc {i} about topic {i % 7}", "source_id": f"tg{i}"} for i in range(3000)]
    await scale_rag.ingest_records(rows, namespace=ns)

    # Immediately-post-ingest queries can transiently miss HNSW until
    # autovacuum analyzes; an explicit ANALYZE makes the plan deterministic.
    await scale_rag.db.execute("ANALYZE chunks")
    await scale_rag.db.execute("ANALYZE documents")

    params = await _build_params(scale_rag, "topic 3", ns)
    config = scale_rag.config

    # Two-stage: the real builder must EXPLAIN onto the HNSW index.
    two_sql, two_extra = _build_naive_query_twostage(config, None, None, None)
    two_plan = await scale_rag.db.fetch_all("EXPLAIN " + two_sql, _merge_params(params, two_extra))
    two_text = "\n".join(str(r) for r in two_plan)
    assert "idx_chunk_embed" in two_text, (
        f"two-stage builder did NOT use HNSW idx_chunk_embed.\nPLAN:\n{two_text}"
    )
    assert "Order By: (embedding <=>" in two_text, (
        f"two-stage candidate ORDER BY not served by index.\nPLAN:\n{two_text}"
    )
    assert "Seq Scan on chunks" not in two_text, (
        f"two-stage builder Seq-Scanned chunks (HNSW not used).\nPLAN:\n{two_text}"
    )

    # Single-stage control: same data, must NOT use the HNSW index.
    # The composite score ORDER BY is not HNSW-eligible, so the planner
    # Seq-Scans + sorts. This proves config.two_stage_retrieval changes
    # the plan rather than the assertion above being trivially true.
    one_sql, one_extra = _build_naive_query(config, None, None, None)
    one_plan = await scale_rag.db.fetch_all("EXPLAIN " + one_sql, _merge_params(params, one_extra))
    one_text = "\n".join(str(r) for r in one_plan)
    assert "idx_chunk_embed" not in one_text, (
        f"single-stage UNEXPECTEDLY used HNSW idx_chunk_embed; the flag no "
        f"longer changes the plan, A/B control is void.\nPLAN:\n{one_text}"
    )
    assert "Seq Scan on chunks" in one_text, (
        f"single-stage control did not Seq-Scan chunks as expected.\nPLAN:\n{one_text}"
    )


class _RecordingDB:
    def __init__(self):
        self.calls = []

    async def fetch_all(self, sql, params):
        self.calls.append((sql, params))
        return []


class _TinyEmbedder:
    async def embed(self, texts):
        return [[0.0, 0.0, 0.0] for _ in texts]


@pytest.mark.asyncio
async def test_twostage_candidate_k_expands_to_effective_top_k():
    config = PGRGConfig(
        embedding_dim=3,
        top_k=10,
        retrieval_candidate_k=10,
        two_stage_retrieval=True,
    )
    db = _RecordingDB()

    await query(
        "candidate expansion",
        db,
        _TinyEmbedder(),
        config,
        mode="naive",
        top_k_override=25,
    )

    assert db.calls
    _, params = db.calls[0]
    assert params["top_k"] == 25
    assert params["candidate_k"] == 25
