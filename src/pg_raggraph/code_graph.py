"""Read-side code-intelligence queries over the CODE_SYMBOL graph.

code_impact answers "who calls this symbol" (callers, incoming edges) and "what
does it call" (callees, outgoing edges) by recursive traversal of the existing
``relationships`` table. Namespace-scoped; no schema changes. See
docs/superpowers/specs/2026-05-26-code-graph-query-ux-design.md.
"""

from __future__ import annotations

from dataclasses import dataclass

CODE_REL_TYPES = ("CALLS", "INHERITS", "IMPLEMENTS")

# Outgoing walk (callees): start at edges where src_id = seed; the "other" node
# is dst_id; follow dst_id -> next src_id. Cycle guard on src_id path.
_CALLEES_SQL = """
WITH RECURSIVE walk AS (
    SELECT r.dst_id AS other_id, r.rel_type,
           COALESCE(NULLIF(r.description, ''),
                    r.properties->'evidence'->>'snippet', '') AS evidence,
           1 AS depth, ARRAY[r.src_id] AS path
    FROM relationships r
    WHERE r.namespace = %(ns)s AND r.src_id = %(seed)s
      AND r.rel_type = ANY(%(rel_types)s) AND r.weight >= %(min_conf)s
      AND NOT COALESCE(r.retracted, FALSE)
  UNION ALL
    SELECT r.dst_id, r.rel_type,
           COALESCE(NULLIF(r.description, ''),
                    r.properties->'evidence'->>'snippet', ''),
           w.depth + 1, w.path || r.src_id
    FROM relationships r
    JOIN walk w ON r.src_id = w.other_id
    WHERE r.namespace = %(ns)s AND w.depth < %(depth)s
      AND r.rel_type = ANY(%(rel_types)s) AND r.weight >= %(min_conf)s
      AND NOT COALESCE(r.retracted, FALSE)
      AND NOT (r.src_id = ANY(w.path))
)
SELECT e.name AS fqn, walk.rel_type, walk.evidence, walk.depth
FROM walk JOIN entities e ON e.id = walk.other_id
ORDER BY walk.depth, e.name
"""

# Incoming walk (callers): start at edges where dst_id = seed; the "other" node
# is src_id; follow src_id -> next dst_id. Cycle guard on dst_id path.
_CALLERS_SQL = """
WITH RECURSIVE walk AS (
    SELECT r.src_id AS other_id, r.rel_type,
           COALESCE(NULLIF(r.description, ''),
                    r.properties->'evidence'->>'snippet', '') AS evidence,
           1 AS depth, ARRAY[r.dst_id] AS path
    FROM relationships r
    WHERE r.namespace = %(ns)s AND r.dst_id = %(seed)s
      AND r.rel_type = ANY(%(rel_types)s) AND r.weight >= %(min_conf)s
      AND NOT COALESCE(r.retracted, FALSE)
  UNION ALL
    SELECT r.src_id, r.rel_type,
           COALESCE(NULLIF(r.description, ''),
                    r.properties->'evidence'->>'snippet', ''),
           w.depth + 1, w.path || r.dst_id
    FROM relationships r
    JOIN walk w ON r.dst_id = w.other_id
    WHERE r.namespace = %(ns)s AND w.depth < %(depth)s
      AND r.rel_type = ANY(%(rel_types)s) AND r.weight >= %(min_conf)s
      AND NOT COALESCE(r.retracted, FALSE)
      AND NOT (r.dst_id = ANY(w.path))
)
SELECT e.name AS fqn, walk.rel_type, walk.evidence, walk.depth
FROM walk JOIN entities e ON e.id = walk.other_id
ORDER BY walk.depth, e.name
"""


@dataclass
class CodeEdge:
    fqn: str
    rel_type: str
    evidence: str
    depth: int


@dataclass
class CodeImpact:
    fqn: str
    found: bool
    callers: list[CodeEdge]
    callees: list[CodeEdge]


def _dedupe(rows) -> list[CodeEdge]:
    """Keep the first (shallowest, name-sorted) edge per fqn."""
    seen: set[str] = set()
    out: list[CodeEdge] = []
    for r in rows:
        if r["fqn"] in seen:
            continue
        seen.add(r["fqn"])
        out.append(CodeEdge(fqn=r["fqn"], rel_type=r["rel_type"],
                            evidence=r["evidence"] or "", depth=r["depth"]))
    return out


async def code_impact(
    db, fqn: str, *, namespace: str, depth: int = 1, min_confidence: float = 0.0
) -> CodeImpact:
    if depth < 1:
        raise ValueError(f"depth must be >= 1, got {depth}")
    seed = await db.fetch_one(
        "SELECT id FROM entities "
        "WHERE namespace = %s AND name = %s AND entity_type = 'CODE_SYMBOL'",
        (namespace, fqn),
    )
    if not seed:
        return CodeImpact(fqn=fqn, found=False, callers=[], callees=[])
    params = {
        "ns": namespace,
        "seed": seed["id"],
        "rel_types": list(CODE_REL_TYPES),
        "min_conf": min_confidence,
        "depth": depth,
    }
    callees = _dedupe(await db.fetch_all(_CALLEES_SQL, params))
    callers = _dedupe(await db.fetch_all(_CALLERS_SQL, params))
    return CodeImpact(fqn=fqn, found=True, callers=callers, callees=callees)
