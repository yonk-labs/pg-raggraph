"""Typed graph traversal and dependent conjunctive joins (issue #95).

The embedding-seeded retrieval modes cannot express questions like
"recommend a restaurant for Maria" — where the answer requires binding
facts *about Maria* first (LIVES_IN → city, CRAVES → food) and then
intersecting typed neighbor sets (LOCATED_IN(city) ∩ SERVES(food)).
The adjacency tables contain the answer path; this module makes the
retrieval layer able to return it.

Three primitives, all pure SQL over the existing ``entities`` /
``relationships`` / ``*_chunks`` tables (no schema changes, no app-side
join loops):

- :func:`find_entities` — anchor binding: exact name match + pg_trgm
  fuzzy match, optionally filtered by entity_type.
- :func:`traverse` — typed, directed edge walk (recursive CTE) from a
  set of entity ids, returning each reached entity with the edge that
  reached it and the edge's provenance chunk ids.
- :func:`graph_join` — the dependent conjunctive join: bind variables
  from an anchor via typed edges, then intersect typed neighbor sets of
  those variables. Executed as indexed SQL joins in a single statement;
  the result carries the bound intermediates and every supporting edge.

Rel-type matching is case-insensitive and accepts synonym lists
(e.g. ``["LIKES", "CRAVES"]``). Directions are always expressed from
the perspective of the walk origin: for bind steps the origin is the
anchor (``"out"`` = anchor —rel→ neighbor); for intersect constraints
the origin is the candidate result entity (``"out"`` = candidate —rel→
bound variable). Retracted edges (fact-level evolution) never match.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Sequence

from pg_raggraph.config import PGRGConfig
from pg_raggraph.db import Database

DIRECTIONS = ("out", "in", "any")
MAX_HOPS_CAP = 10
_VAR_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


# --------------------------------------------------------------------------
# Result shapes
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class EntityMatch:
    """An entity bound by :func:`find_entities`.

    ``score`` is 1.0 for exact name matches, else the pg_trgm similarity
    in [0, 1]. ``match_type`` is ``'exact'`` or ``'trgm'``.
    """

    id: int
    name: str
    entity_type: str
    description: str
    score: float
    match_type: str


@dataclass(frozen=True)
class TraversalHop:
    """One entity reached by :func:`traverse`, with the edge that reached it.

    The same entity can appear more than once when distinct paths reach it —
    each row is one (path, edge) pair. ``chunk_ids`` is the provenance of the
    traversed edge (``relationship_chunks``).
    """

    entity_id: int
    name: str
    entity_type: str
    description: str
    depth: int
    rel_id: int
    rel_type: str
    weight: float
    from_id: int
    chunk_ids: tuple[int, ...]


@dataclass(frozen=True)
class BoundValue:
    """An intermediate value bound by a ``bind`` step of :func:`graph_join`."""

    var: str
    entity_id: int
    name: str
    entity_type: str
    description: str
    rel_id: int
    rel_type: str
    weight: float
    edge_chunk_ids: tuple[int, ...]
    entity_chunk_ids: tuple[int, ...]


@dataclass(frozen=True)
class JoinEvidence:
    """One supporting edge for one intersect constraint of a match."""

    constraint_idx: int
    var: str
    var_entity_id: int
    var_name: str
    rel_id: int
    rel_type: str
    weight: float
    edge_chunk_ids: tuple[int, ...]


@dataclass(frozen=True)
class GraphJoinMatch:
    """A candidate entity that satisfied every intersect constraint."""

    entity_id: int
    name: str
    entity_type: str
    description: str
    evidence: tuple[JoinEvidence, ...]
    entity_chunk_ids: tuple[int, ...]


@dataclass(frozen=True)
class GraphJoinResult:
    """Full, explainable result of :func:`graph_join`.

    ``anchor is None`` means the anchor could not be bound (and matches is
    empty). Empty ``bindings[var]`` pinpoints which bind leg failed when
    there are no matches.
    """

    anchor: EntityMatch | None
    bindings: dict[str, list[BoundValue]] = field(default_factory=dict)
    matches: tuple[GraphJoinMatch, ...] = ()

    def chunk_ids(self) -> list[int]:
        """All provenance chunk ids (bindings + evidence + matches), deduped."""
        ids: set[int] = set()
        for values in self.bindings.values():
            for v in values:
                ids.update(v.edge_chunk_ids)
                ids.update(v.entity_chunk_ids)
        for m in self.matches:
            ids.update(m.entity_chunk_ids)
            for ev in m.evidence:
                ids.update(ev.edge_chunk_ids)
        return sorted(ids)


# --------------------------------------------------------------------------
# Plan parsing / validation (pure — unit-testable)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class BindStep:
    rel_types: tuple[str, ...]
    var: str
    direction: str


@dataclass(frozen=True)
class IntersectStep:
    rel_types: tuple[str, ...]
    var: str  # references a BindStep var (given as "$var" by the caller)
    direction: str


def normalize_rel_types(rel_types: str | Sequence[str]) -> tuple[str, ...]:
    """Upper-case and dedupe a rel_type or synonym list. Raises on empty."""
    if isinstance(rel_types, str):
        rel_types = [rel_types]
    out: list[str] = []
    for rt in rel_types:
        if not isinstance(rt, str) or not rt.strip():
            raise ValueError(f"rel_type entries must be non-empty strings, got {rt!r}")
        upper = rt.strip().upper()
        if upper not in out:
            out.append(upper)
    if not out:
        raise ValueError("rel_types must contain at least one relationship type")
    return tuple(out)


def _validate_direction(direction: str) -> str:
    if direction not in DIRECTIONS:
        raise ValueError(f"direction must be one of {DIRECTIONS}, got {direction!r}")
    return direction


def parse_bind_steps(bind: Sequence[tuple]) -> list[BindStep]:
    """Parse ``bind=[("LIVES_IN", "city"), (["LIKES","CRAVES"], "food", "out")]``."""
    if not bind:
        raise ValueError("graph_join requires at least one bind step")
    steps: list[BindStep] = []
    seen: set[str] = set()
    for i, step in enumerate(bind):
        if not isinstance(step, (tuple, list)) or len(step) not in (2, 3):
            raise ValueError(
                f"bind[{i}] must be (rel_types, var) or (rel_types, var, direction), got {step!r}"
            )
        rel_types = normalize_rel_types(step[0])
        var = step[1]
        direction = _validate_direction(step[2]) if len(step) == 3 else "out"
        if not isinstance(var, str) or not _VAR_RE.match(var):
            raise ValueError(f"bind[{i}] variable name {var!r} is not a valid identifier")
        if var in seen:
            raise ValueError(f"bind variable {var!r} declared twice")
        seen.add(var)
        steps.append(BindStep(rel_types, var, direction))
    return steps


def parse_intersect_steps(
    intersect: Sequence[tuple], bind_vars: Sequence[str]
) -> list[IntersectStep]:
    """Parse ``intersect=[("LOCATED_IN", "$city"), ("SERVES", "$food", "out")]``."""
    if not intersect:
        raise ValueError("graph_join requires at least one intersect constraint")
    known = set(bind_vars)
    steps: list[IntersectStep] = []
    for i, step in enumerate(intersect):
        if not isinstance(step, (tuple, list)) or len(step) not in (2, 3):
            raise ValueError(
                f"intersect[{i}] must be (rel_types, '$var') or "
                f"(rel_types, '$var', direction), got {step!r}"
            )
        rel_types = normalize_rel_types(step[0])
        ref = step[1]
        direction = _validate_direction(step[2]) if len(step) == 3 else "out"
        if not isinstance(ref, str) or not ref.startswith("$"):
            raise ValueError(
                f"intersect[{i}] must reference a bind variable as '$name', got {ref!r}"
            )
        var = ref[1:]
        if var not in known:
            raise ValueError(f"intersect[{i}] references undeclared variable {ref!r}")
        steps.append(IntersectStep(rel_types, var, direction))
    return steps


# --------------------------------------------------------------------------
# SQL builders (pure — unit-testable)
# --------------------------------------------------------------------------

# All identifiers below are generated from integer indexes or fixed
# templates; every user-supplied value travels as a bind parameter.

_EDGE_LIVE = "NOT COALESCE(r.retracted, FALSE)"


def _bind_fragments(direction: str) -> tuple[str, str]:
    """(WHERE condition anchored at %(anchor_id)s, neighbor entity expr)."""
    if direction == "out":
        return "r.src_id = %(anchor_id)s", "r.dst_id"
    if direction == "in":
        return "r.dst_id = %(anchor_id)s", "r.src_id"
    return (
        "(r.src_id = %(anchor_id)s OR r.dst_id = %(anchor_id)s)",
        "CASE WHEN r.src_id = %(anchor_id)s THEN r.dst_id ELSE r.src_id END",
    )


def _cand_fragments(direction: str) -> tuple[str, str]:
    """(JOIN condition against bound var b.entity_id, candidate entity expr)."""
    if direction == "out":  # candidate —rel→ $var
        return "r.dst_id = b.entity_id", "r.src_id"
    if direction == "in":  # $var —rel→ candidate
        return "r.src_id = b.entity_id", "r.dst_id"
    return (
        "(r.src_id = b.entity_id OR r.dst_id = b.entity_id)",
        "CASE WHEN r.src_id = b.entity_id THEN r.dst_id ELSE r.src_id END",
    )


def build_traverse_sql(direction: str, typed: bool) -> str:
    """Recursive-CTE SQL for a typed, directed walk from %(entity_ids)s."""
    _validate_direction(direction)
    if direction == "out":
        join_cond, next_expr = "r.src_id = w.entity_id", "r.dst_id"
    elif direction == "in":
        join_cond, next_expr = "r.dst_id = w.entity_id", "r.src_id"
    else:
        join_cond = "(r.src_id = w.entity_id OR r.dst_id = w.entity_id)"
        next_expr = "CASE WHEN r.src_id = w.entity_id THEN r.dst_id ELSE r.src_id END"
    type_filter = "AND upper(r.rel_type) = ANY(%(rel_types)s)" if typed else ""
    return f"""
