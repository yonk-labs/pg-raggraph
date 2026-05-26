"""Bridge chunkshop Postgres sink rows into ``GraphRAG.ingest_records``.

This is Pattern C from ``docs/cookbook/chunkshop-integration.md``:
chunkshop owns source/connectors/parsers/chunking/embedding/extractors,
then pg-raggraph consumes the stored chunks through its existing
``pre_chunked`` ingest seam.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _validate_ident(value: str, *, kind: str) -> None:
    if not _IDENT_RE.match(value):
        raise ValueError(f"{kind} must match {_IDENT_RE.pattern}, got {value!r}")


def _parse_embedding(value: Any) -> list[float]:
    """Normalize pgvector / numpy / list embeddings to ``list[float]``."""
    if value is None:
        raise ValueError("chunkshop row has NULL embedding — required for pre_chunked ingest")
    if isinstance(value, str):
        s = value.strip()
        if not (s.startswith("[") and s.endswith("]")):
            raise ValueError(f"pgvector text format must be '[v1,v2,...]', got: {s[:40]!r}...")
        return [float(x) for x in s[1:-1].split(",") if x.strip()]
    return [float(x) for x in value]


def _row_metadata(row: dict[str, Any]) -> dict[str, Any]:
    meta = dict(row.get("metadata") or {})
    tags = row.get("tags")
    if tags is not None:
        meta.setdefault("tags", list(tags))
    meta.setdefault("chunkshop_doc_id", row["doc_id"])
    meta.setdefault("chunkshop_seq_num", row["seq_num"])
    if row.get("source") is not None:
        meta.setdefault("chunkshop_source", row["source"])
    return meta


def rows_to_records(
    rows: Iterable[dict[str, Any]],
    *,
    source_prefix: str = "chunkshop",
    skip_llm: bool = False,
) -> list[dict[str, Any]]:
    """Group chunkshop sink rows by ``doc_id`` for ``ingest_records``.

    Expected row keys mirror chunkshop's canonical sink shape:
    ``doc_id``, ``seq_num``, ``original_content``, ``embedded_content``,
    ``embedding``, ``metadata``, ``tags``, and optional ``source``.
    """
    by_doc: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        doc_id = row.get("doc_id")
        if not doc_id:
            raise ValueError("chunkshop row missing 'doc_id' — required for grouping")
        by_doc.setdefault(str(doc_id), []).append(row)

    records: list[dict[str, Any]] = []
    for doc_id, doc_rows in by_doc.items():
        doc_rows.sort(key=lambda r: r.get("seq_num") or 0)
        pre_chunked = []
        for row in doc_rows:
            body = row.get("original_content")
            if body is None:
                raise ValueError("chunkshop row missing 'original_content'")
            pre_chunked.append(
                {
                    "content": body,
                    "embedded_content": row.get("embedded_content") or body,
                    "embedding": _parse_embedding(row.get("embedding")),
                    "metadata": _row_metadata(row),
                }
            )

        text = "\n\n".join(c["content"] for c in pre_chunked)
        record = {
            "text": text,
            "source_id": f"{source_prefix}:{doc_id}",
            "metadata": {
                "source": "chunkshop",
                "chunkshop_doc_id": doc_id,
            },
            "pre_chunked": pre_chunked,
        }
        if skip_llm:
            record["skip_llm"] = True
        records.append(record)
    return records


def code_edges_to_known_graph(
    rows: Iterable[dict[str, Any]],
    *,
    min_confidence: float = 0.0,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Convert chunkshop ``code_edges`` rows into known entities/relationships.

    The returned tuple is ``(entities, relationships)`` and can be merged into
    a record before calling ``GraphRAG.ingest_records``.
    """
    entities_by_name: dict[str, dict[str, Any]] = {}
    relationships: list[dict[str, Any]] = []
    for row in rows:
        confidence = float(row.get("confidence", 1.0))
        if confidence < min_confidence:
            continue
        src = row.get("src_fqn")
        dst = row.get("dst_fqn")
        if not (src and dst):
            raise ValueError("code_edges row must include non-empty 'src_fqn' and 'dst_fqn'")

        for fqn, node_key in ((src, "src_node_id"), (dst, "dst_node_id")):
            entities_by_name.setdefault(
                fqn,
                {
                    "name": fqn,
                    "entity_type": "CODE_SYMBOL",
                    "description": f"Code symbol {fqn}",
                    "properties": {
                        "chunkshop_node_id": row.get(node_key),
                        "source": "chunkshop_code_edges",
                    },
                },
            )

        evidence = dict(row.get("evidence") or {})
        description = evidence.get("snippet") or evidence.get("resolution") or ""
        relationships.append(
            {
                "src": src,
                "dst": dst,
                "rel_type": row.get("edge_type", "CALLS"),
                "description": description,
                "weight": confidence,
                "properties": {
                    "source": "chunkshop_code_edges",
                    "project_id": row.get("project_id"),
                    "src_node_id": row.get("src_node_id"),
                    "dst_node_id": row.get("dst_node_id"),
                    "evidence": evidence,
                },
            }
        )
    return list(entities_by_name.values()), relationships


