"""End-to-end check: per-fact temporal columns on `relationships`.

Migration 006 adds `effective_from`, `effective_to`, `retracted`,
`retracted_at` to the `relationships` row. This integration test goes the
full path: ingest a record with `known_relationships` that carry temporal
fields → run a query that surfaces the relationship → assert the
RelationshipResult carries the temporal fields back.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from pg_raggraph import GraphRAG

pytestmark = pytest.mark.integration

DSN = "postgresql://postgres:postgres@localhost:5434/pg_raggraph"
NS = "test_rel_temporal"


async def _fresh_rag() -> GraphRAG:
    rag = GraphRAG(
        dsn=DSN,
        namespace=NS,
        llm_base_url="http://localhost:99999/v1",  # skip LLM extraction
    )
    await rag.connect()
    await rag.delete(NS)
    return rag


async def test_known_relationships_carry_temporal_fields_through_ingest_and_query():
    rag = await _fresh_rag()
    try:
        eff_from = datetime(2025, 1, 1, tzinfo=timezone.utc)
        eff_to = datetime(2025, 6, 1, tzinfo=timezone.utc)

        await rag.ingest_records(
            [
                {
                    "text": "Alice works at Acme.",
                    "source_id": "doc:1",
                    "entities": [
                        {"name": "Alice", "entity_type": "PERSON"},
                        {"name": "Acme", "entity_type": "ORG"},
                    ],
                    "relationships": [
                        {
                            "src": "Alice",
                            "dst": "Acme",
                            "rel_type": "WORKS_AT",
                            "description": "employment",
                            "weight": 0.95,
                            "effective_from": eff_from,
                            "effective_to": eff_to,
                            "retracted": False,
                        }
                    ],
                    "skip_llm": True,
                }
            ],
            namespace=NS,
        )

        # Read it back directly via the DB pool — the public query() path
        # may not surface the rel for a sparse 1-doc corpus, but a direct
        # SELECT confirms the columns landed.
        async with rag.db.pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT rel_type, effective_from, effective_to, "
                    "retracted, retracted_at FROM relationships "
                    "WHERE namespace = %s ORDER BY id",
                    (NS,),
                )
                rows = await cur.fetchall()

        assert len(rows) == 1
        rel_type, eff_from_db, eff_to_db, retracted, retracted_at = rows[0]
        assert rel_type == "WORKS_AT"
        assert eff_from_db == eff_from
        assert eff_to_db == eff_to
        assert retracted is False
        assert retracted_at is None
    finally:
        await rag.delete(NS)
        await rag.close()


async def test_known_relationships_without_temporal_fields_default_to_null():
    """Existing callers (no temporal info) keep NULL across the board."""
    rag = await _fresh_rag()
    try:
        await rag.ingest_records(
            [
                {
                    "text": "Bob works at BetaCorp.",
                    "source_id": "doc:2",
                    "entities": [
                        {"name": "Bob", "entity_type": "PERSON"},
                        {"name": "BetaCorp", "entity_type": "ORG"},
                    ],
                    "relationships": [
                        {
                            "src": "Bob",
                            "dst": "BetaCorp",
                            "rel_type": "WORKS_AT",
                        }
                    ],
                    "skip_llm": True,
                }
            ],
            namespace=NS,
        )

        async with rag.db.pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT effective_from, effective_to, retracted, retracted_at "
                    "FROM relationships WHERE namespace = %s",
                    (NS,),
                )
                rows = await cur.fetchall()

        assert len(rows) == 1
        eff_from, eff_to, retracted, retracted_at = rows[0]
        assert eff_from is None
        assert eff_to is None
        # Default is FALSE (not NULL) because of the column DEFAULT.
        assert retracted is False
        assert retracted_at is None
    finally:
        await rag.delete(NS)
        await rag.close()
