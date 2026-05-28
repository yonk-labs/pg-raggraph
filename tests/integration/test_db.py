"""Integration tests for database layer."""

import pytest

from pg_raggraph.db import SCHEMA_VERSION

pytestmark = pytest.mark.integration


async def test_connect_and_schema(db):
    """Test that connecting creates the schema.

    schema_version is the high-water mark across the baseline schema (1) and
    every applied migration — _record_migration bumps it via GREATEST. So the
    floor is SCHEMA_VERSION; the actual value rises with each migration.
    """
    version = await db.get_meta("schema_version")
    assert int(version) >= SCHEMA_VERSION


async def test_embedding_dim_stored(db):
    """Test that embedding dimension is stored in meta."""
    dim = await db.get_meta("embedding_dim")
    assert dim == str(db.config.embedding_dim)


async def test_tables_exist(db):
    """Verify all expected tables exist."""
    tables = await db.fetch_all(
        "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename"
    )
    table_names = {t["tablename"] for t in tables}
    expected = {
        "pgrg_meta",
        "documents",
        "chunks",
        "entities",
        "relationships",
        "entity_chunks",
        "relationship_chunks",
        "pgrg_llm_cache",
    }
    assert expected.issubset(table_names), f"Missing tables: {expected - table_names}"


async def test_insert_document(db):
    """Test inserting and querying a document."""
    doc_id = await db.insert_returning_id(
        "INSERT INTO documents (namespace, content_hash, source_path) "
        "VALUES (%s, %s, %s) RETURNING id",
        ("test", "hash123", "/test/file.md"),
    )
    assert doc_id > 0

    row = await db.fetch_one("SELECT * FROM documents WHERE id = %s", (doc_id,))
    assert row["content_hash"] == "hash123"
    assert row["namespace"] == "test"


async def test_insert_entity_with_embedding(db):
    """Test inserting an entity with a vector embedding."""
    dim = db.config.embedding_dim
    embedding = [0.1] * dim
    entity_id = await db.insert_returning_id(
        "INSERT INTO entities (namespace, name, entity_type, description, embedding) "
        "VALUES (%s, %s, %s, %s, %s) RETURNING id",
        ("test", "PostgreSQL", "technology", "A database", embedding),
    )
    assert entity_id > 0

    row = await db.fetch_one("SELECT * FROM entities WHERE id = %s", (entity_id,))
    assert row["name"] == "PostgreSQL"


async def test_bulk_insert(db):
    """Test bulk insert with executemany."""
    rows = [("test", f"hash_{i}", f"/test/file_{i}.md") for i in range(10)]
    await db.bulk_insert("documents", ["namespace", "content_hash", "source_path"], rows)
    count = await db.count("documents")
    assert count >= 10


async def test_tsvector_trigger(db):
    """Test that the search_vector trigger populates tsvector on chunk insert."""
    doc_id = await db.insert_returning_id(
        "INSERT INTO documents (namespace, content_hash) VALUES (%s, %s) RETURNING id",
        ("test", "trigger_test"),
    )
    dim = db.config.embedding_dim
    chunk_id = await db.insert_returning_id(
        "INSERT INTO chunks (document_id, content, embedding) VALUES (%s, %s, %s) RETURNING id",
        (doc_id, "PostgreSQL is a powerful open source database system", [0.0] * dim),
    )
    row = await db.fetch_one(
        "SELECT search_vector IS NOT NULL as has_sv FROM chunks WHERE id = %s",
        (chunk_id,),
    )
    assert row["has_sv"] is True

    # Verify BM25 search works
    results = await db.fetch_all(
        "SELECT id, ts_rank(search_vector, plainto_tsquery('english', %s)) as rank "
        "FROM chunks WHERE search_vector @@ plainto_tsquery('english', %s)",
        ("PostgreSQL database", "PostgreSQL database"),
    )
    assert len(results) > 0


async def test_count(db):
    """Test count helper."""
    count = await db.count("documents", "nonexistent_namespace")
    assert count == 0


