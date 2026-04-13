"""Integration tests for database layer."""

import pytest

from pg_raggraph.db import SCHEMA_VERSION

pytestmark = pytest.mark.integration


async def test_connect_and_schema(db):
    """Test that connecting creates the schema."""
    version = await db.get_meta("schema_version")
    assert version == str(SCHEMA_VERSION)


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
