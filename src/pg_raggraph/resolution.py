"""Entity resolution — merge duplicate entities using pg_trgm + vector similarity.

This module exposes two functions:

- ``resolve_entity`` (insert-on-miss, original): used by the ingestion pipeline.
  This function is byte-for-byte unchanged from v0.5.0a2 and earlier; the A/B-gate
  work in #47 deliberately added a sibling rather than refactoring this one
  (Path A per the mission brief).
- ``resolve_entity_lookup`` (pure read, new in v0.5.0a3): returns a
  ``ResolvedEntity`` or ``None`` for the chunkshop ↔ pg-raggraph A/B gate. Does
  NOT mutate any table. Callers handle their own embedding cache.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal  # noqa: F401  # Literal used by resolve_entity_lookup in Task A2

from pg_raggraph.config import PGRGConfig
from pg_raggraph.db import Database


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
) -> int:
    """Resolve an entity: find existing match or insert new.

    Returns the entity ID (existing or newly created).
    """
    # First check for exact match
    props = properties or {}
    props_json = json.dumps(props)

    existing = await db.fetch_one(
        "SELECT id FROM entities WHERE namespace = %s AND name = %s",
        (namespace, name),
    )
    if existing:
        # Update description/properties if we have new info.
        if description or props:
            await db.execute(
                "UPDATE entities SET description = CASE "
                "WHEN %s = '' THEN description "
                "WHEN description = '' THEN %s "
                "WHEN position(%s in description) > 0 THEN description "
                "ELSE description || ' ' || %s END, "
                "embedding = %s, "
                "properties = properties || %s::jsonb "
                "WHERE id = %s",
                (
                    description,
                    description,
                    description,
                    description,
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

    if match and match["combined"] >= config.resolution_threshold:
        # Merge: update existing entity with new info
        merged_desc = match["description"]
        if description and description not in merged_desc:
            merged_desc = f"{merged_desc} {description}".strip()
        await db.execute(
            "UPDATE entities SET description = %s, embedding = %s, "
            "properties = properties || %s::jsonb WHERE id = %s",
            (merged_desc, embedding, props_json, match["id"]),
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
