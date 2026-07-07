"""Entity resolution — merge duplicate entities using pg_trgm + vector similarity.

This module exposes two functions:

- ``resolve_entity`` (insert-on-miss, original): used by the ingestion pipeline.
  Was byte-for-byte unchanged from v0.5.0a2 until the PR-222 / AAT-004
  hardening pass: descriptions are now capped at
  ``config.entity_description_max_chars`` on every write path, fuzzy merges
  are refused when names differ only by a version-like token
  (``config.entity_version_guard_pattern``), and every fuzzy merge writes an
  audit row to ``entity_merge_log`` (migration 017).
- ``resolve_entity_lookup`` (pure read, new in v0.5.0a3): returns a
  ``ResolvedEntity`` or ``None`` for the chunkshop ↔ pg-raggraph A/B gate. Does
  NOT mutate any table. Callers handle their own embedding cache.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Literal

from pg_raggraph.config import PGRGConfig
from pg_raggraph.db import Database


def merge_description(existing: str, new: str, cap: int) -> str:
    """Keep-first merge of entity descriptions with a hard char cap (PR-222).

    Appends ``new`` unless it's already a substring of ``existing`` (matches
    the SQL ``position()`` dedup used by the exact-match path), then truncates
    to ``cap`` chars — the oldest, usually most canonical, text survives.

    ponytail: per-source descriptions in properties JSONB is the richer
    upgrade path if keep-first truncation ever hurts quality.
    """
    existing = existing or ""
    if new and new not in existing:
        existing = f"{existing} {new}".strip()
    return existing[:cap] if cap > 0 else existing


def differs_only_by_version(a: str, b: str, pattern: str) -> bool:
    """True when two names differ only by a version-like token (AAT-004).

    "PostgreSQL 14" vs "PostgreSQL 15" or "Python 3.11" vs "3.12"-suffixed
    names must never fuzzy-merge — the versioned-docs workload depends on
    them staying distinct. ``pattern`` (config.entity_version_guard_pattern)
    matches the version tokens; empty string disables the guard.
    """
    if not pattern or a == b:
        return False
    rx = re.compile(pattern)
    return rx.sub("\x00", a) == rx.sub("\x00", b)


@dataclass(frozen=True)
class ResolvedEntity:
    """A resolved entity returned by ``resolve_entity_lookup``.

    Shape locked by the chunkshop emission contract §4.1 and the
    pg-raggraph mission brief SC-002. All five fields are required.

    Attributes
    ----------
    id:
        ``entities.id`` of the matched row.
    surface:
        The input surface string echoed back unchanged — lets callers correlate
        a batch lookup result with the input that produced it.
    canonical_name:
        ``entities.name`` of the matched row (the database's canonical form).
    score:
        1.0 for exact matches; otherwise the combined trgm + vector score in
        [0.0, 1.0]. Lower is a weaker match.
    match_type:
        ``'exact'``, ``'trgm'``, or ``'vector'``. ``'exact'`` means namespace +
        name matched directly; ``'trgm'`` / ``'vector'`` indicates the fuzzy
        path returned a row above ``config.resolution_threshold``.
    """

    id: int
    surface: str
    canonical_name: str
    score: float
    match_type: str


async def resolve_entity(
    name: str,
    entity_type: str,
    description: str,
    embedding: list[float],
    namespace: str,
    db: Database,
    config: PGRGConfig,
    properties: dict[str, Any] | None = None,
    source_document_id: int | None = None,
) -> int:
    """Resolve an entity: find existing match or insert new.

    Returns the entity ID (existing or newly created).

    ``source_document_id`` is optional ingest provenance recorded in
    ``entity_merge_log`` when the fuzzy path merges (AAT-004).
    """
    # First check for exact match
    props = properties or {}
    props_json = json.dumps(props)
    cap = config.entity_description_max_chars
    if cap > 0:
        # PR-222: nothing longer than the cap ever reaches the table — a
        # single oversized extraction is truncated before insert/append.
        description = description[:cap]

    existing = await db.fetch_one(
        "SELECT id FROM entities WHERE namespace = %s AND name = %s",
        (namespace, name),
    )
    if existing:
        # Update description/properties if we have new info. left() caps the
        # concatenation (PR-222): keep-first — the existing prefix survives.
        if description or props:
            await db.execute(
                "UPDATE entities SET description = left(CASE "
                "WHEN %s = '' THEN description "
                "WHEN description = '' THEN %s "
                "WHEN position(%s in description) > 0 THEN description "
                "ELSE description || ' ' || %s END, %s), "
                "embedding = %s, "
                "properties = properties || %s::jsonb "
                "WHERE id = %s",
                (
                    description,
                    description,
                    description,
                    description,
                    cap if cap > 0 else 2147483647,  # left(x, NULL) would NULL the column
                    embedding,
                    props_json,
                    existing["id"],
                ),
            )
        return existing["id"]

    # Check for fuzzy match using pg_trgm + vector similarity
    match = await db.fetch_one(
        """SELECT id, name, description,
                  similarity(name, %(name)s) AS trgm_score,
                  1 - (embedding <=> %(embedding)s::vector) AS vec_score,
                  (%(trgm_w)s * similarity(name, %(name)s) +
                   %(vec_w)s * (1 - (embedding <=> %(embedding)s::vector))) AS combined
           FROM entities
           WHERE namespace = %(namespace)s
             AND name != %(name)s
             AND similarity(name, %(name)s) > %(min_trgm)s
           ORDER BY combined DESC
           LIMIT 1""",
        {
            "name": name,
            "embedding": embedding,
            "namespace": namespace,
            "trgm_w": config.trgm_weight,
            "vec_w": config.vec_weight,
            "min_trgm": config.min_trgm_score,
        },
    )

    if (
        match
        and match["combined"] >= config.resolution_threshold
        and entity_type != "CODE_SYMBOL"
        and not differs_only_by_version(name, match["name"], config.entity_version_guard_pattern)
    ):
        # Merge: update existing entity with new info.
        # CODE_SYMBOL entities are identity-keyed by FQN and must never fuzzy-
        # merge: a class and its methods share an FQN prefix (e.g. ``pkg.Foo`` vs
        # ``pkg.Foo.bar``) and would otherwise collapse, corrupting the call
        # graph. They fall through to the exact-name insert below. The version
        # guard generalizes the same protection: "PostgreSQL 14" must never
        # absorb "PostgreSQL 15" (AAT-004).
        merged_desc = merge_description(match["description"], description, cap)
        await db.execute(
            "UPDATE entities SET description = %s, embedding = %s, "
            "properties = properties || %s::jsonb WHERE id = %s",
            (merged_desc, embedding, props_json, match["id"]),
        )
        # AAT-004: fuzzy merges are the lossy, false-positive-prone path —
        # record what was absorbed so false merges are detectable and
        # repairable (rag.entity_merges() / rag.split_entity()). Exact-name
        # matches above are not merges and are not logged.
        await db.execute(
            "INSERT INTO entity_merge_log "
            "(namespace, kept_id, merged_name, merged_type, merged_description, "
            " merged_properties, trgm_score, vec_score, combined_score, source, document_id) "
            "VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, 'auto', %s)",
            (
                namespace,
                match["id"],
                name,
                entity_type,
                description,
                props_json,
                float(match["trgm_score"]),
                float(match["vec_score"]),
                float(match["combined"]),
                source_document_id,
            ),
        )
        return match["id"]

    # No match found — insert new entity
    entity_id = await db.insert_returning_id(
        "INSERT INTO entities (namespace, name, entity_type, description, embedding, properties) "
        "VALUES (%s, %s, %s, %s, %s, %s::jsonb) "
        "ON CONFLICT (namespace, name) DO UPDATE SET "
        "description = EXCLUDED.description, embedding = EXCLUDED.embedding, "
        "properties = entities.properties || EXCLUDED.properties "
        "RETURNING id",
        (namespace, name, entity_type, description, embedding, props_json),
    )
    return entity_id


async def resolve_entity_lookup(
    surface: str,
    *,
    corpus_id: str,
    kind: Literal["fact_endpoint", "cooccur_node"] | None = None,
    db: Database,
    config: PGRGConfig,
) -> ResolvedEntity | None:
    """Look up a canonical entity for a surface string. Pure read — no mutation.

    The A/B-gate counterpart to ``resolve_entity``. Returns ``ResolvedEntity``
    if a match is found (exact name, then trgm-+-vector fuzzy match above
    ``config.resolution_threshold``), or ``None`` otherwise.

    Parameters
    ----------
    surface:
        The input surface string from a fact subject/object or a cooccur node.
        Not normalized by this function; pass it through as-is.
    corpus_id:
        Maps identity-equal to pg-raggraph's ``namespace`` column. Scopes the
        lookup so two corpora with the same surface land on different ids.
    kind:
        Optional discriminator from the chunkshop contract §4.1. Accepted but
        not yet used — present for API stability.
    db:
        The connected ``Database`` pool.
    config:
        The ``PGRGConfig`` — used for ``trgm_weight`` / ``vec_weight`` /
        ``min_trgm_score`` / ``resolution_threshold`` on the fuzzy path.

    Returns
    -------
    ResolvedEntity | None
        ``None`` means no match. A returned ``ResolvedEntity`` carries the
        original ``surface`` echoed back plus the matched ``canonical_name``.
    """
    _ = kind  # accepted for API stability; not consulted by exact/fuzzy paths

    # --- Exact-name match (namespace-scoped) -------------------------------
    row = await db.fetch_one(
        "SELECT id, name FROM entities WHERE namespace = %s AND name = %s",
        (corpus_id, surface),
    )
    if row is not None:
        return ResolvedEntity(
            id=row["id"],
            surface=surface,
            canonical_name=row["name"],
            score=1.0,
            match_type="exact",
        )

    # --- Fuzzy / vector path -----------------------------------------------
    # Embed the surface so the vector leg can score it. Lazy import to avoid
    # importing fastembed when callers only need the exact path.
    from pg_raggraph.embedding import get_embedding_provider

    embedder = get_embedding_provider(config)
    embedded = await embedder.embed([surface])
    surface_embedding = embedded[0]

    match = await db.fetch_one(
        """SELECT id, name,
                  similarity(name, %(surface)s) AS trgm_score,
                  1 - (embedding <=> %(embedding)s::vector) AS vec_score,
                  (%(trgm_w)s * similarity(name, %(surface)s) +
                   %(vec_w)s * (1 - (embedding <=> %(embedding)s::vector))) AS combined
           FROM entities
           WHERE namespace = %(namespace)s
             AND similarity(name, %(surface)s) > %(min_trgm)s
           ORDER BY combined DESC
           LIMIT 1""",
        {
            "surface": surface,
            "embedding": surface_embedding,
            "namespace": corpus_id,
            "trgm_w": config.trgm_weight,
            "vec_w": config.vec_weight,
            "min_trgm": config.min_trgm_score,
        },
    )

    if match is None or match["combined"] < config.resolution_threshold:
        return None

    # Pick the dominant leg: whichever scored higher above the per-metric
    # midpoint determines whether we tag this 'trgm' or 'vector'. Ties resolve
    # to 'trgm' since pg_trgm is the cheaper signal and the SQL also gates on it.
    match_type = "trgm" if match["trgm_score"] >= match["vec_score"] else "vector"

    return ResolvedEntity(
        id=match["id"],
        surface=surface,
        canonical_name=match["name"],
        score=float(match["combined"]),
        match_type=match_type,
    )
