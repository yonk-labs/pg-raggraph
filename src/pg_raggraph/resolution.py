"""Entity resolution — merge duplicate entities using pg_trgm + vector similarity."""

from __future__ import annotations

import json
from typing import Any

from pg_raggraph.config import PGRGConfig
from pg_raggraph.db import Database


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
