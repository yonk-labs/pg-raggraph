"""Unit tests for the runtime index-management API.

Covers the pure-function pieces (type inference, name builders, scoring
heuristic, pg_indexes parsing) without a database. End-to-end DDL
exercising lives in tests/integration/ and the live bench.

The recommend()/add()/remove() entry points are not unit-tested here
because they need an async DB; integration tests cover them.
"""

from __future__ import annotations

import pytest

from pg_raggraph.index_management import (
    IndexRecommendation,
    _btree_index_name,
    _existing_keys_from_indexes,
    _generated_column_name,
    _generated_index_name,
    _gin_index_name,
    _score_recommendation,
    _validate_table,
    infer_sql_type,
)

# --- table validator ---


@pytest.mark.parametrize("t", ["chunks", "documents"])
def test_valid_tables(t: str) -> None:
    assert _validate_table(t) == t


@pytest.mark.parametrize("t", ["entities", "relationships", "chunk", "", "DROP TABLE"])
def test_invalid_tables_rejected(t: str) -> None:
    with pytest.raises(ValueError, match="Invalid table"):
        _validate_table(t)


# --- name builders ---


def test_btree_index_name_encodes_table() -> None:
    """Both tables get distinct btree index names so they can coexist."""
    assert _btree_index_name("tier", "chunks") == "idx_chunks_metadata_tier"
    assert _btree_index_name("salesperson", "documents") == "idx_documents_metadata_salesperson"


def test_gin_index_name_per_table() -> None:
    assert _gin_index_name("chunks") == "idx_chunks_metadata_gin"
    assert _gin_index_name("documents") == "idx_documents_metadata_gin"


def test_generated_column_name_table_independent() -> None:
    """Column lives on a specific table — no cross-table collision
    possible from name alone. ``meta_priority`` on chunks and
    ``meta_priority`` on documents are different DB objects."""
    assert _generated_column_name("priority") == "meta_priority"


def test_generated_index_name_encodes_table() -> None:
    """The btree index on the generated column DOES encode the table
    so chunks-side and documents-side index names don't collide."""
    assert _generated_index_name("priority", "chunks") == "idx_chunks_meta_priority"
    assert _generated_index_name("priority", "documents") == "idx_documents_meta_priority"


# --- type inference ---


@pytest.mark.parametrize(
    "values,expected",
    [
        # numeric
        (["1", "2", "3"], "integer"),
        (["-1", "0", "1000"], "integer"),
        (["999999999999"], "bigint"),  # > 2^31
        (["1.5", "2.7", "3.14"], "numeric"),
        (["1", "2.5"], "numeric"),  # mixed int/float → numeric
        # timestamp
        (["2026-05-20T10:00:00Z", "2026-05-21T11:30:00Z"], "timestamptz"),
        (["2026-05-20 10:00:00", "2026-05-21 11:30:00.123"], "timestamptz"),
        (["2026-05-20T10:00:00+05:00"], "timestamptz"),
        # boolean
        (["true", "false"], "boolean"),
        (["TRUE", "False", "true"], "boolean"),
        (["yes", "no"], "boolean"),
        # text / fallback
        (["alice", "bob", "charlie"], "text"),
        (["2026-05-20"], "text"),  # date without time isn't a timestamp
        (["1", "two", "3"], "text"),  # mixed
        # edge cases
        ([], "text"),
        ([None, None], "text"),  # type: ignore[list-item]
        (["", ""], "text"),
    ],
)
def test_infer_sql_type(values: list, expected: str) -> None:
    assert infer_sql_type(values) == expected


# --- recommendation scoring ---


def test_score_skips_low_signal_keys() -> None:
    """Keys with <100 rows have too little signal to recommend."""
    assert (
        _score_recommendation(
            table="chunks",
            key="rare_tag",
            rows_with_key=50,
            total_rows=1000,
            distinct_values=10,
            sample_values=["x"],
            already_btree=False,
            already_generated=False,
        )
        is None
    )


def test_score_skips_near_unique_text() -> None:
    """Text with >80% cardinality (near-unique) doesn't benefit from btree."""
    assert (
        _score_recommendation(
            table="chunks",
            key="content_hash",
            rows_with_key=10_000,
            total_rows=10_000,
            distinct_values=9_900,
            sample_values=["hash-1", "hash-2", "hash-3"],
            already_btree=False,
            already_generated=False,
        )
        is None
    )


def test_score_recommends_btree_for_selective_text() -> None:
    """100 distinct values across 10K rows = 1% cardinality — sweet
    spot for btree (planner picks it; selectivity is meaningful)."""
    rec = _score_recommendation(
        table="chunks",
        key="customer_id",
        rows_with_key=10_000,
        total_rows=10_000,
        distinct_values=100,
        sample_values=["cust-001", "cust-042", "cust-007"],
        already_btree=False,
        already_generated=False,
    )
    assert rec is not None
    assert rec.kind == "btree"
    assert rec.sql_type is None
    assert rec.confidence == "high"
    assert "selective" in rec.rationale.lower()


