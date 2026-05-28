"""Integration tests for resolve_entity_lookup (SC-003..SC-008)."""

import pytest

from pg_raggraph import GraphRAG
from pg_raggraph.resolution import ResolvedEntity, resolve_entity, resolve_entity_lookup

pytestmark = pytest.mark.integration

DSN = "postgresql://postgres:postgres@localhost:5434/pg_raggraph"


async def _make_rag(namespace: str) -> GraphRAG:
    rag = GraphRAG(
        dsn=DSN,
        namespace=namespace,
        llm_base_url="http://localhost:99999/v1",  # no LLM needed for resolution
    )
    await rag.connect()
    return rag


async def _seed_entity(rag: GraphRAG, name: str, namespace: str) -> int:
    """Insert one entity directly via the existing resolve_entity helper."""
    # Use a zero-vector embedding sized to config.embedding_dim — every dim
    # gets a unique nonzero so trgm/vector cosines aren't pathologically tied.
    dim = rag.config.embedding_dim
    embedding = [0.0] * dim
    embedding[0] = 1.0  # make it a valid unit-ish vector
    return await resolve_entity(
        name=name,
        entity_type="organization",
        description=f"Seed for {name}",
        embedding=embedding,
        namespace=namespace,
        db=rag.db,
        config=rag.config,
    )


async def test_exact_match_returns_score_1_and_match_type_exact():
    """SC-003: surface == entities.name → score=1.0, match_type='exact'."""
    rag = await _make_rag("test_ab_lookup_exact")
    try:
        eid = await _seed_entity(rag, "Apple Inc.", "test_ab_lookup_exact")

        result = await resolve_entity_lookup(
            "Apple Inc.",
            corpus_id="test_ab_lookup_exact",
            db=rag.db,
            config=rag.config,
        )

        assert isinstance(result, ResolvedEntity)
        assert result.id == eid
        assert result.surface == "Apple Inc."
        assert result.canonical_name == "Apple Inc."
        assert result.score == 1.0
        assert result.match_type == "exact"
    finally:
        await rag.db.execute(
            "DELETE FROM entities WHERE namespace = %s",
            ("test_ab_lookup_exact",),
        )
        await rag.db.close()
