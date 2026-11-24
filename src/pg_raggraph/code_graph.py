"""Read-side code-intelligence queries over the CODE_SYMBOL graph.

code_impact answers "who calls this symbol" (callers, incoming edges) and "what
does it call" (callees, outgoing edges) by breadth-first traversal of the existing
``relationships`` table. Namespace-scoped; no schema changes. See
docs/superpowers/specs/2026-05-26-code-graph-query-ux-design.md.
"""

from __future__ import annotations

from dataclasses import dataclass

CODE_REL_TYPES = ("CALLS", "INHERITS", "IMPLEMENTS")


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


async def _walk(db, seed_id, namespace, depth, min_confidence, *, incoming):
    """Expand each reached symbol once. Choose a stable edge for equal-depth paths."""
    origin, target = ("dst_id", "src_id") if incoming else ("src_id", "dst_id")
    sql = f"""
        SELECT e.name AS fqn, step.*
        FROM (
            SELECT DISTINCT ON (r.{target}) r.{target} AS node_id, r.rel_type,
                   COALESCE(NULLIF(r.description, ''),
                            r.properties->'evidence'->>'snippet', '') AS evidence
            FROM relationships r
            WHERE r.namespace = %s AND r.{origin} = ANY(%s)
              AND r.rel_type = ANY(%s) AND r.weight >= %s
              AND NOT COALESCE(r.retracted, FALSE)
            ORDER BY r.{target}, r.id
        ) AS step
        JOIN entities e ON e.id = step.node_id AND e.namespace = %s
        ORDER BY e.name
    """
    frontier = [seed_id]
    reached = set()
    edges = []
    for distance in range(1, depth + 1):
        rows = await db.fetch_all(
            sql, (namespace, frontier, list(CODE_REL_TYPES), min_confidence, namespace)
        )
        frontier = []
        for row in rows:
            node_id = row["node_id"]
            if node_id in reached:
                continue
            reached.add(node_id)
            edges.append(CodeEdge(row["fqn"], row["rel_type"], row["evidence"], distance))
            # A cycle may report the seed as a caller/callee, but it has already expanded.
            if node_id != seed_id:
                frontier.append(node_id)
        if not frontier:
            break
    return edges


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
    callees = await _walk(db, seed["id"], namespace, depth, min_confidence, incoming=False)
    callers = await _walk(db, seed["id"], namespace, depth, min_confidence, incoming=True)
    return CodeImpact(fqn=fqn, found=True, callers=callers, callees=callees)


def render_impact_tree(impact: CodeImpact) -> str:
    """Human-readable tree for ``code-impact``. Pure function (no DB)."""
    lines = [impact.fqn]
    for label, edges in (("callers", impact.callers), ("callees", impact.callees)):
        lines.append(f"  {label}:")
        if not edges:
            lines.append("    (none)")
            continue
        for e in edges:
            depth_note = f" (depth {e.depth})" if e.depth > 1 else ""
            ev = f'    "{e.evidence}"' if e.evidence else ""
            lines.append(f"    - {e.fqn}    {e.rel_type}{depth_note}{ev}")
    return "\n".join(lines)
