"""Bridge: chunkshop SP-A `agent_memory.memory` → pg-raggraph `ingest_records`.

SP-B "agent-memory read bridge" (issue #4). Reuses the existing
`pre_chunked` + `relationships` + `skip_llm=True` seams on
``GraphRAG.ingest_records()`` — no new ingest API. The bridge's job is
to map SP-A row shape to pg-raggraph record shape, group by session,
and stamp ``tier`` (+ other SP-A provenance) onto each chunk's
``metadata`` so the read-side ``memory_tier`` filter applies.

See ``docs/cookbook/chunkshop-integration.md`` → Pattern M for the full
narrative and the runnable example in
``benchmarks/agent-memory-demo/ingest_chunkshop_sp_a.py``.

This module is intentionally pure-Python and DB-agnostic: it transforms
in-memory dicts. Callers fetch from chunkshop's table however they
want (psycopg, asyncpg, ORM) and pipe rows through ``rows_to_records``.

Contract reference: chunkshop SP-A design spec
``docs/superpowers/specs/2026-05-19-chunkshop-memory-primitives-sp-a-design.md``
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any

# The canonical SP-A v1 column set the bridge reads. Mirrored by
# chunkshop's `test_pgraggraph_contract_columns_present` — drift on
# either side fails CI on both sides. See
# tests/unit/test_sp_a_memory_contract.py.
SP_A_MEMORY_COLUMNS: frozenset[str] = frozenset({
    # Identity / classification
    "session_id",
    "tier",
    "kind",
    # Episode payload (pgvector shape)
    "doc_id",
    "seq_num",
    "original_content",
    "embedded_content",
    "embedding",
    "metadata",
    # Fact payload — populated when kind='fact'
    "subject",
    "predicate",
    "object",
    "support_span",
    "confidence",  # promoted as text by SP-A; parsed to float in this bridge
    "source_chunk_seq",  # parent episode's seq_num (fact → episode pointer)
    # Bi-temporal
    "effective_from",
    "effective_to",
    # Soft-invalidation
    "retracted",
    "retracted_at",
    # Provenance
    "extractor",
    "namespace",
    "recorded_at",
})

KIND_EPISODE = "episode"
KIND_FACT = "fact"


def _iso(value: Any) -> str | None:
    """Render datetime-ish values to ISO strings for JSONB-safe metadata."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _parse_confidence(value: Any) -> float | None:
    """SP-A promotes `confidence` as text — coerce to float for ranking use.

    Returns None on null / unparseable values so the bridge doesn't blow up
    on a malformed row (which would otherwise abort the whole ingest_records
    batch). Sparse extractive triples often omit confidence entirely.
    """
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_embedding(value: Any) -> list[float]:
    """Normalize a pgvector embedding to ``list[float]``.

    pgvector's `vector` column comes back from psycopg as a string in the
    form ``"[v1,v2,...]"`` unless the caller registered
    ``pgvector.psycopg.register_vector`` (which yields a numpy array). The
    bridge handles both shapes so consumers don't need the adapter.

    Raises ValueError if the input is neither a sequence nor a parseable
    pgvector string — a malformed embedding aborts ingest by design,
    since silently truncating to an empty embedding would produce
    unranked chunks.
    """
    if value is None:
        raise ValueError("SP-A memory row has NULL embedding — required field")
    if isinstance(value, str):
        s = value.strip()
        if not (s.startswith("[") and s.endswith("]")):
            raise ValueError(
                f"pgvector text format must be '[v1,v2,...]', got: {s[:40]!r}..."
            )
        return [float(x) for x in s[1:-1].split(",") if x.strip()]
    return [float(x) for x in value]


def _row_to_pre_chunked(row: dict[str, Any]) -> dict[str, Any]:
    """Map one SP-A memory row to a ``pre_chunked`` entry.

    The SP-A row's `embedding`, `original_content`, `embedded_content` go
    straight through. Per-row provenance (`tier`, `kind`, `effective_from`
    etc.) is stamped onto the chunk's metadata so the read-side
    ``memory_tier`` filter can apply, and so callers can introspect via
    ``ChunkResult.metadata``.
    """
    upstream_meta = dict(row.get("metadata") or {})
    # SP-A's promoted columns are authoritative; let them override anything
    # already in the chunkshop metadata jsonb of the same name.
    upstream_meta.update({
        "session_id": row["session_id"],
        "tier": row["tier"],
        "kind": row["kind"],
        "effective_from": _iso(row.get("effective_from")),
        "effective_to": _iso(row.get("effective_to")),
        "retracted": bool(row.get("retracted", False)),
        "retracted_at": _iso(row.get("retracted_at")),
        "extractor": row.get("extractor"),
        "recorded_at": _iso(row.get("recorded_at")),
    })
    if row["kind"] == KIND_FACT:
        # Carry the SPO triple + provenance into chunk metadata too, so
        # callers can introspect a fact-chunk without re-querying.
        upstream_meta.update({
            "subject": row.get("subject"),
            "predicate": row.get("predicate"),
            "object": row.get("object"),
            "support_span": row.get("support_span"),
            "confidence": _parse_confidence(row.get("confidence")),
            "source_chunk_seq": row.get("source_chunk_seq"),
        })
    return {
        "content": row["original_content"],
        "embedded_content": row.get("embedded_content"),
        "embedding": _parse_embedding(row["embedding"]),
        "metadata": upstream_meta,
    }


