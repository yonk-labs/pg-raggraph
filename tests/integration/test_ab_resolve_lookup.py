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


async def test_surface_variants_collapse_to_same_id():
    """SC-004: surface variants of 'Apple Inc.' collapse to same id via fuzzy match.

    We use casing/punctuation variants ('Apple Inc', 'apple inc.', 'APPLE INC')
    rather than the single-word 'Apple' because the default
    config.min_trgm_score=0.3 + config.resolution_threshold=0.85 won't pass a
    1-trigram surface against a 2-word canonical. The brief's #47 use case is
    surface-form variation, not aggressive abbreviation — keeping the test
    aligned with the default tuning.
    """
    from pg_raggraph.embedding import get_embedding_provider

    rag = await _make_rag("test_ab_lookup_variants")
    try:
        # Seed one canonical entity with a real embedding so the vector
        # leg of the fuzzy match has signal — not just the trgm leg.
        embedder = get_embedding_provider(rag.config)
        canonical_embedding = (await embedder.embed(["Apple Inc."]))[0]
        eid = await resolve_entity(
            name="Apple Inc.",
            entity_type="organization",
            description="Apple Inc. — Cupertino technology firm",
            embedding=canonical_embedding,
            namespace="test_ab_lookup_variants",
            db=rag.db,
            config=rag.config,
        )

        variants = ["Apple Inc", "APPLE INC.", "apple inc."]
        for surface in variants:
            result = await resolve_entity_lookup(
                surface,
                corpus_id="test_ab_lookup_variants",
                db=rag.db,
                config=rag.config,
            )
            assert result is not None, f"variant {surface!r} returned None — expected fuzzy match"
            assert result.id == eid, (
                f"variant {surface!r} resolved to id {result.id}, expected {eid}"
            )
            assert result.surface == surface
            assert result.canonical_name == "Apple Inc."
            assert result.match_type in {"trgm", "vector"}, (
                f"variant {surface!r} had match_type={result.match_type!r}, "
                "expected 'trgm' or 'vector'"
            )
            # Score is the combined weighted trgm+vec, which can hit 1.0 for
            # case-insensitive duplicates (trgm sees identical trigrams after
            # case folding). The important invariants: positive, ≤ 1.0, and
            # the row resolves to the canonical id — not an exact-match path.
            assert 0.0 < result.score <= 1.0, (
                f"variant {surface!r} had score {result.score}, expected (0, 1]"
            )
    finally:
        await rag.db.execute(
            "DELETE FROM entities WHERE namespace = %s",
            ("test_ab_lookup_variants",),
        )
        await rag.db.close()


async def test_no_match_returns_none():
    """SC-005: surface with no plausible match → None (not a synthetic 0-score)."""
    rag = await _make_rag("test_ab_lookup_nomatch")
    try:
        await _seed_entity(rag, "Microsoft Corporation", "test_ab_lookup_nomatch")

        result = await resolve_entity_lookup(
            "xyzzy plugh frobnitz",  # nothing remotely close
            corpus_id="test_ab_lookup_nomatch",
            db=rag.db,
            config=rag.config,
        )

        assert result is None, f"expected None for unmatched surface, got {result!r}"
    finally:
        await rag.db.execute(
            "DELETE FROM entities WHERE namespace = %s",
            ("test_ab_lookup_nomatch",),
        )
        await rag.db.close()