def attach_code_edges(
    records: list[dict[str, Any]],
    edge_rows: Iterable[dict[str, Any]],
    *,
    min_confidence: float = 0.0,
) -> list[dict[str, Any]]:
    """Attach code-edge entities/relationships to the first ingest record.

    pg-raggraph's known relationships are document-level and only need one
    chunk anchor for graph traversal. Keeping all imported code edges on the
    first record avoids duplicating cross-file edges on every source file.
    """
    entities, relationships = code_edges_to_known_graph(
        edge_rows,
        min_confidence=min_confidence,
    )
    if not entities and not relationships:
        return records
    if not records:
        raise ValueError("cannot attach code_edges without at least one chunkshop record")
    first = records[0]
    first.setdefault("entities", []).extend(entities)
    first.setdefault("relationships", []).extend(relationships)
    return records


def fetch_records_from_table(
    dsn: str,
    *,
    schema: str,
    table: str,
    source_prefix: str = "chunkshop",
    skip_llm: bool = False,
) -> list[dict[str, Any]]:
    """Read a chunkshop Postgres sink table and return ingest records."""
    _validate_ident(schema, kind="schema")
    _validate_ident(table, kind="table")

    import psycopg
    from psycopg import sql
    from psycopg.rows import dict_row

    fq = sql.SQL("{}.{}").format(sql.Identifier(schema), sql.Identifier(table))
    query = sql.SQL(
        "SELECT doc_id, seq_num, original_content, embedded_content, "
        "embedding::text AS embedding, metadata, tags, source "
        "FROM {fq} ORDER BY doc_id, seq_num"
    ).format(fq=fq)

    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        rows = list(conn.execute(query).fetchall())
    return rows_to_records(rows, source_prefix=source_prefix, skip_llm=skip_llm)


def fetch_code_edges_from_table(
    dsn: str,
    *,
    schema: str,
    project_id: str | None = None,
    min_confidence: float = 0.0,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Read ``<schema>.code_edges`` and return known graph payloads."""
    _validate_ident(schema, kind="schema")

    import psycopg
    from psycopg import sql
    from psycopg.rows import dict_row

    fq = sql.SQL("{}.{}").format(sql.Identifier(schema), sql.Identifier("code_edges"))
    where = sql.SQL("WHERE confidence >= %s")
    params: list[Any] = [min_confidence]
    if project_id is not None:
        where = sql.SQL("WHERE confidence >= %s AND project_id = %s")
        params.append(project_id)
    query = sql.SQL(
        "SELECT project_id, edge_type, src_fqn, dst_fqn, src_node_id, "
        "dst_node_id, confidence, evidence FROM {fq} {where} "
        "ORDER BY project_id, edge_type, src_fqn, dst_fqn"
    ).format(fq=fq, where=where)

    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        reg = conn.execute(
            "SELECT to_regclass(%s) AS t", (f"{schema}.code_edges",)
        ).fetchone()
        if not reg or not reg["t"]:
            raise ValueError(
                f"chunkshop code_edges table '{schema}.code_edges' not found. "
                "Importing code edges requires a chunkshop>=0.6.0 sink produced with "
                "the code_relationships extractor (its finalize() materializes "
                f"{schema}.code_edges). Re-run chunkshop ingest with code_relationships "
                "enabled, or omit --with-code-edges."
            )
        rows = list(conn.execute(query, params).fetchall())
    return code_edges_to_known_graph(rows, min_confidence=min_confidence)


__all__ = [
    "attach_code_edges",
    "code_edges_to_known_graph",
    "fetch_code_edges_from_table",
    "fetch_records_from_table",
    "rows_to_records",
]
