"""Bridge chunkshop into ``GraphRAG`` ingest.

Two shapes (see ``docs/cookbook/chunkshop-integration.md``):

- **Pattern C** — chunkshop runs its own pipeline and writes a Postgres sink
  (chunks + a ``code_edges`` table); pg-raggraph consumes the stored rows through
  the ``pre_chunked`` ingest seam and ``code_edges_to_known_graph``.
- **Pattern D** (in-process) — pg-raggraph drives chunkshop's ``symbol_aware``
  chunker itself; ``extract_symbol_graph`` runs chunkshop's
  ``CodeRelationshipsExtractor`` over the produced chunks to attach per-chunk
  ``callees`` and resolve ``CALLS``/``INHERITS``/``IMPLEMENTS`` edges, which then
  flow through the same ``code_edges_to_known_graph`` seam.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
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
    summaries: dict[str, str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Convert chunkshop ``code_edges`` rows into known entities/relationships.

    The returned tuple is ``(entities, relationships)`` and can be merged into
    a record before calling ``GraphRAG.ingest_records``.

    Pass *summaries* (fqn -> summary string) to enrich ``CODE_SYMBOL`` entity
    descriptions beyond the default ``"Code symbol {fqn}"`` fallback.
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
                    "description": (summaries or {}).get(fqn) or f"Code symbol {fqn}",
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


@dataclass
class SymbolGraph:
    """Output of :func:`extract_symbol_graph`.

    ``callees_by_index`` is parallel to the input ``cs_chunks`` — entry ``i`` is
    the per-chunk callee list (``{name, line, snippet, resolved_intra_file}``) for
    chunk ``i`` (#74). ``edges`` is the raw ``finalize()`` edge list (#75),
    key-compatible with :func:`code_edges_to_known_graph`.
    """

    callees_by_index: list[list[dict[str, Any]]] = field(default_factory=list)
    edges: list[dict[str, Any]] = field(default_factory=list)


class CorpusCodeGraph:
    """Corpus-wide cross-file code-symbol resolver (#76).

    chunkshop resolves a call by matching its bare name against the symbols a
    *single* extractor instance has accumulated. The per-document extractor in
    :func:`extract_symbol_graph` therefore only resolves intra-file calls. This
    holder owns **one** extractor for a whole ``ingest_records`` batch so calls
    resolve across files.

    **Memory (the #76 OOM fix, v0.5.0a13).** chunkshop accumulates one entry per
    call site (each with a source ``snippet``) in ``extractor._pending_calls`` —
    O(call-sites), ~3.6 GB at 100k files. So :meth:`accumulate` keeps only the
    small **symbol index** in the extractor and **returns each doc's call sites
    for the caller to spill to the DB**, clearing them from memory. Resolution
    then streams those calls back in bounded batches via :meth:`resolve_batch`
    (verified byte-identical to a single ``finalize()``), plus a one-shot
    :meth:`resolve_class_edges` for the far-smaller INHERITS/IMPLEMENTS set.
    Peak memory is O(batch + symbol index), not O(corpus call sites).

    ``accumulate`` is serialized by a lock because ``extract()`` mutates shared
    state and docs are ingested concurrently; it is ~ms of tree-sitter, so
    contention is negligible (embedding stays outside the lock).
    """

    def __init__(self) -> None:
        import asyncio

        self._lock = asyncio.Lock()
        self._n = 0
        try:
            from chunkshop.config import CodeRelationshipsExtractor as _CodeRelCfg
            from chunkshop.extractors import load_extractor

            self._ext = load_extractor(_CodeRelCfg(type="code_relationships"))
        except (ImportError, AttributeError, TypeError, ValueError):
            self._ext = None
        if self._ext is not None and not (
            callable(getattr(self._ext, "extract", None))
            and callable(getattr(self._ext, "finalize", None))
        ):
            self._ext = None
        # Spill needs to read/swap the extractor's pending-call/class-edge lists.
        # Feature-guard the private attrs: if a chunkshop build lacks them we
        # degrade to in-memory accumulation (correct, just not OOM-bounded).
        self._spillable = self._ext is not None and all(
            isinstance(getattr(self._ext, attr, None), list)
            for attr in ("_pending_calls", "_pending_class_edges")
        )

    @property
    def available(self) -> bool:
        """False when the installed chunkshop lacks the extractor (degrade)."""
        return self._ext is not None

    @property
    def spillable(self) -> bool:
        """True when call sites can be spilled to keep memory O(batch). False
        means the chunkshop build lacks the internal lists — accumulation stays
        in memory (the pre-a13 behavior)."""
        return self._spillable

    @property
    def count(self) -> int:
        """Number of documents accumulated."""
        return self._n

    async def accumulate(
        self, content: str, *, source_path: str | None = None, language: str | None = None
    ) -> list[dict[str, Any]]:
        """Parse one doc into the shared symbol index. Returns this doc's call
        sites (for the caller to spill to the DB) and drops them from the
        in-memory extractor, so resolver memory stays O(symbol index). Returns
        ``[]`` when unavailable, or when not spillable (calls then remain in the
        extractor for a single end-of-ingest resolve)."""
        if self._ext is None:
            return []
        async with self._lock:
            self._ext.extract(content or "", source_path=source_path, language=language)
            self._n += 1
            if not self._spillable:
                return []
            calls = list(self._ext._pending_calls)
            self._ext._pending_calls.clear()
            return calls

    def resolve_batch(self, calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Resolve a batch of spilled call sites against the accumulated symbol
        index → ``CALLS`` edges (key-compatible with
        :func:`code_edges_to_known_graph`). Class edges are excluded here and
        emitted once by :meth:`resolve_class_edges`."""
        if self._ext is None:
            return []
        if not self._spillable:
            return []
        self._ext._pending_calls = list(calls)
        saved = self._ext._pending_class_edges
        self._ext._pending_class_edges = []
        try:
            return list(self._ext.finalize(project_id="corpus"))
        finally:
            self._ext._pending_class_edges = saved

    def resolve_class_edges(self) -> list[dict[str, Any]]:
        """Resolve the accumulated INHERITS/IMPLEMENTS edges once (their count is
        O(classes), not O(call-sites), so they need no spill). Run after the call
        batches."""
        if self._ext is None:
            return []
        if self._spillable:
            self._ext._pending_calls = []
        return list(self._ext.finalize(project_id="corpus"))

    def finalize(self, *, project_id: str = "corpus") -> list[dict[str, Any]]:
        """Non-spill fallback: resolve everything still held in the extractor in
        one pass. Used only when :attr:`spillable` is False (older chunkshop)."""
        if self._ext is None:
            return []
        return list(self._ext.finalize(project_id=project_id or "corpus"))


def _bucket_callees(
    callees: list[dict[str, Any]], cs_chunks
) -> list[list[dict[str, Any]]]:
    """Assign whole-file callees to chunks by line span (narrowest wins).

    Each callee carries a 1-based ``line``; each chunk carries ``start_line`` /
    ``end_line``. A callee lands in the narrowest chunk span that contains its
    line, so a call inside a method lands on the method chunk, not its enclosing
    class chunk. Callees with no line, or outside every span, are dropped.
    """
    spans: list[tuple[int | None, int | None]] = [
        ((cs.metadata or {}).get("start_line"), (cs.metadata or {}).get("end_line"))
        for cs in cs_chunks
    ]
    buckets: list[list[dict[str, Any]]] = [[] for _ in cs_chunks]
    for callee in callees:
        line = callee.get("line")
        if line is None:
            continue
        best_i: int | None = None
        best_width: int | None = None
        for i, (start, end) in enumerate(spans):
            if start is None or end is None or not (start <= line <= end):
                continue
            width = end - start
            if best_width is None or width < best_width:
                best_i, best_width = i, width
        if best_i is not None:
            buckets[best_i].append(callee)
    return buckets


def extract_symbol_graph(
    content: str,
    cs_chunks,
    *,
    source_path: str | None = None,
    language: str | None = None,
    project_id: str = "doc",
) -> "SymbolGraph | None":
    """Run chunkshop's CodeRelationshipsExtractor over a code document.

    Parses the *whole document* once (not per chunk): per-chunk parsing
    misattributes class inheritance to the innermost method and can drop the
    class symbol entirely, whereas a whole-file parse builds the real scope tree.
    ``finalize()`` then resolves the accumulated calls/inheritance into edges
    (#75). Per-chunk callees (#74) are recovered by bucketing the whole-file call
    sites into chunk line spans via :func:`_bucket_callees`.

    Per-file scope (one call per document). Returns ``None`` when the installed
    chunkshop lacks the extractor, so older builds degrade gracefully (callees
    absent, no code graph, no crash).

    Correct results require chunkshop's tree-sitter parse path; the regex
    fallback collapses symbol spans and starves call extraction.
    """
    try:
        from chunkshop.config import CodeRelationshipsExtractor as _CodeRelCfg
        from chunkshop.extractors import load_extractor

        extractor = load_extractor(_CodeRelCfg(type="code_relationships"))
    except (ImportError, AttributeError, TypeError, ValueError):
        return None
    if not callable(getattr(extractor, "extract", None)) or not callable(
        getattr(extractor, "finalize", None)
    ):
        return None

    if language is None:
        for cs in cs_chunks:
            lang = (cs.metadata or {}).get("language")
            if lang:
                language = lang
                break

    result = extractor.extract(content or "", source_path=source_path, language=language)
    whole_callees = list((result.metadata or {}).get("callees", []))
    edges = list(extractor.finalize(project_id=project_id or "doc"))
    return SymbolGraph(
        callees_by_index=_bucket_callees(whole_callees, cs_chunks),
        edges=edges,
    )


def attach_code_edges(
    records: list[dict[str, Any]],
    edge_rows: Iterable[dict[str, Any]],
    *,
    min_confidence: float = 0.0,
    summaries: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Attach code-edge entities/relationships to the first ingest record.

    pg-raggraph's known relationships are document-level and only need one
    chunk anchor for graph traversal. Keeping all imported code edges on the
    first record avoids duplicating cross-file edges on every source file.

    When *summaries* is ``None`` (the default) it is derived automatically from
    ``pre_chunked`` chunk metadata in *records* via :func:`summaries_by_fqn`.
    """
    if summaries is None:
        summaries = summaries_by_fqn(records)
    entities, relationships = code_edges_to_known_graph(
        edge_rows,
        min_confidence=min_confidence,
        summaries=summaries,
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


def summaries_by_fqn(records: Iterable[dict[str, Any]]) -> dict[str, str]:
    """Map fqn -> summary from imported chunk metadata.

    Scans each record's ``pre_chunked`` chunks; includes only chunks whose
    metadata carries BOTH ``fqn`` and a non-empty ``summary`` (chunkshop's
    symbol_aware chunker + code_summary extractor).
    """
    out: dict[str, str] = {}
    for record in records:
        for chunk in record.get("pre_chunked") or []:
            meta = chunk.get("metadata") or {}
            fqn = meta.get("fqn")
            summary = meta.get("summary")
            if fqn and summary:
                out[str(fqn)] = str(summary)
    return out


def fetch_code_edges_from_table(
    dsn: str,
    *,
    schema: str,
    project_id: str | None = None,
    min_confidence: float = 0.0,
    summaries: dict[str, str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Read ``<schema>.code_edges`` and return known graph payloads.

    Pass *summaries* (fqn -> summary string) to enrich ``CODE_SYMBOL`` entity
    descriptions.  Typically derived via :func:`summaries_by_fqn` before calling
    this function.
    """
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
        reg = conn.execute("SELECT to_regclass(%s) AS t", (f"{schema}.code_edges",)).fetchone()
        if not reg or not reg["t"]:
            raise ValueError(
                f"chunkshop code_edges table '{schema}.code_edges' not found. "
                "Importing code edges requires a chunkshop>=0.6.0 sink produced with "
                "the code_relationships extractor (its finalize() materializes "
                f"{schema}.code_edges). Re-run chunkshop ingest with code_relationships "
                "enabled, or omit --with-code-edges."
            )
        rows = list(conn.execute(query, params).fetchall())
    return code_edges_to_known_graph(rows, min_confidence=min_confidence, summaries=summaries)


__all__ = [
    "CorpusCodeGraph",
    "SymbolGraph",
    "attach_code_edges",
    "code_edges_to_known_graph",
    "extract_symbol_graph",
    "fetch_code_edges_from_table",
    "fetch_records_from_table",
    "rows_to_records",
    "summaries_by_fqn",
]
