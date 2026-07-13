"""Set-seeded, authority-scored graph retrieval — the ``graph_analyze`` plan
primitive (issue #100).

The cap-gold-v1 Tier 3 "composed analytics" shape — semantic top-K seed →
typed multi-hop expansion → authority scoring (in-degree over the expanded
set) → structured metadata filter → RRF-fused top-N with provenance —
expresses cleanly as ONE SQL statement (proven in
``benchmarks/age-bakeoff/cap-gold-v1/run_pipelines.py``, ``PGRG_TIER3``),
but no public API call could run it. ``find_entities``/``traverse``/
``graph_join`` stay small and single-purpose; this module adds the
composition as an explicit five-stage plan:

    seed (semantic | ids | name) → expand → score → filter → fuse

Each stage maps 1:1 onto a proven CTE; this is a SQL-template assembler,
not new engine work. Every leg runs on existing indexes:
``relationships(dst_id, rel_type)`` drives the in-degree aggregate,
``entity_chunks`` carries provenance, and the whole plan is a single
round-trip — recursive expansion, aggregation, filtering, and rank fusion
in the same statement as the pgvector seed. (The AGE equivalent needs two
statements: ``cypher()`` cannot consume dynamic CTE seed ids.)

Design note: ``docs/superpowers/specs/2026-07-11-graph-analyze-api-design.md``
(option B). Deliberately minimal: ``in_degree`` is the only authority
metric and RRF the only fusion — add strategies when a second use case
demands one, not before.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from pg_raggraph.config import PGRGConfig
from pg_raggraph.db import Database
from pg_raggraph.graph_join import (
    MAX_HOPS_CAP,
    _validate_direction,
    find_entities,
    normalize_rel_types,
)

# --------------------------------------------------------------------------
# Plan stages (pure dataclasses — unit-testable without a database)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class SemanticSeed:
    """Seed the plan from a semantic top-K: the ``top_k`` nearest chunks to
    ``query`` (embedded via the configured embedder), mapped to their linked
    entities, optionally restricted to one ``entity_type``."""

    query: str
    top_k: int = 60
    entity_type: str | None = None

    def __post_init__(self):
        if not self.query or not self.query.strip():
            raise ValueError("SemanticSeed.query must be a non-empty string")
        if self.top_k < 1:
            raise ValueError(f"SemanticSeed.top_k must be >= 1, got {self.top_k}")


@dataclass(frozen=True)
class NameSeed:
    """Seed from a named entity — exact + pg_trgm fuzzy binding, same
    resolution ``find_entities``/``graph_join`` use."""

    name: str
    entity_type: str | None = None
    fuzzy: bool = True
    limit: int = 5

    def __post_init__(self):
        if not self.name or not self.name.strip():
            raise ValueError("NameSeed.name must be a non-empty string")
        if self.limit < 1:
            raise ValueError(f"NameSeed.limit must be >= 1, got {self.limit}")


@dataclass(frozen=True)
class Expand:
    """Typed, directed expansion from the seed set. Unrolled fixed-hop CTEs
    (the proven Tier 3 shape) — each hop is an indexed join on
    ``relationships(src_id|dst_id, rel_type)``. ``rel_types`` accepts a
    single type or a case-insensitive synonym list."""

    rel_types: str | Sequence[str]
    direction: str = "out"
    max_hops: int = 2

    def __post_init__(self):
        # Normalize eagerly so a bad plan fails at construction, not at SQL
        # time. frozen dataclass → object.__setattr__.
        object.__setattr__(self, "rel_types", normalize_rel_types(self.rel_types))
        _validate_direction(self.direction)
        if not 1 <= self.max_hops <= MAX_HOPS_CAP:
            raise ValueError(f"max_hops must be in 1..{MAX_HOPS_CAP}, got {self.max_hops}")


@dataclass(frozen=True)
class Authority:
    """Authority weighting over the expanded set. ``in_degree`` counts live
    edges of ``rel_types`` (default: the Expand types) pointing INTO each
    neighborhood entity — indexed on ``relationships(dst_id, rel_type)``."""

    metric: str = "in_degree"
    rel_types: str | Sequence[str] | None = None

    def __post_init__(self):
        if self.metric != "in_degree":
            raise ValueError(f"Authority.metric {self.metric!r} not supported (only 'in_degree')")
        if self.rel_types is not None:
            object.__setattr__(self, "rel_types", normalize_rel_types(self.rel_types))


@dataclass(frozen=True)
class MetadataFilter:
    """Hard WHERE filters over ``documents.metadata`` (structured fields
    only — same guard as ``query(metadata_filters={"hard": ...})``).

    Values compare as equality by default; a ``(op, value)`` tuple with op
    in ``gte/gt/lte/lt`` makes a range filter. Numeric values compare
    numerically (``::numeric`` cast); strings compare as text — ISO dates
    and zero-padded ids order correctly as text.
    """

    filters: dict

    _OPS = {"gte": ">=", "gt": ">", "lte": "<=", "lt": "<"}

    def __post_init__(self):
        for field, value in (self.filters or {}).items():
            if isinstance(value, tuple):
                if len(value) != 2 or value[0] not in self._OPS:
                    raise ValueError(
                        f"MetadataFilter[{field!r}]: tuple form is (op, value) "
                        f"with op in {sorted(self._OPS)}, got {value!r}"
                    )


@dataclass(frozen=True)
class RRF:
    """Reciprocal-rank fusion across the plan's score legs. ``semantic`` is
    the seed distance rank (SemanticSeed plans only), ``authority`` the
    aggregate rank. ``k=None`` uses ``config.rrf_k``."""

    legs: tuple[str, ...] = ("semantic", "authority")
    k: int | None = None

    def __post_init__(self):
        bad = set(self.legs) - {"semantic", "authority"}
        if bad or not self.legs:
            raise ValueError(
                f"RRF.legs must be non-empty, from semantic/authority; got {self.legs}"
            )


@dataclass(frozen=True)
class AnalyzedChunk:
    """One fused result row with provenance and per-leg scores.

    ``semantic_score`` is 1 - cosine distance to the seed query (None for
    id/name-seeded plans, and for chunks with no embedding).
    ``authority`` is the aggregate value (in-degree count) of the
    highest-authority neighborhood entity linked to the chunk.
    """

    chunk_id: int
    document_id: int
    source_path: str | None
    content: str
    metadata: dict | None
    semantic_score: float | None
    authority: int
    score: float


# --------------------------------------------------------------------------
# SQL assembly (pure — unit-testable)
# --------------------------------------------------------------------------

_EDGE_LIVE = "NOT COALESCE(r.retracted, FALSE)"


def _hop_fragments(direction: str) -> tuple[str, str]:
    """(JOIN condition against the previous hop alias ``p``, reached-entity
    expr) — same convention as graph_join's bind/cand fragments."""
    if direction == "out":
        return "r.src_id = p.entity_id", "r.dst_id"
    if direction == "in":
        return "r.dst_id = p.entity_id", "r.src_id"
    return (
        "(r.src_id = p.entity_id OR r.dst_id = p.entity_id)",
        "CASE WHEN r.src_id = p.entity_id THEN r.dst_id ELSE r.src_id END",
    )


