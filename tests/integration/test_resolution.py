"""Integration tests for entity resolution."""

import pytest

from pg_raggraph.resolution import resolve_entity

pytestmark = pytest.mark.integration


async def test_exact_match_returns_existing(db, config):
    """If an entity with the same name exists, return its ID."""
    dim = config.embedding_dim
    emb = [0.5] * dim

    # Insert first entity
    id1 = await resolve_entity(
        name="PostgreSQL",
        entity_type="technology",
        description="A database",
        embedding=emb,
        namespace="test",
        db=db,
        config=config,
    )
    assert id1 > 0

    # Resolve same name — should return same ID
    id2 = await resolve_entity(
        name="PostgreSQL",
        entity_type="technology",
        description="An open source database",
        embedding=emb,
        namespace="test",
        db=db,
        config=config,
    )
    assert id2 == id1


async def test_new_entity_gets_inserted(db, config):
    """If no match found, a new entity is created."""
    dim = config.embedding_dim
    emb1 = [0.1] * dim
    emb2 = [0.9] * dim

    id1 = await resolve_entity(
        name="Python",
        entity_type="language",
        description="A programming language",
        embedding=emb1,
        namespace="test",
        db=db,
        config=config,
    )

    id2 = await resolve_entity(
        name="Kubernetes",
        entity_type="technology",
        description="Container orchestration",
        embedding=emb2,
        namespace="test",
        db=db,
        config=config,
    )

    assert id1 != id2


async def test_fuzzy_match_merges_similar(db, config):
    """Similar names (e.g., 'OpenAI' and 'Open AI') should merge when threshold is met."""
    dim = config.embedding_dim
    # Use very similar embeddings so vector score is high
    emb = [0.5] * dim

    # Lower threshold for this test
    config.resolution_threshold = 0.5
    config.min_trgm_score = 0.2

    id1 = await resolve_entity(
        name="OpenAI",
        entity_type="organization",
        description="An AI company",
        embedding=emb,
        namespace="test",
        db=db,
        config=config,
    )

    # "Open AI" is similar to "OpenAI"
    id2 = await resolve_entity(
        name="Open AI",
        entity_type="organization",
        description="Creator of GPT",
        embedding=emb,
        namespace="test",
        db=db,
        config=config,
    )

    # They should merge (same ID)
    assert id2 == id1

    # Verify description was updated
    row = await db.fetch_one("SELECT description FROM entities WHERE id = %s", (id1,))
    assert "Creator of GPT" in row["description"]


async def test_namespace_isolation(db, config):
    """Entities in different namespaces don't merge."""
    dim = config.embedding_dim
    emb = [0.5] * dim

    id1 = await resolve_entity(
        name="PostgreSQL",
        entity_type="technology",
        description="A database",
        embedding=emb,
        namespace="ns1",
        db=db,
        config=config,
    )

    id2 = await resolve_entity(
        name="PostgreSQL",
        entity_type="technology",
        description="A database",
        embedding=emb,
        namespace="ns2",
        db=db,
        config=config,
    )

    # Different namespaces = different entities
    assert id1 != id2
