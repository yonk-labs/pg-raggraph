"""Tests for the documents-side metadata-index config fields (Option A).

Three new fields mirror the chunks-side knobs for the documents table:

- ``document_metadata_indexes: list[str]`` — btree per-key on
  ``documents.metadata->>'<key>'``
- ``document_metadata_indexes_gin: bool`` — GIN on the whole
  ``documents.metadata`` JSONB
- ``document_metadata_generated_columns: dict[str, str | dict]`` — typed
  STORED columns + btree indexes on ``documents``

The DDL helpers (``_apply_metadata_indexes`` etc.) were refactored to
take a ``table`` parameter. These tests pin both the config field
defaults / acceptance AND the name-builder behavior for both tables.

End-to-end DDL exercising (actual index creation, planner picking) is
covered by the live bench in benchmarks/, not unit tests.
"""

from __future__ import annotations

import pytest

from pg_raggraph.config import PGRGConfig
from pg_raggraph.db import (
    _metadata_generated_column_name,
    _metadata_generated_index_name,
    _metadata_gin_index_name,
    _metadata_index_name,
    _validate_metadata_table,
)

# --- config defaults ---


def test_document_metadata_indexes_default_empty() -> None:
    """Opt-in: zero schema change for callers who don't set it."""
    assert PGRGConfig().document_metadata_indexes == []


def test_document_metadata_indexes_gin_default_false() -> None:
    assert PGRGConfig().document_metadata_indexes_gin is False


def test_document_metadata_generated_columns_default_empty() -> None:
    assert PGRGConfig().document_metadata_generated_columns == {}


# --- config acceptance ---


def test_document_metadata_indexes_accepts_list() -> None:
    cfg = PGRGConfig(document_metadata_indexes=["salesperson", "product", "customer"])
    assert cfg.document_metadata_indexes == ["salesperson", "product", "customer"]


def test_document_metadata_indexes_gin_accepts_bool() -> None:
    assert PGRGConfig(document_metadata_indexes_gin=True).document_metadata_indexes_gin is True
    assert PGRGConfig(document_metadata_indexes_gin=False).document_metadata_indexes_gin is False


def test_document_metadata_generated_columns_accepts_dict() -> None:
    cfg = PGRGConfig(
        document_metadata_generated_columns={
            "priority": "int",
            "created_at": "timestamptz",
        }
    )
    assert cfg.document_metadata_generated_columns == {
        "priority": "int",
        "created_at": "timestamptz",
    }


def test_document_metadata_generated_columns_accepts_nested_json_path_spec() -> None:
    cfg = PGRGConfig(
        document_metadata_generated_columns={
            "term": {
                "type": "text",
                "path": ["lede_report", "attributes", "term", "value"],
            }
        }
    )
    assert cfg.document_metadata_generated_columns["term"]["type"] == "text"


# --- chunks-side fields stay isolated from documents-side ---


def test_setting_doc_fields_doesnt_touch_chunks_fields() -> None:
    """Verify the two parallel namespaces don't bleed."""
    cfg = PGRGConfig(
        metadata_indexes=["tier"],
        document_metadata_indexes=["salesperson"],
        metadata_generated_columns={"chunk_priority": "int"},
        document_metadata_generated_columns={"doc_priority": "int"},
    )
    assert cfg.metadata_indexes == ["tier"]
    assert cfg.document_metadata_indexes == ["salesperson"]
    assert cfg.metadata_generated_columns == {"chunk_priority": "int"}
    assert cfg.document_metadata_generated_columns == {"doc_priority": "int"}


# --- table validator ---


@pytest.mark.parametrize("table", ["chunks", "documents"])
def test_valid_metadata_tables(table: str) -> None:
    assert _validate_metadata_table(table) == table


@pytest.mark.parametrize(
    "table",
    ["entities", "relationships", "chunk", "", "DROP TABLE chunks", "; SELECT 1"],
)
def test_invalid_metadata_tables_rejected(table: str) -> None:
    with pytest.raises(ValueError, match="metadata-index table"):
        _validate_metadata_table(table)


# --- name builders take table parameter ---


def test_btree_index_name_defaults_to_chunks() -> None:
    """Back-compat: callers that didn't pass table still get chunks-side names."""
    assert _metadata_index_name("tier") == "idx_chunks_metadata_tier"


def test_btree_index_name_threads_table() -> None:
    assert _metadata_index_name("tier", table="chunks") == "idx_chunks_metadata_tier"
    assert (
        _metadata_index_name("salesperson", table="documents")
        == "idx_documents_metadata_salesperson"
    )


def test_gin_index_name_per_table() -> None:
    assert _metadata_gin_index_name("chunks") == "idx_chunks_metadata_gin"
    assert _metadata_gin_index_name("documents") == "idx_documents_metadata_gin"
    # Default
    assert _metadata_gin_index_name() == "idx_chunks_metadata_gin"


def test_generated_column_name_is_table_independent() -> None:
    """Column lives on a specific table, no cross-table name collision."""
    assert _metadata_generated_column_name("priority") == "meta_priority"


def test_generated_index_name_threads_table() -> None:
    assert _metadata_generated_index_name("priority", table="chunks") == "idx_chunks_meta_priority"
    assert (
        _metadata_generated_index_name("priority", table="documents")
        == "idx_documents_meta_priority"
    )
    # Back-compat: default to chunks
    assert _metadata_generated_index_name("priority") == "idx_chunks_meta_priority"
