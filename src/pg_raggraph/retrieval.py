"""Hybrid retrieval engine — CTE + pgvector + BM25 in single queries."""

from __future__ import annotations

import time
from datetime import datetime
from typing import Literal

from pg_raggraph.config import PGRGConfig
from pg_raggraph.db import Database
from pg_raggraph.embedding import EmbeddingProvider
from pg_raggraph.evolution import (
    _effective_tier,
    evolution_bind_params,
    evolution_score_expr,
    evolution_where_clauses,
    memory_tier_clause,
)
from pg_raggraph.models import ChunkResult, EntityResult, QueryResult, RelationshipResult

QueryMode = Literal["local", "global", "hybrid", "naive", "naive_boost", "smart"]

_RETRIEVAL_STRATEGY_VALUES = ("weighted", "pre_filter", "vector_first")


def _effective_retrieval_strategy(cfg: PGRGConfig, override: str | None) -> str:
    """Resolve retrieval_strategy after applying the per-query override.

    ``None`` falls back to ``cfg.retrieval_strategy`` (today's "weighted"
    by default — backward-compatible). Validates against the Literal set.
    """
    if override is None:
        return cfg.retrieval_strategy
    if override not in _RETRIEVAL_STRATEGY_VALUES:
        raise ValueError(
            f"Invalid retrieval_strategy {override!r}. "
            f"Must be one of: {_RETRIEVAL_STRATEGY_VALUES}"
        )
    return override


def _merge_params(base: dict, extra: dict) -> dict:
    """Merge two bind-param dicts, raising on key collision.

    Guards against future edits where evolution_bind_params or builder
    extra params start using overlapping keys — silent overrides would
    cause subtle wrong-result bugs in retrieval.
    """
    overlap = set(base) & set(extra)
    if overlap:
        raise RuntimeError(f"Bind-param key collision in retrieval query: {sorted(overlap)}")
    return {**base, **extra}


def _to_or_tsquery(text: str) -> str:
    """Convert text to an OR-based tsquery string.

    "payment service outage" → "payment | service | outage"
    This matches chunks containing ANY of the words, not ALL.
    Limits to 20 words to prevent tsquery parser overflow.
    """
    import re

    words = re.findall(r"\w+", text.lower())
    if not words:
        return "empty"
    # Filter short words and limit to 20 terms (prevent tsquery overflow)
    words = [w for w in words if len(w) > 2][:20]
    return " | ".join(words) if words else "empty"


# --- SQL Templates ---
#
# These are built per-query from the active PGRGConfig so different callers
# can toggle evolution_tier without restarting. When evolution_tier == "off"
# the builders return the today's byte-identical base expression (plus
# parameterized weights) and skip the retraction filter.


def _build_naive_query(
    cfg: PGRGConfig,
    as_of: datetime | None = None,
    version_filter: str | None = None,
    evolution_aware: bool | None = None,
    retracted_behavior: str | None = None,
    supersession_behavior: str | None = None,
    memory_tier: str | None = None,
) -> tuple[str, dict]:
    base = (
        "%(w_sem)s * (1 - (c.embedding <=> %(embedding)s::vector)) + "
        "%(w_bm25)s * ts_rank(c.search_vector, to_tsquery('english', %(tsquery)s)) + "
        "%(w_graph)s * 0"  # naive has no graph leg
    )
    clauses, extra_params = evolution_where_clauses(
        cfg,
        doc_alias="d",
        as_of=as_of,
        version_filter=version_filter,
        evolution_aware=evolution_aware,
        retracted_behavior=retracted_behavior,
        supersession_behavior=supersession_behavior,
    )
    mt_clause, mt_params = memory_tier_clause(cfg, chunk_alias="c", override=memory_tier)
    if mt_clause:
        clauses.append(mt_clause)
        extra_params = _merge_params(extra_params, mt_params)
    extra_where = (" AND " + " AND ".join(clauses)) if clauses else ""
    # PRG-1 consumer-surface columns (d.metadata/retracted/version_label/
    # effective_from/effective_to/superseded_by_id) are intentionally repeated
    # in all three builders below — keep the three SELECT blocks in sync.
    sql = f"""
SELECT c.id, COALESCE(c.embedded_content, c.content) AS content, c.metadata,
       d.source_path,
       d.metadata AS doc_metadata,
       d.retracted, d.version_label, d.effective_from, d.effective_to,
       (SELECT dv.document_id FROM document_versions dv
        WHERE dv.supersedes_document_id = d.id ORDER BY dv.id LIMIT 1)
           AS superseded_by_id,
       1 - (c.embedding <=> %(embedding)s::vector) AS vec_score,
       ts_rank(c.search_vector, to_tsquery('english', %(tsquery)s)) AS bm25_score,
       {evolution_score_expr(base, cfg, evolution_aware, retracted_behavior)} AS score
FROM chunks c
JOIN documents d ON d.id = c.document_id
WHERE d.namespace = %(namespace)s{extra_where}
ORDER BY score DESC
LIMIT %(top_k)s
"""
    return sql, extra_params