def test_score_recommends_btree_for_extreme_low_cardinality_with_medium_confidence() -> None:
    """3 distinct values across 10K rows (e.g., a 3-value tier enum) is
    too low-cardinality for high confidence — the planner may skip the
    index when each value matches 33%+ of rows. Still recommended, but
    medium confidence."""
    rec = _score_recommendation(
        table="chunks",
        key="tier",
        rows_with_key=10_000,
        total_rows=10_000,
        distinct_values=3,
        sample_values=["provisional", "consolidated", "provisional"],
        already_btree=False,
        already_generated=False,
    )
    assert rec is not None
    assert rec.kind == "btree"
    assert rec.confidence == "medium"


def test_score_recommends_generated_for_numeric() -> None:
    rec = _score_recommendation(
        table="documents",
        key="priority",
        rows_with_key=5_000,
        total_rows=5_000,
        distinct_values=10,
        sample_values=["1", "2", "3", "4", "5"],
        already_btree=False,
        already_generated=False,
    )
    assert rec is not None
    assert rec.kind == "generated"
    assert rec.sql_type == "integer"
    assert rec.table == "documents"
    assert "range" in rec.rationale.lower() or "typed" in rec.rationale.lower()


def test_score_marks_already_applied() -> None:
    """already_exists=True still emerges in output (UI shows
    "Already applied" rather than dropping the suggestion)."""
    rec = _score_recommendation(
        table="chunks",
        key="tier",
        rows_with_key=10_000,
        total_rows=10_000,
        distinct_values=3,
        sample_values=["a", "b", "c"],
        already_btree=True,
        already_generated=False,
    )
    assert rec is not None
    assert rec.already_exists is True


def test_score_marks_generated_not_btree_already_applied() -> None:
    """already_generated tracks SEPARATELY from already_btree —
    a key with btree but no generated column on a numeric field
    should still recommend the generated column."""
    rec = _score_recommendation(
        table="chunks",
        key="priority",
        rows_with_key=5_000,
        total_rows=5_000,
        distinct_values=10,
        sample_values=["1", "2", "3"],
        already_btree=True,
        already_generated=False,
    )
    assert rec is not None
    assert rec.kind == "generated"
    assert rec.already_exists is False  # generated column doesn't exist yet


# --- pg_indexes parsing ---


def test_existing_keys_from_indexes_handles_all_kinds() -> None:
    """Round-trip every flavor of metadata index we generate."""
    rows = [
        {
            "table": "chunks",
            "name": "idx_chunks_metadata_tier",
            "definition": (
                "CREATE INDEX idx_chunks_metadata_tier ON chunks (((metadata ->> 'tier'::text)))"
            ),
        },
        {
            "table": "chunks",
            "name": "idx_chunks_metadata_gin",
            "definition": "CREATE INDEX idx_chunks_metadata_gin ON chunks USING gin (metadata)",
        },
        {
            "table": "chunks",
            "name": "idx_chunks_meta_priority",
            "definition": "CREATE INDEX idx_chunks_meta_priority ON chunks (meta_priority)",
        },
        {
            "table": "documents",
            "name": "idx_documents_metadata_salesperson",
            "definition": (
                "CREATE INDEX idx_documents_metadata_salesperson ON documents "
                "(((metadata ->> 'salesperson'::text)))"
            ),
        },
        {
            "table": "documents",
            "name": "idx_documents_meta_priority",
            "definition": "CREATE INDEX idx_documents_meta_priority ON documents (meta_priority)",
        },
    ]
    result = _existing_keys_from_indexes(rows)
    assert ("chunks", "tier", "btree") in result
    assert ("chunks", "__full_metadata__", "gin") in result
    assert ("chunks", "priority", "generated") in result
    assert ("documents", "salesperson", "btree") in result
    assert ("documents", "priority", "generated") in result


def test_existing_keys_ignores_unrelated_indexes() -> None:
    """Non-metadata indexes (e.g., idx_chunk_doc) are skipped."""
    rows = [
        {
            "table": "chunks",
            "name": "idx_chunk_doc",  # pre-existing, not metadata-related
            "definition": "CREATE INDEX idx_chunk_doc ON chunks (document_id)",
        },
        {
            "table": "chunks",
            "name": "idx_chunks_metadata_tier",
            "definition": (
                "CREATE INDEX idx_chunks_metadata_tier ON chunks (((metadata ->> 'tier'::text)))"
            ),
        },
    ]
    result = _existing_keys_from_indexes(rows)
    assert len(result) == 1
    assert ("chunks", "tier", "btree") in result


# --- IndexRecommendation dataclass ---


def test_index_recommendation_default_fields() -> None:
    """Default ``sample_values=[]`` from field(default_factory=list) —
    not a mutable shared default."""
    a = IndexRecommendation(table="chunks", key="foo", kind="btree")
    b = IndexRecommendation(table="documents", key="bar", kind="btree")
    a.sample_values.append("test")
    assert b.sample_values == []  # not aliased