WITH RECURSIVE walk AS (
    SELECT e.id AS entity_id, 0 AS depth, ARRAY[e.id] AS path,
           NULL::bigint AS rel_id, NULL::text AS rel_type,
           NULL::double precision AS weight, NULL::bigint AS from_id
    FROM entities e
    WHERE e.id = ANY(%(entity_ids)s) AND e.namespace = %(namespace)s
    UNION ALL
    SELECT {next_expr}, w.depth + 1, w.path || {next_expr},
           r.id, r.rel_type, r.weight, w.entity_id
    FROM walk w
    JOIN relationships r ON {join_cond}
    WHERE w.depth < %(max_hops)s
      AND r.namespace = %(namespace)s
      AND {_EDGE_LIVE}
      {type_filter}
      AND NOT ({next_expr} = ANY(w.path))
)
SELECT w.entity_id, w.depth, w.rel_id, w.rel_type, w.weight, w.from_id,
       e.name, e.entity_type, e.description,
       COALESCE((SELECT array_agg(rc.chunk_id ORDER BY rc.chunk_id)
                 FROM relationship_chunks rc
                 WHERE rc.relationship_id = w.rel_id),
                ARRAY[]::bigint[]) AS chunk_ids
FROM walk w
JOIN entities e ON e.id = w.entity_id
WHERE w.depth > 0
ORDER BY w.depth, w.entity_id, w.rel_id
LIMIT %(limit)s
"""


def build_join_sql(binds: Sequence[BindStep], intersects: Sequence[IntersectStep]) -> str:
    """One-statement SQL for the dependent conjunctive join.

    Shape: one ``bind_i`` CTE per bind step (indexed scan on
    ``relationships(src_id|dst_id, rel_type)`` anchored at the anchor id),
    one ``cand_j`` CTE per intersect constraint (indexed join against the
    referenced bind set), an intersection over candidate ids, then a UNION
    of ``'bind'`` rows (the bound intermediates) and ``'match'`` rows (one
    per supporting edge) so the whole join is a single round-trip.
    """
    var_to_idx = {b.var: i for i, b in enumerate(binds)}
    parts: list[str] = []

    for i, b in enumerate(binds):
        cond, entity_expr = _bind_fragments(b.direction)
        parts.append(f"""bind_{i} AS (
    SELECT DISTINCT {entity_expr} AS entity_id, r.id AS rel_id, r.rel_type, r.weight
    FROM relationships r
    WHERE r.namespace = %(namespace)s
      AND {_EDGE_LIVE}
      AND {cond}
      AND upper(r.rel_type) = ANY(%(bind_{i}_types)s)
)""")

    for j, c in enumerate(intersects):
        join_cond, cand_expr = _cand_fragments(c.direction)
        k = var_to_idx[c.var]
        parts.append(f"""cand_{j} AS (
    SELECT DISTINCT {cand_expr} AS candidate_id, b.entity_id AS var_id,
           r.id AS rel_id, r.rel_type, r.weight
    FROM relationships r
    JOIN bind_{k} b ON {join_cond}
    WHERE r.namespace = %(namespace)s
      AND {_EDGE_LIVE}
      AND upper(r.rel_type) = ANY(%(cand_{j}_types)s)
      AND {cand_expr} <> %(anchor_id)s
)""")

    intersection = "\n    ".join(
        f"JOIN (SELECT DISTINCT candidate_id FROM cand_{j}) i{j} USING (candidate_id)"
        for j in range(1, len(intersects))
    )
    parts.append(f"""matched AS (
    SELECT candidate_id
    FROM (SELECT DISTINCT candidate_id FROM cand_0) i0
    {intersection}
    ORDER BY candidate_id
    LIMIT %(match_limit)s
)""")

    bind_rows = "\n    UNION ALL\n    ".join(
        f"SELECT {i} AS step_idx, entity_id, rel_id, rel_type, weight FROM bind_{i}"
        for i in range(len(binds))
    )
    parts.append(f"""bind_rows AS (
    {bind_rows}
)""")

    match_rows = "\n    UNION ALL\n    ".join(
        f"SELECT {j} AS step_idx, c.candidate_id, c.var_id, c.rel_id, c.rel_type, c.weight\n"
        f"    FROM cand_{j} c JOIN matched m ON m.candidate_id = c.candidate_id"
        for j in range(len(intersects))
    )
    parts.append(f"""match_rows AS (
    {match_rows}
)""")

    ctes = ",\n".join(parts)
    return f"""