def _build_naive_query_twostage(
    cfg: PGRGConfig,
    as_of: datetime | None = None,
    version_filter: str | None = None,
    evolution_aware: bool | None = None,
    retracted_behavior: str | None = None,
    supersession_behavior: str | None = None,
    memory_tier: str | None = None,
) -> tuple[str, dict]:
    """Two-stage naive retrieval (K1).

    Stage 1 — a candidate CTE whose ORDER BY is the *bare* distance
    ``c.embedding <=> %(embedding)s::vector`` (no composite arithmetic),
    which is HNSW-eligible so the planner can serve it from
    ``idx_chunk_embed`` instead of Seq-Scanning the namespace.

    Stage 2 — the EXISTING composite ``score`` expression from
    ``_build_naive_query`` re-scores only the <= retrieval_candidate_k
    candidates, then trims to top_k. The scoring expression and the
    PRG-1 consumer-surface columns are kept byte-identical to the
    single-stage builder so ranking is the same when the candidate set
    is a superset of the true top-k (it is, since w_sem dominates).

    The candidate CTE re-joins ``documents`` (it only carries
    ``document_id``) so the re-score block can expose every column
    ``query()``'s row consumer reads. ``evolution_where_clauses`` is
    reused exactly as ``_build_naive_query`` does and applies to the
    CTE's ``documents`` join — when evolution_tier == "off" the clauses
    list is empty and both builders are byte-stable.
    """
    base = (
        "%(w_sem)s * (1 - (cand.embedding <=> %(embedding)s::vector)) + "
        "%(w_bm25)s * ts_rank(cand.search_vector, to_tsquery('english', %(tsquery)s)) + "
        "%(w_graph)s * 0"  # naive has no graph leg
    )
    clauses, extra_params = evolution_where_clauses(
        cfg,
        doc_alias="d",
        as_of=as_of,
        version_filter=version_filter,
        evolution_aware=evolution_aware,
        retracted_behavior=retracted_behavior,
        supersession_behavior=supersession_behavior,
    )
    # memory_tier filter applies to the candidate CTE's chunk alias `c`,
    # so HNSW seek-ahead can still skip non-matching chunks.
    mt_clause, mt_params = memory_tier_clause(cfg, chunk_alias="c", override=memory_tier)
    if mt_clause:
        clauses.append(mt_clause)
        extra_params = _merge_params(extra_params, mt_params)
    extra_where = (" AND " + " AND ".join(clauses)) if clauses else ""
    sql = f"""
WITH candidates AS (
    SELECT c.id, c.embedding, c.search_vector,
           COALESCE(c.embedded_content, c.content) AS content,
           c.metadata, c.document_id
    FROM chunks c
    JOIN documents d ON d.id = c.document_id
    WHERE d.namespace = %(namespace)s{extra_where}
    ORDER BY c.embedding <=> %(embedding)s::vector
    LIMIT %(candidate_k)s
)
SELECT cand.id, cand.content, cand.metadata,
       d.source_path,
       d.metadata AS doc_metadata,
       d.retracted, d.version_label, d.effective_from, d.effective_to,
       (SELECT dv.document_id FROM document_versions dv
        WHERE dv.supersedes_document_id = d.id ORDER BY dv.id LIMIT 1)
           AS superseded_by_id,
       1 - (cand.embedding <=> %(embedding)s::vector) AS vec_score,
       ts_rank(cand.search_vector, to_tsquery('english', %(tsquery)s)) AS bm25_score,
       {evolution_score_expr(base, cfg, evolution_aware, retracted_behavior)} AS score
FROM candidates cand
JOIN documents d ON d.id = cand.document_id
ORDER BY score DESC
LIMIT %(top_k)s
"""
    return sql, extra_params


def _build_naive_prefilter(
    cfg: PGRGConfig,
    as_of: datetime | None = None,
    version_filter: str | None = None,
    evolution_aware: bool | None = None,
    retracted_behavior: str | None = None,
    supersession_behavior: str | None = None,
    memory_tier: str | None = None,
) -> tuple[str, dict]:
    """Naive retrieval, ``retrieval_strategy='pre_filter'`` path.

    Same SQL shape as ``_build_naive_query`` (single-pass), but wraps the
    namespace + predicates in a CTE so the planner is encouraged to
    materialize the predicate-matching subset BEFORE the composite-score
    ORDER BY. When the predicate column is indexed (namespace, future
    JSONB GIN/generated columns), the CTE materializes a small set fast
    and the vector compute + sort runs over only matching rows.

    For unindexed predicates (e.g., plain JSONB metadata keys) this
    devolves to weighted-equivalent latency — the planner still has to
    scan to identify matches. Use this strategy with an index strategy;
    see docs/cookbook/retrieval-strategy.md (TODO).
    """
    base = (
        "%(w_sem)s * (1 - (cand.embedding <=> %(embedding)s::vector)) + "
        "%(w_bm25)s * ts_rank(cand.search_vector, to_tsquery('english', %(tsquery)s)) + "
        "%(w_graph)s * 0"
    )
    clauses, extra_params = evolution_where_clauses(
        cfg,
        doc_alias="d",
        as_of=as_of,
        version_filter=version_filter,
        evolution_aware=evolution_aware,
        retracted_behavior=retracted_behavior,
        supersession_behavior=supersession_behavior,
    )
    mt_clause, mt_params = memory_tier_clause(cfg, chunk_alias="c", override=memory_tier)
    if mt_clause:
        clauses.append(mt_clause)
        extra_params = _merge_params(extra_params, mt_params)
    extra_where = (" AND " + " AND ".join(clauses)) if clauses else ""
    sql = f"""
WITH filtered AS (
    SELECT c.id, c.embedding, c.search_vector,
           COALESCE(c.embedded_content, c.content) AS content,
           c.metadata, c.document_id
    FROM chunks c
    JOIN documents d ON d.id = c.document_id
    WHERE d.namespace = %(namespace)s{extra_where}
)
SELECT cand.id, cand.content, cand.metadata,
       d.source_path,
       d.metadata AS doc_metadata,
       d.retracted, d.version_label, d.effective_from, d.effective_to,
       (SELECT dv.document_id FROM document_versions dv
        WHERE dv.supersedes_document_id = d.id ORDER BY dv.id LIMIT 1)
           AS superseded_by_id,
       1 - (cand.embedding <=> %(embedding)s::vector) AS vec_score,
       ts_rank(cand.search_vector, to_tsquery('english', %(tsquery)s)) AS bm25_score,
       {evolution_score_expr(base, cfg, evolution_aware, retracted_behavior)} AS score
FROM filtered cand
JOIN documents d ON d.id = cand.document_id
ORDER BY score DESC
LIMIT %(top_k)s
"""
    return sql, extra_params


