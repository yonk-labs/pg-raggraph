"""Integration tests for evolving-knowledge-RAG Tier 1."""
from __future__ import annotations

import pytest

from pg_raggraph import GraphRAG

pytestmark = pytest.mark.integration

DSN = "postgresql://postgres:postgres@localhost:5434/pg_raggraph"


async def _fresh(namespace: str) -> GraphRAG:
    rag = GraphRAG(dsn=DSN, namespace=namespace, llm_base_url="http://localhost:99999/v1")
    await rag.connect()
    await rag.delete(namespace)
    return rag


async def test_schema_has_evolution_tables_and_columns():
    """Tier 1 migration creates three new tables + adds evolution columns to documents."""
    rag = await _fresh("test_evo_schema")
    try:
        # Three new tables exist
        for tbl in ("facts", "fact_edges", "document_versions"):
            row = await rag.db.fetch_one(
                "SELECT 1 AS ok FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name = %s",
                (tbl,),
            )
            assert row is not None, f"table {tbl} missing"

        # documents has new columns
        for col in ("effective_from", "effective_to", "retracted", "version_label"):
            row = await rag.db.fetch_one(
                "SELECT 1 AS ok FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = 'documents' "
                "AND column_name = %s",
                (col,),
            )
            assert row is not None, f"documents.{col} missing"
    finally:
        await rag.close()


async def test_migration_002_idempotent():
    """Applying migration 002 twice is safe — IF NOT EXISTS + nullable columns."""
    rag = await _fresh("test_evo_idemp")
    try:
        # Simulate re-running migration by dropping the applied row and re-applying
        await rag.db.execute(
            "DELETE FROM pgrg_applied_migrations WHERE filename = '002_evolution_tracking.sql'"
        )
        # Next connect triggers re-application of 002
        await rag.close()
        rag = GraphRAG(dsn=DSN, namespace="test_evo_idemp",
                       llm_base_url="http://localhost:99999/v1")
        await rag.connect()
        # Schema should still be correct
        row = await rag.db.fetch_one(
            "SELECT 1 AS ok FROM information_schema.columns "
            "WHERE table_name='documents' AND column_name='effective_from'"
        )
        assert row is not None
    finally:
        await rag.close()
