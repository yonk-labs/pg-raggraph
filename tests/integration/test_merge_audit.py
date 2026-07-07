"""Integration tests for PR-222 (description cap) and AAT-004 (merge audit log).

Covers:
- fuzzy auto-merge writes an entity_merge_log row with scores + provenance
- exact-name matches are not merges and are not logged
- version-suffix guard: "PostgreSQL 14"/"PostgreSQL 15" never fuzzy-merge
- description cap enforced across repeated exact + fuzzy merges
- merge_entities unions descriptions/properties and logs (I-14 fix)
- entity_merges() read API filters; split_entity() manual repair
"""

import os

import pytest

from pg_raggraph import GraphRAG
from pg_raggraph.resolution import resolve_entity

pytestmark = pytest.mark.integration

TEST_DSN = os.environ.get(
    "PGRG_TEST_DSN",
    "postgresql://postgres:postgres@localhost:5434/pg_raggraph",
)


async def _clean(db, namespace: str) -> None:
    await db.execute("DELETE FROM entities WHERE namespace = %s", (namespace,))
    await db.execute("DELETE FROM entity_merge_log WHERE namespace = %s", (namespace,))


async def _rag(namespace: str) -> GraphRAG:
    rag = GraphRAG(dsn=TEST_DSN, namespace=namespace, llm_base_url="", skip_extraction=True)
    await rag.connect()
    return rag


# ---------------------------------------------------------------------------
# Fuzzy auto-merge audit trail
# ---------------------------------------------------------------------------


async def test_fuzzy_merge_writes_audit_row(db, config):
    ns = "test_mergelog_fuzzy"
    await _clean(db, ns)
    emb = [0.5] * config.embedding_dim
    config.resolution_threshold = 0.5
    config.min_trgm_score = 0.2

    id1 = await resolve_entity(
        name="OpenAI",
        entity_type="organization",
        description="An AI company",
        embedding=emb,
        namespace=ns,
        db=db,
        config=config,
    )
    id2 = await resolve_entity(
        name="Open AI",
        entity_type="organization",
        description="Creator of GPT",
        embedding=emb,
        namespace=ns,
        db=db,
        config=config,
        source_document_id=4242,
    )
    assert id2 == id1

    rows = await db.fetch_all("SELECT * FROM entity_merge_log WHERE namespace = %s", (ns,))
    assert len(rows) == 1
    log = rows[0]
    assert log["kept_id"] == id1
    assert log["merged_name"] == "Open AI"
    assert log["merged_type"] == "organization"
    assert log["merged_description"] == "Creator of GPT"
    assert log["source"] == "auto"
    assert log["document_id"] == 4242
    assert 0.0 < log["trgm_score"] <= 1.0
    assert 0.0 < log["vec_score"] <= 1.0001
    assert log["combined_score"] >= config.resolution_threshold
    assert log["merged_at"] is not None


async def test_exact_match_update_is_not_logged(db, config):
    ns = "test_mergelog_exact"
    await _clean(db, ns)
    emb = [0.5] * config.embedding_dim

    for desc in ("A database", "An open source database"):
        await resolve_entity(
            name="PostgreSQL",
            entity_type="technology",
            description=desc,
            embedding=emb,
            namespace=ns,
            db=db,
            config=config,
        )

    rows = await db.fetch_all("SELECT * FROM entity_merge_log WHERE namespace = %s", (ns,))
    assert rows == []


# ---------------------------------------------------------------------------
# Version-suffix guard (AAT-004)
# ---------------------------------------------------------------------------