def _build_naive_vector_first(
    cfg: PGRGConfig,
    as_of: datetime | None = None,
    version_filter: str | None = None,
    evolution_aware: bool | None = None,
    retracted_behavior: str | None = None,
    supersession_behavior: str | None = None,
    memory_tier: str | None = None,
) -> tuple[str, dict]:
    """Naive retrieval, ``retrieval_strategy='vector_first'`` path.

    The candidate CTE does a BARE ``ORDER BY embedding <=> q`` with NO
    namespace join — the planner is free to use the HNSW index
    (``idx_chunk_embed``) directly. Fetches ``top_k * retrieval_oversample_factor``
    candidates, then the outer query post-filters by namespace +
    predicates and re-ranks with the composite score.

    Best for: broad/exploratory queries on large single-namespace
    corpora where HNSW actually beats a namespace-scoped seq scan.

    Worst for: multi-namespace deployments where the HNSW seed may
    return mostly off-namespace rows that get discarded post-filter
    (oversample compensates partially; bump ``retrieval_oversample_factor``
    or switch to "pre_filter" / "weighted" if recall drops).

    NOTE: the post-filter WHERE includes namespace, evolution clauses,
    and memory_tier — same set as weighted/pre_filter. The trade is
    "HNSW-fast seed, then trim" vs "scoped scan, single pass."
    """
    base = (
        "%(w_sem)s * (1 - (cand.embedding <=> %(embedding)s::vector)) + "
        "%(w_bm25)s * ts_rank(cand.search_vector, to_tsquery('english', %(tsquery)s)) + "
        "%(w_graph)s * 0"
    )
    clauses, extra_params = evolution_where_clauses(
        cfg,
        doc_alias="d",
        as_of=as_of,
        version_filter=version_filter,
        evolution_aware=evolution_aware,
        retracted_behavior=retracted_behavior,
        supersession_behavior=supersession_behavior,
    )
    # vector_first post-filters by chunk metadata, so the alias matters —
    # in the outer SELECT the chunk metadata lives on `cand`.
    mt_clause, mt_params = memory_tier_clause(cfg, chunk_alias="cand", override=memory_tier)
    if mt_clause:
        clauses.append(mt_clause)
        extra_params = _merge_params(extra_params, mt_params)
    extra_where = (" AND " + " AND ".join(clauses)) if clauses else ""
    sql = f"""
WITH candidates AS (
    SELECT c.id, c.embedding, c.search_vector,
           COALESCE(c.embedded_content, c.content) AS content,
           c.metadata, c.document_id
    FROM chunks c
    ORDER BY c.embedding <=> %(embedding)s::vector
    LIMIT %(vector_first_k)s
)
SELECT cand.id, cand.content, cand.metadata,
       d.source_path,
       d.metadata AS doc_metadata,
       d.retracted, d.version_label, d.effective_from, d.effective_to,
       (SELECT dv.document_id FROM document_versions dv
        WHERE dv.supersedes_document_id = d.id ORDER BY dv.id LIMIT 1)
           AS superseded_by_id,
       1 - (cand.embedding <=> %(embedding)s::vector) AS vec_score,
       ts_rank(cand.search_vector, to_tsquery('english', %(tsquery)s)) AS bm25_score,
       {evolution_score_expr(base, cfg, evolution_aware, retracted_behavior)} AS score
FROM candidates cand
JOIN documents d ON d.id = cand.document_id
WHERE d.namespace = %(namespace)s{extra_where}
ORDER BY score DESC
LIMIT %(top_k)s
"""
    return sql, extra_params