WITH {ctes}
SELECT 'bind' AS row_kind, b.step_idx, b.entity_id AS entity_id,
       e.name, e.entity_type, e.description,
       b.rel_id, b.rel_type, b.weight,
       NULL::bigint AS var_id, NULL::text AS var_name,
       COALESCE((SELECT array_agg(rc.chunk_id ORDER BY rc.chunk_id)
                 FROM relationship_chunks rc
                 WHERE rc.relationship_id = b.rel_id),
                ARRAY[]::bigint[]) AS edge_chunk_ids,
       COALESCE((SELECT array_agg(ec.chunk_id ORDER BY ec.chunk_id)
                 FROM entity_chunks ec WHERE ec.entity_id = b.entity_id),
                ARRAY[]::bigint[]) AS entity_chunk_ids
FROM bind_rows b
JOIN entities e ON e.id = b.entity_id
UNION ALL
SELECT 'match', m.step_idx, m.candidate_id,
       ce.name, ce.entity_type, ce.description,
       m.rel_id, m.rel_type, m.weight,
       m.var_id, ve.name,
       COALESCE((SELECT array_agg(rc.chunk_id ORDER BY rc.chunk_id)
                 FROM relationship_chunks rc
                 WHERE rc.relationship_id = m.rel_id),
                ARRAY[]::bigint[]),
       COALESCE((SELECT array_agg(ec.chunk_id ORDER BY ec.chunk_id)
                 FROM entity_chunks ec WHERE ec.entity_id = m.candidate_id),
                ARRAY[]::bigint[])
