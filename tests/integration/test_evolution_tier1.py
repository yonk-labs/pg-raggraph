"""Integration tests for evolving-knowledge-RAG Tier 1."""
from __future__ import annotations

from datetime import datetime, timezone

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
    """Applying migration 002 twice is safe — IF NOT EXISTS + nullable columns.

    Also asserts:
      - pgrg_applied_migrations ends up with exactly one row for 002 (no dup).
      - Column count on `documents` is stable across re-apply (no drift).
    """
    rag = await _fresh("test_evo_idemp")
    try:
        # Snapshot post-first-apply state
        count_before = await rag.db.fetch_one(
            "SELECT COUNT(*) AS n FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name='documents'"
        )
        assert count_before is not None
        documents_cols_before = count_before["n"]

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

        # pgrg_applied_migrations must have exactly one row for 002 — no
        # duplicates introduced by re-apply.
        applied = await rag.db.fetch_one(
            "SELECT COUNT(*) AS n FROM pgrg_applied_migrations "
            "WHERE filename = '002_evolution_tracking.sql'"
        )
        assert applied is not None
        assert applied["n"] == 1, (
            f"expected exactly 1 applied-migrations row for 002, got {applied['n']}"
        )

        # documents column count must be stable — no drift (e.g. ADD COLUMN
        # without IF NOT EXISTS sneaking in) after re-apply.
        count_after = await rag.db.fetch_one(
            "SELECT COUNT(*) AS n FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name='documents'"
        )
        assert count_after is not None
        assert count_after["n"] == documents_cols_before, (
            f"documents column count drifted across re-apply: "
            f"{documents_cols_before} -> {count_after['n']}"
        )
    finally:
        await rag.close()


async def test_ingest_stores_evolution_metadata_on_document():
    """Caller-supplied evolution metadata flows through ingest to documents."""
    import os
    import tempfile
    rag = await _fresh("test_evo_meta")
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8"
        ) as f:
            f.write("# Retracted Study\n\nA claim that was later retracted.\n")
            path = f.name
        try:
            await rag.ingest(
                [path],
                namespace="test_evo_meta",
                metadata={
                    "effective_from": datetime(2001, 6, 1, tzinfo=timezone.utc),
                    "retracted": True,
                    "version_label": "HRT-2001-obs",
                },
            )
            row = await rag.db.fetch_one(
                "SELECT effective_from, retracted, version_label "
                "FROM documents WHERE namespace = %s",
                ("test_evo_meta",),
            )
            assert row is not None
            assert row["effective_from"].year == 2001
            assert row["retracted"] is True
            assert row["version_label"] == "HRT-2001-obs"
        finally:
            os.unlink(path)
    finally:
        await rag.close()


async def test_ingest_without_metadata_defaults():
    """Ingest with no evolution metadata leaves columns at defaults."""
    import os
    import tempfile
    rag = await _fresh("test_evo_nometa")
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8"
        ) as f:
            f.write("# Plain\n\nNo evolution metadata supplied.\n")
            path = f.name
        try:
            await rag.ingest([path], namespace="test_evo_nometa")
            row = await rag.db.fetch_one(
                "SELECT effective_from, retracted, version_label "
                "FROM documents WHERE namespace = %s",
                ("test_evo_nometa",),
            )
            assert row is not None
            assert row["effective_from"] is None
            assert row["retracted"] is False
            assert row["version_label"] is None
        finally:
            os.unlink(path)
    finally:
        await rag.close()


async def test_ingest_creates_document_versions_row_when_version_supplied():
    """When metadata carries version_label OR supersedes_document_id, a
    document_versions row is created mirroring the document metadata."""
    import os
    import tempfile
    rag = await _fresh("test_evo_docver")
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8"
        ) as f:
            f.write("# Python 3.12\n\nNew features in 3.12.\n")
            path = f.name
        try:
            await rag.ingest(
                [path],
                namespace="test_evo_docver",
                metadata={
                    "effective_from": datetime(2024, 10, 1, tzinfo=timezone.utc),
                    "version_label": "Python 3.12",
                },
            )
            dv = await rag.db.fetch_one(
                "SELECT version_label, effective_from, namespace "
                "FROM document_versions "
                "WHERE document_id IN (SELECT id FROM documents WHERE namespace = %s) "
                "LIMIT 1",
                ("test_evo_docver",),
            )
            assert dv is not None
            assert dv["version_label"] == "Python 3.12"
            assert dv["effective_from"].year == 2024
            assert dv["namespace"] == "test_evo_docver"
        finally:
            os.unlink(path)
    finally:
        await rag.close()