def _build_local_query(
    cfg: PGRGConfig,
    as_of: datetime | None = None,
    version_filter: str | None = None,
    evolution_aware: bool | None = None,
    retracted_behavior: str | None = None,
    supersession_behavior: str | None = None,
    memory_tier: str | None = None,
) -> tuple[str, dict]:
    base = (
        "%(w_sem)s * (1 - (rc.embedding <=> %(embedding)s::vector)) + "
        "%(w_bm25)s * ts_rank(rc.search_vector, to_tsquery('english', %(tsquery)s)) + "
        "%(w_graph)s * 1.0"  # graph leg: binary presence in neighborhood
    )
    clauses, extra_params = evolution_where_clauses(
        cfg,
        doc_alias="d",
        as_of=as_of,
        version_filter=version_filter,
        evolution_aware=evolution_aware,
        retracted_behavior=retracted_behavior,
        supersession_behavior=supersession_behavior,
    )
    # memory_tier applies to the post-graph chunk set — alias `rc` in the
    # outer SELECT preserves c.metadata from the relevant_chunks CTE.
    mt_clause, mt_params = memory_tier_clause(cfg, chunk_alias="rc", override=memory_tier)
    if mt_clause:
        clauses.append(mt_clause)
        extra_params = _merge_params(extra_params, mt_params)
    extra_where = (" AND " + " AND ".join(clauses)) if clauses else ""
    sql = f"""
WITH RECURSIVE seeds AS (
    SELECT id, 1 - (embedding <=> %(embedding)s::vector) AS sim
    FROM entities
    WHERE namespace = %(namespace)s
    ORDER BY embedding <=> %(embedding)s::vector
    LIMIT %(seed_k)s
),
neighborhood AS (
    SELECT id, 0 AS depth, ARRAY[id] AS path FROM seeds
    UNION ALL
    SELECT e2.id, n.depth + 1, n.path || e2.id
    FROM neighborhood n
    JOIN relationships r ON (r.src_id = n.id OR r.dst_id = n.id)
    JOIN entities e2 ON e2.id = CASE
        WHEN r.src_id = n.id THEN r.dst_id ELSE r.src_id END
    WHERE n.depth < %(max_hops)s
      AND NOT (e2.id = ANY(n.path))
),
relevant_chunks AS (
    SELECT DISTINCT c.id,
           COALESCE(c.embedded_content, c.content) AS content,
           c.embedding, c.search_vector, c.metadata, c.document_id
    FROM chunks c
    JOIN entity_chunks ec ON ec.chunk_id = c.id
    WHERE ec.entity_id IN (SELECT DISTINCT id FROM neighborhood)
)
SELECT rc.id, rc.content, rc.metadata,
       d.source_path,
       d.metadata AS doc_metadata,
       d.retracted, d.version_label, d.effective_from, d.effective_to,
       (SELECT dv.document_id FROM document_versions dv
        WHERE dv.supersedes_document_id = d.id ORDER BY dv.id LIMIT 1)
           AS superseded_by_id,
       {evolution_score_expr(base, cfg, evolution_aware, retracted_behavior)} AS score
FROM relevant_chunks rc
JOIN documents d ON d.id = rc.document_id
WHERE d.namespace = %(namespace)s{extra_where}
ORDER BY score DESC
LIMIT %(top_k)s
"""
    return sql, extra_params


def _build_global_query(
    cfg: PGRGConfig,
    as_of: datetime | None = None,
    version_filter: str | None = None,
    evolution_aware: bool | None = None,
    retracted_behavior: str | None = None,
    supersession_behavior: str | None = None,
    memory_tier: str | None = None,
) -> tuple[str, dict]:
    base = (
        "%(w_sem)s * (1 - (rc.embedding <=> %(embedding)s::vector)) + "
        "%(w_bm25)s * ts_rank(rc.search_vector, to_tsquery('english', %(tsquery)s)) + "
        "%(w_graph)s * 1.0"  # graph leg: binary presence via relationship seed
    )
    clauses, extra_params = evolution_where_clauses(
        cfg,
        doc_alias="d",
        as_of=as_of,
        version_filter=version_filter,
        evolution_aware=evolution_aware,
        retracted_behavior=retracted_behavior,
        supersession_behavior=supersession_behavior,
    )
    # Same memory_tier alias as local — `rc` in the outer SELECT.
    mt_clause, mt_params = memory_tier_clause(cfg, chunk_alias="rc", override=memory_tier)
    if mt_clause:
        clauses.append(mt_clause)
        extra_params = _merge_params(extra_params, mt_params)
    extra_where = (" AND " + " AND ".join(clauses)) if clauses else ""
    sql = f"""
WITH rel_matches AS (
    SELECT r.id, r.src_id, r.dst_id, r.rel_type, r.description,
           1 - (e_src.embedding <=> %(embedding)s::vector) AS src_sim,
           1 - (e_dst.embedding <=> %(embedding)s::vector) AS dst_sim
    FROM relationships r
    JOIN entities e_src ON e_src.id = r.src_id
    JOIN entities e_dst ON e_dst.id = r.dst_id
    WHERE r.namespace = %(namespace)s
    ORDER BY GREATEST(
        1 - (e_src.embedding <=> %(embedding)s::vector),
        1 - (e_dst.embedding <=> %(embedding)s::vector)
    ) DESC
    LIMIT %(seed_k)s
),
rel_entity_ids AS (
    SELECT src_id AS id FROM rel_matches
    UNION
    SELECT dst_id AS id FROM rel_matches
),
relevant_chunks AS (
    SELECT DISTINCT c.id,
           COALESCE(c.embedded_content, c.content) AS content,
           c.embedding, c.search_vector, c.metadata, c.document_id
    FROM chunks c
    JOIN entity_chunks ec ON ec.chunk_id = c.id
    WHERE ec.entity_id IN (SELECT id FROM rel_entity_ids)
)
SELECT rc.id, rc.content, rc.metadata,
       d.source_path,
       d.metadata AS doc_metadata,
       d.retracted, d.version_label, d.effective_from, d.effective_to,
       (SELECT dv.document_id FROM document_versions dv
        WHERE dv.supersedes_document_id = d.id ORDER BY dv.id LIMIT 1)
           AS superseded_by_id,
       {evolution_score_expr(base, cfg, evolution_aware, retracted_behavior)} AS score
FROM relevant_chunks rc
JOIN documents d ON d.id = rc.document_id
WHERE d.namespace = %(namespace)s{extra_where}
ORDER BY score DESC
LIMIT %(top_k)s
"""
    return sql, extra_params