async def test_documents_graph_status_columns(db):
    """Migration 012: graph_status / graph_extracted_at / graph_error are present.

    New rows default to 'ready' so existing callers (synchronous extract) are
    unaffected. The deferred-extraction path will explicitly set 'pending'.
    """
    cols = await db.fetch_all(
        "SELECT column_name, data_type, column_default, is_nullable "
        "FROM information_schema.columns "
        "WHERE table_name = 'documents' "
        "AND column_name IN ('graph_status', 'graph_extracted_at', 'graph_error')"
    )
    by_name = {c["column_name"]: c for c in cols}
    assert "graph_status" in by_name
    assert by_name["graph_status"]["is_nullable"] == "NO"
    assert "'ready'" in (by_name["graph_status"]["column_default"] or "")
    assert "graph_extracted_at" in by_name
    assert "graph_error" in by_name

    # Inserted-without-graph_status row backfills to 'ready' (the default).
    doc_id = await db.insert_returning_id(
        "INSERT INTO documents (namespace, content_hash) VALUES (%s, %s) RETURNING id",
        ("test", "gs_default_check"),
    )
    row = await db.fetch_one("SELECT graph_status FROM documents WHERE id = %s", (doc_id,))
    assert row["graph_status"] == "ready"


async def test_relationships_unique_constraint_present(db):
    """Migration 013 (PR-002): UNIQUE on (namespace, src_id, dst_id, rel_type)."""
    row = await db.fetch_one(
        "SELECT conname FROM pg_constraint WHERE conname = 'relationships_ns_edge_unique'"
    )
    assert row is not None, "migration 013's unique constraint must exist"


async def test_relationships_insert_is_idempotent_under_unique(db):
    """Re-inserting the same (ns, src, dst, rel_type) must not raise after PR-002."""
    dim = db.config.embedding_dim
    src = await db.insert_returning_id(
        "INSERT INTO entities (namespace, name, entity_type, embedding) "
        "VALUES (%s, %s, %s, %s) RETURNING id",
        ("test", "src_idem", "x", [0.1] * dim),
    )
    dst = await db.insert_returning_id(
        "INSERT INTO entities (namespace, name, entity_type, embedding) "
        "VALUES (%s, %s, %s, %s) RETURNING id",
        ("test", "dst_idem", "x", [0.1] * dim),
    )
    sql = (
        "INSERT INTO relationships "
        "(namespace, src_id, dst_id, rel_type, weight, description, properties) "
        "VALUES (%s, %s, %s, %s, %s, %s, '{}'::jsonb) "
        "ON CONFLICT (namespace, src_id, dst_id, rel_type) DO UPDATE "
        "SET weight = GREATEST(relationships.weight, EXCLUDED.weight) "
        "RETURNING id"
    )
    rid1 = await db.insert_returning_id(sql, ("test", src, dst, "REL", 1.0, "first"))
    rid2 = await db.insert_returning_id(sql, ("test", src, dst, "REL", 2.0, "second"))
    rid3 = await db.insert_returning_id(sql, ("test", src, dst, "REL", 1.5, "third"))
    assert rid1 == rid2 == rid3, "ON CONFLICT must keep the original row id stable"
    row = await db.fetch_one("SELECT weight FROM relationships WHERE id = %s", (rid1,))
    assert row["weight"] == 2.0, "GREATEST(weight) must keep the highest seen"


async def test_documents_graph_status_partial_index(db):
    """Migration 012: partial index on (namespace, created_at) WHERE pending."""
    row = await db.fetch_one(
        "SELECT indexdef FROM pg_indexes "
        "WHERE tablename = 'documents' AND indexname = 'idx_documents_graph_status_pending'"
    )
    assert row is not None, "expected idx_documents_graph_status_pending"
    indexdef = row["indexdef"]
    assert "namespace" in indexdef and "created_at" in indexdef
    assert "graph_status = 'pending'" in indexdef.lower() or "(graph_status" in indexdef.lower()
