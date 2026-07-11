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


async def test_code_symbols_never_fuzzy_merge(db, config):
    """CODE_SYMBOL entities are identity-keyed by FQN and must not fuzzy-merge,
    even when a class and its method share an FQN prefix under a low threshold —
    the exact case that would otherwise collapse a call graph."""
    dim = config.embedding_dim
    emb = [0.5] * dim  # identical embeddings → high vector score
    config.resolution_threshold = 0.5
    config.min_trgm_score = 0.2

    id1 = await resolve_entity(
        name="pkg.mod.Foo",
        entity_type="CODE_SYMBOL",
        description="Code symbol pkg.mod.Foo",
        embedding=emb,
        namespace="test_codesym",
        db=db,
        config=config,
    )
    id2 = await resolve_entity(
        name="pkg.mod.Foo.bar",
        entity_type="CODE_SYMBOL",
        description="Code symbol pkg.mod.Foo.bar",
        embedding=emb,
        namespace="test_codesym",
        db=db,
        config=config,
    )

    assert id1 != id2
    rows = await db.fetch_all(
        "SELECT name FROM entities WHERE namespace = %s AND entity_type = 'CODE_SYMBOL' "
        "ORDER BY name",
        ("test_codesym",),
    )
    assert [r["name"] for r in rows] == ["pkg.mod.Foo", "pkg.mod.Foo.bar"]


async def test_no_fuzzy_merge_types_are_exempt(db, config):
    """Caller-declared no_fuzzy_merge_types must not fuzzy-merge even above the
    threshold (issue #98): distinct legal case captions with similar party names
    would otherwise collapse. Generalizes the built-in CODE_SYMBOL exemption."""
    dim = config.embedding_dim
    emb = [0.5] * dim  # identical embeddings → high vector score
    config.resolution_threshold = 0.5
    config.min_trgm_score = 0.2
    config.no_fuzzy_merge_types = ["CASE"]

    id1 = await resolve_entity(
        name="Smith v. Jones (Ohio 2019)",
        entity_type="CASE",
        description="Case caption 1",
        embedding=emb,
        namespace="test_nofuzzy",
        db=db,
        config=config,
    )
    id2 = await resolve_entity(
        name="Smith v. Jones (Texas 2021)",
        entity_type="CASE",
        description="Case caption 2",
        embedding=emb,
        namespace="test_nofuzzy",
        db=db,
        config=config,
    )

    assert id1 != id2
    rows = await db.fetch_all(
        "SELECT name FROM entities WHERE namespace = %s AND entity_type = 'CASE' ORDER BY name",
        ("test_nofuzzy",),
    )
    assert len(rows) == 2


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