ENTITIES_FOR_CHUNKS = """
SELECT DISTINCT e.name, e.entity_type, e.description
FROM entities e
JOIN entity_chunks ec ON ec.entity_id = e.id
WHERE ec.chunk_id = ANY(%(chunk_ids)s)
"""

RELATIONSHIPS_FOR_ENTITIES = """
SELECT DISTINCT e_src.name AS source, e_dst.name AS target,
       r.rel_type, r.description
FROM relationships r
JOIN entities e_src ON e_src.id = r.src_id
JOIN entities e_dst ON e_dst.id = r.dst_id
WHERE r.src_id IN (
    SELECT entity_id FROM entity_chunks WHERE chunk_id = ANY(%(chunk_ids)s)
)
OR r.dst_id IN (
    SELECT entity_id FROM entity_chunks WHERE chunk_id = ANY(%(chunk_ids)s)
)
LIMIT 20
"""


async def query(
    question: str,
    db: Database,
    embedder: EmbeddingProvider,
    config: PGRGConfig,
    mode: QueryMode = "hybrid",
    namespace: str | None = None,
    *,
    as_of: datetime | None = None,
    version_filter: str | None = None,
    evolution_aware: bool | None = None,
    retracted_behavior: str | None = None,
    supersession_behavior: str | None = None,
    memory_tier: str | None = None,
    retrieval_strategy: str | None = None,
    top_k_override: int | None = None,
) -> QueryResult:
    """Execute a retrieval query against the knowledge graph.

    ``top_k_override`` lets callers fetch a larger candidate pool when
    a downstream reranker will trim back to ``config.top_k``. None
    falls back to ``config.top_k``.
    """
    valid_modes = ("naive", "local", "global", "hybrid", "naive_boost", "smart")
    if mode not in valid_modes:
        raise ValueError(f"Invalid mode '{mode}'. Must be one of: {valid_modes}")

    # Smart and naive_boost modes are handled in separate functions
    if mode == "smart":
        return await _smart_query(
            question,
            db,
            embedder,
            config,
            namespace,
            as_of=as_of,
            version_filter=version_filter,
            evolution_aware=evolution_aware,
            retracted_behavior=retracted_behavior,
            supersession_behavior=supersession_behavior,
            memory_tier=memory_tier,
            retrieval_strategy=retrieval_strategy,
            top_k_override=top_k_override,
        )
    if mode == "naive_boost":
        return await _naive_boost_query(
            question,
            db,
            embedder,
            config,
            namespace,
            as_of=as_of,
            version_filter=version_filter,
            evolution_aware=evolution_aware,
            retracted_behavior=retracted_behavior,
            supersession_behavior=supersession_behavior,
            memory_tier=memory_tier,
            retrieval_strategy=retrieval_strategy,
            top_k_override=top_k_override,
        )

    start = time.perf_counter()
    ns = namespace or config.namespace
    effective_top_k = top_k_override or config.top_k
    candidate_k = max(config.retrieval_candidate_k, effective_top_k)

    # Embed the question
    q_embedding = (await embedder.embed([question]))[0]

    tsquery = _to_or_tsquery(question)

    params = {
        "embedding": q_embedding,
        "query": question,
        "tsquery": tsquery,
        "namespace": ns,
        "top_k": effective_top_k,
        "candidate_k": candidate_k,
        "seed_k": min(effective_top_k, 5),
        "max_hops": config.max_hops,
        "w_sem": config.w_sem,
        "w_bm25": config.w_bm25,
        "w_graph": config.w_graph,
        **evolution_bind_params(config),
    }

    if mode == "naive":
        # retrieval_strategy router (Scope A, #4 follow-up):
        # - "pre_filter": CTE-materialized predicate subset → rank.
        # - "vector_first": HNSW-seed CTE (no namespace join) → post-filter.
        # - "weighted" (default): preserves existing two_stage_retrieval flow.
        effective_strategy = _effective_retrieval_strategy(config, retrieval_strategy)
        if effective_strategy == "pre_filter":
            sql, extra = _build_naive_prefilter(
                config,
                as_of,
                version_filter,
                evolution_aware,
                retracted_behavior,
                supersession_behavior,
                memory_tier,
            )
        elif effective_strategy == "vector_first":
            sql, extra = _build_naive_vector_first(
                config,
                as_of,
                version_filter,
                evolution_aware,
                retracted_behavior,
                supersession_behavior,
                memory_tier,
            )
            # vector_first needs an extra bind param for its oversample CTE.
            params["vector_first_k"] = effective_top_k * config.retrieval_oversample_factor
        elif config.two_stage_retrieval:
            sql, extra = _build_naive_query_twostage(
                config,
                as_of,
                version_filter,
                evolution_aware,
                retracted_behavior,
                supersession_behavior,
                memory_tier,
            )
        else:
            sql, extra = _build_naive_query(
                config,
                as_of,
                version_filter,
                evolution_aware,
                retracted_behavior,
                supersession_behavior,
                memory_tier,
            )
        rows = await db.fetch_all(sql, _merge_params(params, extra))
    elif mode == "local":
        sql, extra = _build_local_query(
            config,
            as_of,
            version_filter,
            evolution_aware,
            retracted_behavior,
            supersession_behavior,
            memory_tier,
        )
        rows = await db.fetch_all(sql, _merge_params(params, extra))
    elif mode == "global":
        sql, extra = _build_global_query(
            config,
            as_of,
            version_filter,
            evolution_aware,
            retracted_behavior,
            supersession_behavior,
            memory_tier,
        )
        rows = await db.fetch_all(sql, _merge_params(params, extra))
    elif mode == "hybrid":
        # Run local and global, merge results
        local_sql, local_extra = _build_local_query(
            config,
            as_of,
            version_filter,
            evolution_aware,
            retracted_behavior,
            supersession_behavior,
            memory_tier,
        )
        global_sql, global_extra = _build_global_query(
            config,
            as_of,
            version_filter,
            evolution_aware,
            retracted_behavior,
            supersession_behavior,
            memory_tier,
        )
        local_rows = await db.fetch_all(local_sql, _merge_params(params, local_extra))
        global_rows = await db.fetch_all(global_sql, _merge_params(params, global_extra))
        # Deduplicate by chunk ID, prefer higher score
        seen = {}
        for row in local_rows + global_rows:
            cid = row["id"]
            if cid not in seen or row["score"] > seen[cid]["score"]:
                seen[cid] = row
        rows = sorted(seen.values(), key=lambda r: r["score"], reverse=True)[:effective_top_k]
    else:
        rows = []

    # Build chunk results
    evo_on = _effective_tier(config, evolution_aware) != "off"
    chunks = []
    chunk_ids = []
    for row in rows:
        chunks.append(
            ChunkResult(
                content=row["content"],
                score=float(row["score"]) if row["score"] else 0.0,
                document_source=row.get("source_path"),
                chunk_id=row["id"],
                # PRG-1: opaque caller metadata is tier-independent.
                # DEC-4: empty/absent JSONB ('{}') maps to None.
                metadata=(row.get("doc_metadata") or None),
                # DEC-5: evolution fields only when effective tier != "off".
                retracted=(row.get("retracted") if evo_on else None),
                version_label=(row.get("version_label") if evo_on else None),
                effective_from=(row.get("effective_from") if evo_on else None),
                effective_to=(row.get("effective_to") if evo_on else None),
                superseded_by_id=(row.get("superseded_by_id") if evo_on else None),
            )
        )
        chunk_ids.append(row["id"])

    # Fetch related entities and relationships
    entities = []
    relationships = []
    if chunk_ids:
        ent_rows = await db.fetch_all(ENTITIES_FOR_CHUNKS, {"chunk_ids": chunk_ids})
        entities = [
            EntityResult(
                name=r["name"],
                entity_type=r["entity_type"],
                description=r["description"] or "",
            )
            for r in ent_rows
        ]

        rel_rows = await db.fetch_all(RELATIONSHIPS_FOR_ENTITIES, {"chunk_ids": chunk_ids})
        relationships = [
            RelationshipResult(
                source=r["source"],
                target=r["target"],
                rel_type=r["rel_type"],
                description=r["description"] or "",
            )
            for r in rel_rows
        ]

    latency_ms = (time.perf_counter() - start) * 1000

    result = QueryResult(
        chunks=chunks,
        entities=entities,
        relationships=relationships,
        query_mode=mode,
        latency_ms=latency_ms,
    )
    result.populate_confidence(
        high_threshold=config.boost_confidence_threshold,
        low_threshold=config.expand_confidence_threshold,
    )
    return result


