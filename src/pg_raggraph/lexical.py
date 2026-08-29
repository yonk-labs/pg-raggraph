"""Lexical scoring backends for hybrid retrieval (issue #96).

The default backend is PostgreSQL ``ts_rank`` — term-frequency/proximity
only, no corpus statistics. The ``"bm25"`` backend scores Okapi BM25 in SQL
from per-namespace statistics maintained incrementally by the migration-016
triggers:

    score(chunk, Q) = Σ_{t ∈ Q ∩ chunk}  IDF(t) · tf·(k1+1) / (tf + k1·(1 − b + b·dl/avgdl))

    IDF(t) = ln(1 + (N − df + 0.5) / (df + 0.5))   [Lucene's non-negative variant]

where N/avgdl come from ``lexical_corpus_stats``, df from ``lexeme_stats``,
tf is the lexeme's position count in ``chunks.search_vector`` (1 for the
positionless identifier lexemes), and dl is the chunk's total term count.
Query terms are normalized in SQL exactly like the index side: 'english'
stemming plus ``pgrg_identifier_tsvector()`` for underscore identifiers.

Stats maintenance strategy: exact incremental triggers on chunks
(insert/update/delete) and documents (delete-cascade path) — no drift.
Chunks ingested before migration 016 are not counted; run
``rebuild_lexical_stats()`` once per pre-existing namespace.

BM25 raw scores are unbounded (roughly 0–15 on typical corpora), unlike
ts_rank's ~0.01–0.5. The backend is designed for ``fusion="rrf"`` (the
default), which is scale-free; under ``fusion="linear"`` retune ``w_bm25``.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pg_raggraph.config import PGRGConfig
    from pg_raggraph.db import Database

# Byte-identical to the historical inline expression — the ts_rank backend
# must not change existing SQL by a single byte.
_TS_RANK_EXPR = "ts_rank({alias}.search_vector, to_tsquery('english', %(tsquery)s))"

# Normalized query lexemes as text[]: 'english'-stemmed terms plus
# identifier-preserved tokens — symmetric with how chunks.search_vector is
# built (migration 016). Binds the existing %(query)s param (raw question).
_QUERY_LEXEMES_EXPR = (
    "tsvector_to_array(to_tsvector('english', %(query)s) || pgrg_identifier_tsvector(%(query)s))"
)

# Same normalization, but over the EXPANDED query text (%(rare_query)s: the
# raw question plus any retrieval_expansion / retrieval_alias_map terms).
# The #114 coverage bonus must score the same term set the tsquery searches,
# or it fights the expansion features: an alias-lifted doc would win the
# lexical leg only to be out-scored by a raw-term-only bonus.
_RARE_QUERY_LEXEMES_EXPR = (
    "tsvector_to_array(to_tsvector('english', %(rare_query)s)"
    " || pgrg_identifier_tsvector(%(rare_query)s))"
)


def bm25_score_sql(alias: str) -> str:
    """Okapi BM25 as a correlated scalar subquery over ``{alias}.search_vector``.

    Evaluated per candidate row, so it belongs after a candidate-narrowing
    stage (two-stage / pre_filter / vector_first / graph CTEs). Guards:
    GREATEST(N − df, 0) keeps the IDF log argument positive under stats
    drift; missing corpus stats (pre-016 corpora before rebuild) make the
    join empty and the whole leg scores 0 — vector ordering still works.
    """
    return f"""(SELECT COALESCE(sum(
        ln(1.0 + (GREATEST(cs.chunk_count - ls.df, 0) + 0.5) / (ls.df + 0.5))
        * (tf.freq * (%(bm25_k1)s + 1.0))
        / (tf.freq + %(bm25_k1)s * (1.0 - %(bm25_b)s
            + %(bm25_b)s * dl.len
              / GREATEST(cs.total_len::float / GREATEST(cs.chunk_count, 1), 1.0)))
    ), 0.0)
    FROM unnest({alias}.search_vector) lex
    CROSS JOIN LATERAL (
        SELECT GREATEST(COALESCE(array_length(lex.positions, 1), 1), 1)::float AS freq
    ) tf
    CROSS JOIN LATERAL (
        SELECT pgrg_lexeme_len({alias}.search_vector)::float AS len
    ) dl
    JOIN lexeme_stats ls
        ON ls.namespace = %(namespace)s AND ls.lexeme = lex.lexeme
    JOIN lexical_corpus_stats cs
        ON cs.namespace = %(namespace)s
    WHERE lex.lexeme = ANY({_QUERY_LEXEMES_EXPR}))"""


def idf_coverage_sql(alias: str) -> str:
    """IDF-coverage rare-token bonus term (issue #114), in [0, 1].

    The fraction of the query's total IDF mass covered by this chunk's
    matched lexemes: sum(IDF) over query lexemes present in the chunk,
    divided by sum(IDF) over all query lexemes known to the namespace.
    Rare tokens (ticket ids, names, amounts) carry almost all of a query's
    IDF mass, so the docs sharing them separate decisively from template
    near-duplicates that merely match many common words — the class where
    ts_rank (no IDF) and rank-flattened RRF fusion both go blind.

    Self-contained: keyed on ``{alias}.id`` (fetches search_vector itself),
    so it composes into any naive SELECT block regardless of which columns
    the enclosing CTE carries. The denominator subquery is uncorrelated —
    the planner runs it once per statement (InitPlan). Missing stats
    (pre-016 corpora before rebuild) make both sums empty and the term
    scores 0 for every row — ordering falls back to the base score.
    """
    idf = "ln(1.0 + (GREATEST(cs.chunk_count - ls.df, 0) + 0.5) / (ls.df + 0.5))"
    return f"""((SELECT COALESCE(sum({idf}), 0.0)
    FROM chunks ch
    CROSS JOIN LATERAL unnest(ch.search_vector) lex
    JOIN lexeme_stats ls
        ON ls.namespace = %(namespace)s AND ls.lexeme = lex.lexeme
    JOIN lexical_corpus_stats cs
        ON cs.namespace = %(namespace)s
    WHERE ch.id = {alias}.id
      AND lex.lexeme = ANY({_RARE_QUERY_LEXEMES_EXPR}))
    / GREATEST((SELECT COALESCE(sum({idf}), 0.0)
    FROM unnest({_RARE_QUERY_LEXEMES_EXPR}) q(lexeme)
    JOIN lexeme_stats ls
        ON ls.namespace = %(namespace)s AND ls.lexeme = q.lexeme
    JOIN lexical_corpus_stats cs
        ON cs.namespace = %(namespace)s), 1e-9))"""


def lexical_score_sql(cfg: PGRGConfig, alias: str) -> str:
    """The lexical-leg score expression for the configured backend.

    ``alias`` is the chunk-table alias exposing ``search_vector`` in the
    enclosing query. For ``lexical_backend="ts_rank"`` the output is
    byte-identical to the historical inline expression.
    """
    if cfg.lexical_backend == "bm25":
        return bm25_score_sql(alias)
    return _TS_RANK_EXPR.format(alias=alias)


def bm25_score(
    tf: float,
    df: int,
    doc_count: int,
    doc_len: float,
    avg_len: float,
    k1: float = 1.2,
    b: float = 0.75,
) -> float:
    """Python reference of the per-term SQL formula in :func:`bm25_score_sql`.

    Kept in lockstep with the SQL so unit tests can verify the math (IDF
    ordering, length normalization, tf saturation) without a database.
    """
    idf = math.log(1.0 + (max(doc_count - df, 0) + 0.5) / (df + 0.5))
    tf_term = (tf * (k1 + 1.0)) / (tf + k1 * (1.0 - b + b * doc_len / max(avg_len, 1.0)))
    return idf * tf_term


async def rebuild_lexical_stats(db: Database, namespace: str) -> dict[str, Any]:
    """Recompute ``lexeme_stats`` + ``lexical_corpus_stats`` for a namespace.

    Needed once per namespace whose chunks predate migration 016 (the
    triggers only see writes made after the migration). Transactional, but
    it does not lock ``chunks`` — run while ingest into the namespace is
    quiescent, or re-run afterwards.
    """
    async with db.transaction() as tx:
        await tx.execute("DELETE FROM lexeme_stats WHERE namespace = %s", (namespace,))
        await tx.execute("DELETE FROM lexical_corpus_stats WHERE namespace = %s", (namespace,))
        await tx.execute(
            """
            INSERT INTO lexeme_stats (namespace, lexeme, df)
            SELECT d.namespace, t.lexeme, count(*)
            FROM chunks c
            JOIN documents d ON d.id = c.document_id
            CROSS JOIN LATERAL unnest(c.search_vector) t
            WHERE d.namespace = %s
            GROUP BY d.namespace, t.lexeme
            """,
            (namespace,),
        )
        await tx.execute(
            """
            INSERT INTO lexical_corpus_stats (namespace, chunk_count, total_len)
            SELECT d.namespace, count(c.id), COALESCE(sum(pgrg_lexeme_len(c.search_vector)), 0)
            FROM chunks c
            JOIN documents d ON d.id = c.document_id
            WHERE d.namespace = %s
            GROUP BY d.namespace
            """,
            (namespace,),
        )
        row = await tx.fetch_one(
            """
            SELECT
                (SELECT count(*) FROM lexeme_stats WHERE namespace = %s) AS lexemes,
                COALESCE((SELECT chunk_count FROM lexical_corpus_stats
                          WHERE namespace = %s), 0) AS chunks,
                COALESCE((SELECT total_len FROM lexical_corpus_stats
                          WHERE namespace = %s), 0) AS total_len
            """,
            (namespace, namespace, namespace),
        )
    return {"namespace": namespace, **(row or {})}