async def test_version_suffix_never_merges(db, config):
    """'PostgreSQL 14' and 'PostgreSQL 15' survive as distinct entities even
    with identical embeddings and a low threshold — the guard, not the score,
    is what protects them."""
    ns = "test_mergelog_verguard"
    await _clean(db, ns)
    emb = [0.5] * config.embedding_dim
    config.resolution_threshold = 0.5
    config.min_trgm_score = 0.2

    id1 = await resolve_entity(
        name="PostgreSQL 14",
        entity_type="technology",
        description="Release 14",
        embedding=emb,
        namespace=ns,
        db=db,
        config=config,
    )
    id2 = await resolve_entity(
        name="PostgreSQL 15",
        entity_type="technology",
        description="Release 15",
        embedding=emb,
        namespace=ns,
        db=db,
        config=config,
    )

    assert id1 != id2
    rows = await db.fetch_all(
        "SELECT name FROM entities WHERE namespace = %s ORDER BY name", (ns,)
    )
    assert [r["name"] for r in rows] == ["PostgreSQL 14", "PostgreSQL 15"]
    logs = await db.fetch_all("SELECT * FROM entity_merge_log WHERE namespace = %s", (ns,))
    assert logs == []


async def test_version_guard_disabled_restores_old_behavior(db, config):
    ns = "test_mergelog_verguard_off"
    await _clean(db, ns)
    emb = [0.5] * config.embedding_dim
    config.resolution_threshold = 0.5
    config.min_trgm_score = 0.2
    config.entity_version_guard_pattern = ""

    id1 = await resolve_entity(
        name="PostgreSQL 14",
        entity_type="technology",
        description="Release 14",
        embedding=emb,
        namespace=ns,
        db=db,
        config=config,
    )
    id2 = await resolve_entity(
        name="PostgreSQL 15",
        entity_type="technology",
        description="Release 15",
        embedding=emb,
        namespace=ns,
        db=db,
        config=config,
    )
    assert id1 == id2  # guard off → the false merge the guard exists to stop


# ---------------------------------------------------------------------------
# Description cap (PR-222)
# ---------------------------------------------------------------------------


async def test_description_cap_across_repeated_merges(db, config):
    ns = "test_mergelog_cap"
    await _clean(db, ns)
    emb = [0.5] * config.embedding_dim
    config.entity_description_max_chars = 200
    config.resolution_threshold = 0.5
    config.min_trgm_score = 0.2

    # Exact-match path: 50 novel descriptions.
    for i in range(50):
        eid = await resolve_entity(
            name="HotEntity",
            entity_type="technology",
            description=f"novel fact number {i} about the hot entity",
            embedding=emb,
            namespace=ns,
            db=db,
            config=config,
        )
    # Fuzzy path: one more merge with a long description.
    fid = await resolve_entity(
        name="Hot Entity",
        entity_type="technology",
        description="z" * 500,
        embedding=emb,
        namespace=ns,
        db=db,
        config=config,
    )
    assert fid == eid

    row = await db.fetch_one(
        "SELECT description FROM entities WHERE id = %s",
        (eid,),
    )
    assert len(row["description"]) <= 200
    assert row["description"].startswith("novel fact number 0")  # keep-first


async def test_oversized_insert_is_capped(db, config):
    ns = "test_mergelog_cap_insert"
    await _clean(db, ns)
    config.entity_description_max_chars = 200

    eid = await resolve_entity(
        name="FreshEntity",
        entity_type="technology",
        description="x" * 5000,
        embedding=[0.5] * config.embedding_dim,
        namespace=ns,
        db=db,
        config=config,
    )
    row = await db.fetch_one("SELECT description FROM entities WHERE id = %s", (eid,))
    assert len(row["description"]) == 200


# ---------------------------------------------------------------------------
# merge_entities (manual path, I-14) + read/repair APIs
# ---------------------------------------------------------------------------