# --- Smart mode and graph boost ---

GRAPH_BOOST_QUERY = """
WITH seed_entities AS (
    SELECT DISTINCT entity_id
    FROM entity_chunks
    WHERE chunk_id = ANY(%(chunk_ids)s)
),
neighbors AS (
    SELECT DISTINCT
        CASE WHEN r.src_id IN (SELECT entity_id FROM seed_entities)
             THEN r.dst_id ELSE r.src_id END AS nid
    FROM relationships r
    WHERE (r.src_id IN (SELECT entity_id FROM seed_entities)
           OR r.dst_id IN (SELECT entity_id FROM seed_entities))
      AND r.namespace = %(namespace)s
)
SELECT c.id,
       COALESCE(COUNT(DISTINCT ec.entity_id) FILTER (
           WHERE ec.entity_id IN (SELECT nid FROM neighbors)
       ), 0) AS neighbor_hits
FROM chunks c
LEFT JOIN entity_chunks ec ON ec.chunk_id = c.id
WHERE c.id = ANY(%(chunk_ids)s)
GROUP BY c.id
"""


async def _graph_boost(
    result: QueryResult, db: Database, config: PGRGConfig, namespace: str
) -> QueryResult:
    """Apply 1-hop graph boost to re-rank vector-retrieved chunks.

    Takes the top-K chunks from a vector search, finds entities in those
    chunks, then checks which OTHER chunks contain entities connected to
    those seed entities. Boosts the score of chunks with graph connections.

    This is cheap — one SQL query, no recursion — but captures the signal
    that "related chunks via entity relationships" are more relevant.
    """
    if not result.chunks or not config.enable_graph_boost:
        return result

    chunk_ids = [c.chunk_id for c in result.chunks if c.chunk_id is not None]
    if not chunk_ids:
        return result

    boost_rows = await db.fetch_all(
        GRAPH_BOOST_QUERY, {"chunk_ids": chunk_ids, "namespace": namespace}
    )
    boost_map = {r["id"]: r["neighbor_hits"] for r in boost_rows}

    for chunk in result.chunks:
        if chunk.chunk_id is None:
            continue
        hits = boost_map.get(chunk.chunk_id, 0)
        if hits > 0:
            chunk.score *= config.graph_boost_factor

    result.chunks.sort(key=lambda c: c.score, reverse=True)
    result.populate_confidence(
        high_threshold=config.boost_confidence_threshold,
        low_threshold=config.expand_confidence_threshold,
    )
    return result