def _seed_cte(seed: SemanticSeed | Sequence[int]) -> str:
    """The ``seeds`` CTE: one column, ``entity_id``."""
    if isinstance(seed, SemanticSeed):
        type_join = (
            "JOIN entities e ON e.id = ec.entity_id "
            "AND lower(e.entity_type) = lower(%(seed_entity_type)s)"
            if seed.entity_type is not None
            else ""
        )
        return f"""seed_chunks AS (
    SELECT c.id
    FROM chunks c
    JOIN documents d ON d.id = c.document_id
    WHERE d.namespace = %(namespace)s
    ORDER BY c.embedding <=> %(qvec)s::vector
    LIMIT %(seed_top_k)s
),
seeds AS (
    SELECT DISTINCT ec.entity_id
    FROM seed_chunks sc
    JOIN entity_chunks ec ON ec.chunk_id = sc.id
    {type_join}
)"""
    # id seed (NameSeed resolves to ids in Python first)
    return """seeds AS (
    SELECT e.id AS entity_id
    FROM entities e
    WHERE e.id = ANY(%(seed_ids)s) AND e.namespace = %(namespace)s
)"""


def build_analyze_sql(
    seed: SemanticSeed | Sequence[int],
    expand: Expand,
    metadata_where: str,
    fuse_legs: tuple[str, ...],
) -> str:
    """One-statement SQL for the five-stage plan. Mirrors PGRG_TIER3:
    seeds → hop_1..hop_n (unrolled, DISTINCT per hop) → hood → authority
    (targeted in-degree) → cand (chunks + provenance + filter) → RRF."""
    semantic = isinstance(seed, SemanticSeed)

    join_cond, next_expr = _hop_fragments(expand.direction)
    hops = []
    for i in range(1, expand.max_hops + 1):
        prev = "seeds" if i == 1 else f"hop_{i - 1}"
        hops.append(f"""hop_{i} AS (
    SELECT DISTINCT {next_expr} AS entity_id
    FROM relationships r
    JOIN {prev} p ON {join_cond}
    WHERE r.namespace = %(namespace)s AND {_EDGE_LIVE}
      AND upper(r.rel_type) = ANY(%(expand_types)s)
)""")
    hood_union = "\n    UNION SELECT entity_id FROM ".join(
        ["seeds"] + [f"hop_{i}" for i in range(1, expand.max_hops + 1)]
    )

    semantic_col = (
        "1 - (c.embedding <=> %(qvec)s::vector) AS semantic_score,"
        if semantic
        else "NULL::double precision AS semantic_score,"
    )
    filter_clause = f"\n      AND {metadata_where}" if metadata_where else ""

    rrf_terms = []
    if "semantic" in fuse_legs and semantic:
        rrf_terms.append(
            "1.0 / (%(rrf_k)s + RANK() OVER (ORDER BY semantic_score DESC NULLS LAST))"
        )
    if "authority" in fuse_legs:
        rrf_terms.append("1.0 / (%(rrf_k)s + RANK() OVER (ORDER BY authority DESC))")
    rrf_expr = " +\n       ".join(rrf_terms)

    return f"""
WITH {_seed_cte(seed)},
{",".join(hops)},
hood AS (
    SELECT entity_id FROM {hood_union}
),
authority AS (
    -- targeted in-degree: indexed on relationships(dst_id, rel_type)
    SELECT h.entity_id, count(r.id) AS authority
    FROM hood h
    LEFT JOIN relationships r
      ON r.dst_id = h.entity_id
     AND upper(r.rel_type) = ANY(%(authority_types)s)
     AND r.namespace = %(namespace)s AND {_EDGE_LIVE}
    GROUP BY h.entity_id
),
cand AS (
    SELECT DISTINCT ON (c.id)
           c.id AS chunk_id, c.document_id,
           COALESCE(c.embedded_content, c.content) AS content,
           d.source_path, d.metadata AS doc_metadata,
           {semantic_col}
           a.authority
    FROM hood h
    JOIN entity_chunks ec ON ec.entity_id = h.entity_id
    JOIN authority a ON a.entity_id = h.entity_id
    JOIN chunks c ON c.id = ec.chunk_id
    JOIN documents d ON d.id = c.document_id
    WHERE d.namespace = %(namespace)s{filter_clause}
    ORDER BY c.id, a.authority DESC
)
SELECT chunk_id, document_id, content, source_path, doc_metadata,
       semantic_score, authority,
       {rrf_expr} AS score
FROM cand
ORDER BY score DESC
LIMIT %(top_k)s
"""