async def test_merge_entities_preserves_data_and_logs(db):
    ns = "merge_audit_manual"
    rag = await _rag(ns)
    try:
        await _clean(db, ns)
        await rag.db.execute(
            "INSERT INTO entities (namespace, name, entity_type, description, properties) "
            "VALUES (%s, 'Postgres', 'tech', 'The canonical row.', '{\"tier\": \"keep\"}'), "
            "       (%s, 'PostgresQL', 'tech', 'The absorbed row.', "
            '        \'{"tier": "merged", "extra": 1}\')',
            (ns, ns),
        )
        rows = await rag.db.fetch_all("SELECT id, name FROM entities WHERE namespace = %s", (ns,))
        keep = next(r["id"] for r in rows if r["name"] == "Postgres")
        merged = next(r["id"] for r in rows if r["name"] == "PostgresQL")

        await rag.merge_entities(keep, [merged])

        row = await rag.db.fetch_one(
            "SELECT description, properties FROM entities WHERE id = %s", (keep,)
        )
        assert "The canonical row." in row["description"]
        assert "The absorbed row." in row["description"]  # I-14: no longer dropped
        assert row["properties"]["tier"] == "keep"  # keep wins on conflict
        assert row["properties"]["extra"] == 1  # merged fills gaps

        logs = await rag.entity_merges(namespace=ns)
        assert len(logs) == 1
        assert logs[0]["source"] == "manual"
        assert logs[0]["kept_id"] == keep
        assert logs[0]["merged_entity_id"] == merged
        assert logs[0]["merged_name"] == "PostgresQL"
        assert logs[0]["merged_description"] == "The absorbed row."
        assert logs[0]["combined_score"] is None
    finally:
        await rag.close()


async def test_entity_merges_filters_and_split_entity(db, config):
    ns = "merge_audit_split"
    rag = await _rag(ns)
    try:
        await _clean(db, ns)
        emb = [0.5] * config.embedding_dim
        config.resolution_threshold = 0.5
        config.min_trgm_score = 0.2

        await resolve_entity(
            name="Kubernetes",
            entity_type="technology",
            description="Container orchestration",
            embedding=emb,
            namespace=ns,
            db=db,
            config=config,
        )
        kept = await resolve_entity(
            name="Kubernetes.",
            entity_type="technology",
            description="The k8s project",
            embedding=emb,
            namespace=ns,
            db=db,
            config=config,
        )

        logs = await rag.entity_merges(namespace=ns)
        assert len(logs) == 1
        assert logs[0]["kept_id"] == kept
        # min_score above any possible combined score filters it out.
        assert await rag.entity_merges(namespace=ns, min_score=1.5) == []

        # split_entity recreates the absorbed entity, repoints nothing.
        new_id = await rag.split_entity(logs[0]["id"])
        row = await rag.db.fetch_one("SELECT * FROM entities WHERE id = %s", (new_id,))
        assert row["name"] == "Kubernetes."
        assert row["description"] == "The k8s project"
        assert row["embedding"] is not None

        # A second split of the same row refuses — the name is back.
        with pytest.raises(ValueError, match="already exists"):
            await rag.split_entity(logs[0]["id"])
        with pytest.raises(ValueError, match="not found"):
            await rag.split_entity(999_999_999)
    finally:
        await rag.close()


async def test_trim_entity_descriptions(db, config):
    ns = "test_mergelog_trim"
    rag = await _rag(ns)
    try:
        await _clean(db, ns)
        await rag.db.execute(
            "INSERT INTO entities (namespace, name, entity_type, description) "
            "VALUES (%s, 'Bloated', 'tech', %s), (%s, 'Slim', 'tech', 'short')",
            (ns, "b" * 5000, ns),
        )
        rag.config.entity_description_max_chars = 200

        trimmed = await rag.trim_entity_descriptions(namespace=ns)
        assert trimmed == 1
        row = await rag.db.fetch_one(
            "SELECT description FROM entities WHERE namespace = %s AND name = 'Bloated'",
            (ns,),
        )
        assert len(row["description"]) == 200
        # Idempotent — nothing left over the cap.
        assert await rag.trim_entity_descriptions(namespace=ns) == 0
    finally:
        await rag.close()