async def _naive_boost_query(
    question: str,
    db: Database,
    embedder: EmbeddingProvider,
    config: PGRGConfig,
    namespace: str | None = None,
    *,
    as_of: datetime | None = None,
    version_filter: str | None = None,
    evolution_aware: bool | None = None,
    retracted_behavior: str | None = None,
    supersession_behavior: str | None = None,
    memory_tier: str | None = None,
    retrieval_strategy: str | None = None,
    top_k_override: int | None = None,
) -> QueryResult:
    """Naive vector+BM25 retrieval followed by cheap 1-hop graph boost."""
    result = await query(
        question=question,
        db=db,
        embedder=embedder,
        config=config,
        mode="naive",
        namespace=namespace,
        as_of=as_of,
        version_filter=version_filter,
        evolution_aware=evolution_aware,
        retracted_behavior=retracted_behavior,
        supersession_behavior=supersession_behavior,
        memory_tier=memory_tier,
        retrieval_strategy=retrieval_strategy,
        top_k_override=top_k_override,
    )
    ns = namespace or config.namespace
    boosted = await _graph_boost(result, db, config, ns)
    boosted.query_mode = "naive_boost"
    return boosted


def _merge_and_dedupe(primary: QueryResult, secondary: QueryResult, top_k: int) -> QueryResult:
    """Merge two QueryResults, deduping by chunk_id, keeping highest-scored."""
    seen: dict = {}
    for chunk in primary.chunks + secondary.chunks:
        key = chunk.chunk_id if chunk.chunk_id is not None else chunk.content[:100]
        if key not in seen or chunk.score > seen[key].score:
            seen[key] = chunk
    merged = sorted(seen.values(), key=lambda c: c.score, reverse=True)[:top_k]
    primary.chunks = merged

    # Union entities and relationships
    ent_names = {e.name for e in primary.entities}
    for e in secondary.entities:
        if e.name not in ent_names:
            primary.entities.append(e)
            ent_names.add(e.name)

    rel_keys = {(r.source, r.target, r.rel_type) for r in primary.relationships}
    for r in secondary.relationships:
        k = (r.source, r.target, r.rel_type)
        if k not in rel_keys:
            primary.relationships.append(r)
            rel_keys.add(k)
    return primary


# --- smart-router question-shape detection ---
#
# The original smart router (validated on pg-agents) only routed between
# naive → naive_boost → local. The CRM compare_modes.py run on
# 2026-04-30 surfaced a real gap: questions like "What's the most common
# reason we win deals?" or "What objections came up most often" want
# *aggregation across documents*, which the `global` mode (relationship-
# centric retrieval) handles best. The original router never picked
# `global` because naive can score high on individual chunks while the
# answer needs to span them.
#
# Fix: detect aggregation/synthesis question shape BEFORE running naive
# and route directly to the right mode. Conservative heuristics — only
# fire on clear lexical signals so we don't pay global's higher latency
# on plain lookup questions.

# Aggregation cue tokens — questions implying counting/comparing across docs.
_AGG_PATTERNS = [
    r"\bmost (often|common|frequent)\b",
    r"\bleast (often|common|frequent)\b",
    r"\bhow many\b",
    r"\bwhich .+ (had|has|have) the most\b",
    r"\bacross (all|our|the|every)\b",
    r"\bpattern[s]?\b",
    r"\btrend[s]?\b",
    r"\bsummari[sz]e\b",
    r"\boverall\b",
    r"\bin total\b",
    r"\bevery (customer|deal|product|account)\b",
]

# Synthesis cue tokens — questions implying combining info from many sources.
_SYN_PATTERNS = [
    r"\bcompare\b",
    r"\bcontrast\b",
    r"\b(differences?|similarities)\s+between\b",
    r"\balongside\b",
    r"\b(common|shared) (theme|threads?|reasons?|objections?)\b",
]