def build_metadata_where(mf: MetadataFilter | None, config: PGRGConfig) -> tuple[str, dict]:
    """WHERE fragment + params for the filter stage (documents alias ``d``).

    Same structured-field guard as query()'s hard filters: filtering
    free-text metadata silently drops answers on vocab mismatch, so it is
    rejected loudly.
    """
    if mf is None or not mf.filters:
        return "", {}
    allowed = set(config.structured_metadata_fields or [])
    terms: list[str] = []
    params: dict = {}
    for i, (field, value) in enumerate(mf.filters.items()):
        if field not in allowed:
            raise ValueError(
                f"'{field}' is not a structured field; hard-filtering free-text "
                f"metadata silently drops answers. Add it to "
                f"config.structured_metadata_fields or drop the filter."
            )
        op, raw = (
            ("=", value)
            if not isinstance(value, tuple)
            else (
                MetadataFilter._OPS[value[0]],
                value[1],
            )
        )
        key = f"ga_mf_{i}"
        params[f"{key}_f"] = field
        if isinstance(raw, (int, float)) and not isinstance(raw, bool):
            terms.append(f"(d.metadata->>%({key}_f)s)::numeric {op} %({key})s")
            params[key] = raw
        else:
            terms.append(f"d.metadata->>%({key}_f)s {op} %({key})s")
            params[key] = str(raw)
    return " AND ".join(terms), params