def _fact_row_to_relationship(row: dict[str, Any]) -> dict[str, Any] | None:
    """Map a `kind='fact'` row to a pg-raggraph known-relationship dict.

    Returns None when the SPO triple is sparse (extractive-default
    chunkshop runs may emit ``support_span``-only fact rows with null
    subject/predicate/object). The chunk still lands via
    ``_row_to_pre_chunked``; only the graph edge is skipped.
    """
    subject = row.get("subject")
    predicate = row.get("predicate")
    obj = row.get("object")
    if not (subject and predicate and obj):
        return None
    rel: dict[str, Any] = {
        "src": subject,
        "dst": obj,
        "rel_type": predicate,
    }
    if row.get("support_span"):
        rel["description"] = row["support_span"]
    confidence = _parse_confidence(row.get("confidence"))
    if confidence is not None:
        rel["weight"] = confidence
    return rel


def _fact_entities(row: dict[str, Any]) -> list[dict[str, Any]]:
    """Derive subject/object entities so `entity_chunks` links get written."""
    out: list[dict[str, Any]] = []
    for name in (row.get("subject"), row.get("object")):
        if name:
            out.append({"name": name, "entity_type": "ENTITY"})
    return out


def rows_to_records(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group SP-A memory rows by ``session_id`` and emit pg-raggraph records.

    One record per session. Each record uses pg-raggraph's existing
    ``pre_chunked`` + ``relationships`` + ``skip_llm=True`` seams — no
    new ingest API. Episode rows become chunks; fact rows become chunks
    *and* (when the SPO triple is populated) caller-known relationships.

    Caller is responsible for fetching ``rows`` from chunkshop's memory
    table — see the runnable example
    ``benchmarks/agent-memory-demo/ingest_chunkshop_sp_a.py``.
    """
    by_session: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        sid = row.get("session_id")
        if not sid:
            raise ValueError(
                "SP-A memory row missing 'session_id' — required for grouping."
            )
        by_session.setdefault(sid, []).append(row)

    records: list[dict[str, Any]] = []
    for session_id, session_rows in by_session.items():
        # Stable order: SP-A guarantees `seq_num` is set on episodes (per
        # the session staging source's stable per-event ordinal). For fact
        # rows that came from a consolidation run, sort by effective_from
        # as a secondary key. Defensively coerce missing seq_num to 0.
        session_rows.sort(
            key=lambda r: (r.get("seq_num") or 0, _iso(r.get("effective_from")) or "")
        )

        pre_chunked = [_row_to_pre_chunked(r) for r in session_rows]

        # Build relationships + caller-known entities from fact rows only.
        relationships: list[dict[str, Any]] = []
        entity_names: set[str] = set()
        entities: list[dict[str, Any]] = []
        for r in session_rows:
            if r.get("kind") != KIND_FACT:
                continue
            rel = _fact_row_to_relationship(r)
            if rel is not None:
                relationships.append(rel)
            for ent in _fact_entities(r):
                if ent["name"] not in entity_names:
                    entity_names.add(ent["name"])
                    entities.append(ent)

        # Text input is only used for LLM extraction, which is skipped
        # here. Use a stable concatenation of episode contents so
        # content-hash dedup is stable across re-ingests of the same
        # session state.
        text = "\n\n".join(
            r["original_content"] for r in session_rows if r.get("kind") == KIND_EPISODE
        ) or session_id  # fall back to session_id when there are no episode rows yet

        records.append({
            "text": text,
            "source_id": f"agent_memory:{session_id}",
            "metadata": {
                "session_id": session_id,
                "source": "chunkshop_sp_a",
            },
            "pre_chunked": pre_chunked,
            "relationships": relationships,
            "entities": entities,
            "skip_llm": True,
        })
    return records


__all__ = [
    "SP_A_MEMORY_COLUMNS",
    "KIND_EPISODE",
    "KIND_FACT",
    "rows_to_records",
]