def _question_shape(question: str) -> str:
    """Cheap lexical classifier returning aggregation / synthesis / lookup.

    Returns the strongest shape that matches; falls back to "lookup" when
    no aggregation/synthesis signal is present. Tunable via the pattern
    lists above.
    """
    import re

    q = question.lower()
    for p in _AGG_PATTERNS:
        if re.search(p, q):
            return "aggregation"
    for p in _SYN_PATTERNS:
        if re.search(p, q):
            return "synthesis"
    return "lookup"


async def _smart_query(
    question: str,
    db: Database,
    embedder: EmbeddingProvider,
    config: PGRGConfig,
    namespace: str | None = None,
    *,
    as_of: datetime | None = None,
    version_filter: str | None = None,
    evolution_aware: bool | None = None,
    retracted_behavior: str | None = None,
    supersession_behavior: str | None = None,
    memory_tier: str | None = None,
    retrieval_strategy: str | None = None,
    top_k_override: int | None = None,
) -> QueryResult:
    """Confidence + question-shape routing that improves accuracy across corpora.

    Two layers of routing:

    1. **Question shape** (lexical, cheap, fires before naive runs):
       - "aggregation" — questions like "most common", "across all", "how
         many" — route to ``global`` mode (relationship-centric).
       - "synthesis" — questions like "compare X vs Y", "alongside", "common
         themes" — route to ``hybrid`` (local + global merged).
       - "lookup" — falls through to confidence-based routing below.

    2. **Confidence** (validated on pg-agents corpus, 479 docs, 17K entities):
       - High confidence (top_score >= boost_threshold): ship naive as-is.
       - Medium confidence (between thresholds): apply cheap graph boost.
         Boost gives +19% top-score improvement on dev knowledge bases;
         pulling in local-mode chunks dilutes the ranking.
       - Low confidence (top_score < expand_threshold): escalate to local
         mode — pulls in new chunks via graph traversal.

    The shape pre-check came from the 2026-04-30 CRM compare_modes.py run
    (docs/cookbook/sales-crm-ingestion.md "Per-mode breakdown") which showed
    ``global`` winning 5/5 questions while ``smart`` (without shape detection)
    only matched on 3/5. The two questions ``smart`` lost were both
    aggregation-shaped.
    """
    start = time.perf_counter()
    ns = namespace or config.namespace

    # Layer 1: question-shape pre-check. Aggregation/synthesis questions
    # bypass naive's confidence check and go straight to the right mode.
    shape = _question_shape(question)
    if shape == "aggregation":
        agg = await query(
            question=question,
            db=db,
            embedder=embedder,
            config=config,
            mode="global",
            namespace=namespace,
            as_of=as_of,
            version_filter=version_filter,
            evolution_aware=evolution_aware,
            retracted_behavior=retracted_behavior,
            supersession_behavior=supersession_behavior,
            memory_tier=memory_tier,
            retrieval_strategy=retrieval_strategy,
            top_k_override=top_k_override,
        )
        agg.query_mode = "smart[global]"
        agg.latency_ms = (time.perf_counter() - start) * 1000
        return agg
    if shape == "synthesis":
        syn = await query(
            question=question,
            db=db,
            embedder=embedder,
            config=config,
            mode="hybrid",
            namespace=namespace,
            as_of=as_of,
            version_filter=version_filter,
            evolution_aware=evolution_aware,
            retracted_behavior=retracted_behavior,
            supersession_behavior=supersession_behavior,
            memory_tier=memory_tier,
            retrieval_strategy=retrieval_strategy,
            top_k_override=top_k_override,
        )
        syn.query_mode = "smart[hybrid]"
        syn.latency_ms = (time.perf_counter() - start) * 1000
        return syn

    # Layer 2: confidence-based routing for lookup-shaped questions.
    # Always start with naive (cheap)
    result = await query(
        question=question,
        db=db,
        embedder=embedder,
        config=config,
        mode="naive",
        namespace=namespace,
        as_of=as_of,
        version_filter=version_filter,
        evolution_aware=evolution_aware,
        retracted_behavior=retracted_behavior,
        top_k_override=top_k_override,
    )

    # High confidence — ship it
    if result.confidence == "high":
        result.query_mode = "smart[naive]"
        result.latency_ms = (time.perf_counter() - start) * 1000
        return result

    # Low confidence — escalate to local mode (pulls in new chunks via graph)
    if result.confidence == "low":
        expanded = await query(
            question=question,
            db=db,
            embedder=embedder,
            config=config,
            mode="local",
            namespace=namespace,
            as_of=as_of,
            version_filter=version_filter,
            evolution_aware=evolution_aware,
            retracted_behavior=retracted_behavior,
            supersession_behavior=supersession_behavior,
            memory_tier=memory_tier,
            retrieval_strategy=retrieval_strategy,
            top_k_override=top_k_override,
        )
        expanded.query_mode = "smart[expanded]"
        expanded.latency_ms = (time.perf_counter() - start) * 1000
        return expanded

    # Medium confidence — cheap graph boost only (validated best path)
    boosted = await _graph_boost(result, db, config, ns)
    boosted.query_mode = "smart[boosted]"
    boosted.latency_ms = (time.perf_counter() - start) * 1000
    return boosted
