"""Entity resolution — merge duplicate entities using pg_trgm + vector similarity."""

from __future__ import annotations

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
) -> int:
    """Resolve an entity: find existing match or insert new.

    Returns the entity ID (existing or newly created).
    """
    # First check for exact match
    existing = await db.fetch_one(
        "SELECT id FROM entities WHERE namespace = %s AND name = %s",
        (namespace, name),
    )
    if existing:
        # Update description if we have new info
        if description:
            await db.execute(
                "UPDATE entities SET description = CASE "
                "WHEN description = '' THEN %s "
                "ELSE description || ' ' || %s END, "
                "embedding = %s "
                "WHERE id = %s",
                (description, description, embedding, existing["id"]),
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
            "UPDATE entities SET description = %s, embedding = %s WHERE id = %s",
            (merged_desc, embedding, match["id"]),
        )
        return match["id"]

    # No match found — insert new entity
    entity_id = await db.insert_returning_id(
        "INSERT INTO entities (namespace, name, entity_type, description, embedding) "
        "VALUES (%s, %s, %s, %s, %s) "
        "ON CONFLICT (namespace, name) DO UPDATE SET "
        "description = EXCLUDED.description, embedding = EXCLUDED.embedding "
        "RETURNING id",
        (namespace, name, entity_type, description, embedding),
    )
    return entity_id