# --------------------------------------------------------------------------
# Async executor
# --------------------------------------------------------------------------


async def graph_analyze(
    db: Database,
    config: PGRGConfig,
    embed,
    seed: SemanticSeed | NameSeed | Sequence[int],
    expand: Expand,
    *,
    score: Authority | None = None,
    filter: MetadataFilter | None = None,  # noqa: A002 - mirrors the design-doc API
    fuse: RRF | None = None,
    top_k: int = 10,
    namespace: str,
) -> list[AnalyzedChunk]:
    """Execute the five-stage plan in one SQL round-trip (plus one embedding
    call for SemanticSeed / one binding query for NameSeed).

    ``embed`` is an async callable ``str -> list[float]`` (the GraphRAG
    wrapper passes the configured embedder); only consulted for
    SemanticSeed plans.
    """
    if top_k < 1:
        raise ValueError(f"top_k must be >= 1, got {top_k}")
    score = score or Authority()
    fuse = fuse or RRF()
    if not isinstance(seed, SemanticSeed) and "authority" not in fuse.legs:
        raise ValueError(
            "fuse legs must include 'authority' for id/name-seeded plans — "
            "the semantic leg only exists under a SemanticSeed"
        )

    params: dict = {
        "namespace": namespace,
        "top_k": top_k,
        "rrf_k": fuse.k if fuse.k is not None else config.rrf_k,
        "expand_types": list(expand.rel_types),
        "authority_types": list(score.rel_types or expand.rel_types),
    }

    if isinstance(seed, SemanticSeed):
        params["qvec"] = await embed(seed.query)
        params["seed_top_k"] = seed.top_k
        if seed.entity_type is not None:
            params["seed_entity_type"] = seed.entity_type
        sql_seed: SemanticSeed | Sequence[int] = seed
    elif isinstance(seed, NameSeed):
        matches = await find_entities(
            db,
            config,
            seed.name,
            fuzzy=seed.fuzzy,
            entity_type=seed.entity_type,
            namespace=namespace,
            limit=seed.limit,
        )
        if not matches:
            return []
        params["seed_ids"] = [m.id for m in matches]
        sql_seed = params["seed_ids"]
    else:
        ids = [int(i) for i in seed]
        if not ids:
            raise ValueError("seed entity_ids must be non-empty")
        params["seed_ids"] = ids
        sql_seed = ids

    metadata_where, mf_params = build_metadata_where(filter, config)
    params.update(mf_params)

    sql = build_analyze_sql(sql_seed, expand, metadata_where, fuse.legs)
    rows = await db.fetch_all(sql, params)
    return [
        AnalyzedChunk(
            chunk_id=r["chunk_id"],
            document_id=r["document_id"],
            source_path=r["source_path"],
            content=r["content"],
            metadata=(r["doc_metadata"] or None),
            semantic_score=(
                float(r["semantic_score"]) if r["semantic_score"] is not None else None
            ),
            authority=int(r["authority"]),
            score=float(r["score"]),
        )
        for r in rows
    ]