FROM match_rows m
JOIN entities ce ON ce.id = m.candidate_id
JOIN entities ve ON ve.id = m.var_id
ORDER BY row_kind, entity_id, step_idx, rel_id
"""


def build_find_entities_sql(fuzzy: bool, typed: bool) -> str:
    """SQL for anchor binding: exact name + optional pg_trgm fuzzy leg."""
    type_filter = "AND lower(entity_type) = lower(%(entity_type)s)" if typed else ""
    exact = f"""SELECT id, name, entity_type, description,
           1.0::double precision AS score, 'exact' AS match_type
    FROM entities
    WHERE namespace = %(namespace)s AND name = %(name)s {type_filter}"""
    if not fuzzy:
        return f"{exact}\nORDER BY name\nLIMIT %(limit)s"
    return f"""
WITH exact AS (
    {exact}
),
fuzzy AS (
    -- The trgm match operator (%%, psycopg-escaped) is the index-eligible
    -- gate: it drives a Bitmap Index Scan on idx_entity_name_trgm using
    -- pg_trgm.similarity_threshold, which the executor pins to min_score via
    -- set_local (find_entities). similarity() > min_score stays as the exact
    -- gate: the operator matches at >= threshold while the original semantics
    -- were strictly >. A bare similarity() WHERE gate cannot use the GIN
    -- index and seq-scanned 11.5K entities at 31.8ms p50
    -- (benchmarks/age-bakeoff/cap-gold-v1/RESULTS.md). NOTE: psycopg parses
    -- placeholders even in SQL comments, so no bare percent signs here.
    SELECT id, name, entity_type, description,
           similarity(name, %(name)s)::double precision AS score, 'trgm' AS match_type
    FROM entities
    WHERE namespace = %(namespace)s AND name <> %(name)s
      AND name %% %(name)s
      AND similarity(name, %(name)s) > %(min_score)s {type_filter}
    ORDER BY score DESC
    LIMIT %(limit)s
)
SELECT * FROM exact
UNION ALL
SELECT * FROM fuzzy
ORDER BY score DESC, name
LIMIT %(limit)s
"""


# --------------------------------------------------------------------------
# Async executors
# --------------------------------------------------------------------------


async def find_entities(
    db: Database,
    config: PGRGConfig,
    name: str,
    *,
    fuzzy: bool = True,
    entity_type: str | None = None,
    namespace: str,
    limit: int = 5,
    min_score: float | None = None,
) -> list[EntityMatch]:
    """Bind a name to entities: exact match first, then pg_trgm fuzzy.

    ``min_score`` defaults to ``config.min_trgm_score``. pg_trgm similarity
    is case-insensitive, so casing differences land on the fuzzy leg with a
    high score.
    """
    if not name or not name.strip():
        raise ValueError("name must be a non-empty string")
    if limit < 1:
        raise ValueError(f"limit must be >= 1, got {limit}")
    sql = build_find_entities_sql(fuzzy=fuzzy, typed=entity_type is not None)
    params: dict = {
        "namespace": namespace,
        "name": name.strip(),
        "limit": limit,
        "min_score": min_score if min_score is not None else config.min_trgm_score,
    }
    if entity_type is not None:
        params["entity_type"] = entity_type
    # find_entities runs outside any caller transaction (pooled per-call
    # connection), so the trgm threshold rides along as a transaction-local
    # set_config on the same connection/transaction as the query itself.
    set_local = {"pg_trgm.similarity_threshold": str(params["min_score"])} if fuzzy else None
    rows = await db.fetch_all(sql, params, set_local=set_local)
    return [
        EntityMatch(
            id=r["id"],
            name=r["name"],
            entity_type=r["entity_type"],
            description=r["description"] or "",
            score=float(r["score"]),
            match_type=r["match_type"],
        )
        for r in rows
    ]


async def traverse(
    db: Database,
    entity_ids: Sequence[int],
    *,
    rel_types: str | Sequence[str] | None = None,
    direction: str = "out",
    max_hops: int = 1,
    namespace: str,
    limit: int = 200,
) -> list[TraversalHop]:
    """Typed, directed edge walk from ``entity_ids`` (single round-trip)."""
    ids = [int(i) for i in entity_ids]
    if not ids:
        raise ValueError("entity_ids must be non-empty")
    _validate_direction(direction)
    if not 1 <= max_hops <= MAX_HOPS_CAP:
        raise ValueError(f"max_hops must be in 1..{MAX_HOPS_CAP}, got {max_hops}")
    if limit < 1:
        raise ValueError(f"limit must be >= 1, got {limit}")
    typed = rel_types is not None
    sql = build_traverse_sql(direction, typed)
    params: dict = {
        "entity_ids": ids,
        "namespace": namespace,
        "max_hops": max_hops,
        "limit": limit,
    }
    if typed:
        params["rel_types"] = list(normalize_rel_types(rel_types))
    rows = await db.fetch_all(sql, params)
    return [
        TraversalHop(
            entity_id=r["entity_id"],
            name=r["name"],
            entity_type=r["entity_type"],
            description=r["description"] or "",
            depth=r["depth"],
            rel_id=r["rel_id"],
            rel_type=r["rel_type"],
            weight=float(r["weight"]),
            from_id=r["from_id"],
            chunk_ids=tuple(r["chunk_ids"]),
        )
        for r in rows
    ]


async def graph_join(
    db: Database,
    config: PGRGConfig,
    anchor: str | int,
    bind: Sequence[tuple],
    intersect: Sequence[tuple],
    *,
    namespace: str,
    anchor_type: str | None = None,
    fuzzy: bool = True,
    match_limit: int = 50,
) -> GraphJoinResult:
    """Dependent conjunctive join: bind variables from an anchor, intersect.

    Example — "restaurant for Maria" (Maria LIVES_IN city, CRAVES food;
    restaurant LOCATED_IN city AND SERVES food)::

        result = await graph_join(
            db, config, "Maria Ashby",
            bind=[("LIVES_IN", "city"), (["CRAVES", "LIKES"], "food")],
            intersect=[("LOCATED_IN", "$city"), ("SERVES", "$food")],
            namespace="demo",
        )

    ``anchor`` is an entity name (exact + fuzzy bound) or a known entity id.
    An unbindable anchor returns an empty result with ``anchor=None`` rather
    than raising — callers can distinguish "no such person" from "person
    found, no restaurant". The join itself is one SQL round-trip.
    """
    binds = parse_bind_steps(bind)
    intersects = parse_intersect_steps(intersect, [b.var for b in binds])
    if match_limit < 1:
        raise ValueError(f"match_limit must be >= 1, got {match_limit}")

    # --- Anchor binding ----------------------------------------------------
    anchor_match: EntityMatch | None = None
    if isinstance(anchor, bool) or not isinstance(anchor, (int, str)):
        raise ValueError(f"anchor must be an entity name or id, got {anchor!r}")
    if isinstance(anchor, int):
        row = await db.fetch_one(
            "SELECT id, name, entity_type, description FROM entities "
            "WHERE id = %s AND namespace = %s",
            (anchor, namespace),
        )
        if row is not None:
            anchor_match = EntityMatch(
                id=row["id"],
                name=row["name"],
                entity_type=row["entity_type"],
                description=row["description"] or "",
                score=1.0,
                match_type="exact",
            )
    else:
        candidates = await find_entities(
            db,
            config,
            anchor,
            fuzzy=fuzzy,
            entity_type=anchor_type,
            namespace=namespace,
            limit=1,
        )
        anchor_match = candidates[0] if candidates else None

    if anchor_match is None:
        return GraphJoinResult(anchor=None, bindings={b.var: [] for b in binds}, matches=())

    # --- The join: one statement, indexed scans only ------------------------
    sql = build_join_sql(binds, intersects)
    params: dict = {
        "namespace": namespace,
        "anchor_id": anchor_match.id,
        "match_limit": match_limit,
    }
    for i, b in enumerate(binds):
        params[f"bind_{i}_types"] = list(b.rel_types)
    for j, c in enumerate(intersects):
        params[f"cand_{j}_types"] = list(c.rel_types)
    rows = await db.fetch_all(sql, params)

    bindings: dict[str, list[BoundValue]] = {b.var: [] for b in binds}
    by_candidate: dict[int, dict] = {}
    for r in rows:
        if r["row_kind"] == "bind":
            step = binds[r["step_idx"]]
            bindings[step.var].append(
                BoundValue(
                    var=step.var,
                    entity_id=r["entity_id"],
                    name=r["name"],
                    entity_type=r["entity_type"],
                    description=r["description"] or "",
                    rel_id=r["rel_id"],
                    rel_type=r["rel_type"],
                    weight=float(r["weight"]),
                    edge_chunk_ids=tuple(r["edge_chunk_ids"]),
                    entity_chunk_ids=tuple(r["entity_chunk_ids"]),
                )
            )
        else:
            step = intersects[r["step_idx"]]
            slot = by_candidate.setdefault(
                r["entity_id"],
                {
                    "name": r["name"],
                    "entity_type": r["entity_type"],
                    "description": r["description"] or "",
                    "entity_chunk_ids": tuple(r["entity_chunk_ids"]),
                    "evidence": [],
                },
            )
            slot["evidence"].append(
                JoinEvidence(
                    constraint_idx=r["step_idx"],
                    var=step.var,
                    var_entity_id=r["var_id"],
                    var_name=r["var_name"],
                    rel_id=r["rel_id"],
                    rel_type=r["rel_type"],
                    weight=float(r["weight"]),
                    edge_chunk_ids=tuple(r["edge_chunk_ids"]),
                )
            )

    matches = tuple(
        GraphJoinMatch(
            entity_id=eid,
            name=slot["name"],
            entity_type=slot["entity_type"],
            description=slot["description"],
            evidence=tuple(slot["evidence"]),
            entity_chunk_ids=slot["entity_chunk_ids"],
        )
        for eid, slot in sorted(by_candidate.items())
    )
    return GraphJoinResult(anchor=anchor_match, bindings=bindings, matches=matches)
