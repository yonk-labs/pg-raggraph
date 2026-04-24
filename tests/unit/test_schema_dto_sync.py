"""Unit test: schema.sql column sets match pydantic DTO field sets for
evolution tables. Catches drift when someone adds a column to the schema
without a corresponding DTO field (or vice versa)."""
from __future__ import annotations

import re
from pathlib import Path

from pg_raggraph.models import Document, DocumentVersion, Fact, FactEdge

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "src" / "pg_raggraph" / "sql" / "schema.sql"

DOCUMENT_EVOLUTION_COLS = {"effective_from", "effective_to", "retracted", "version_label"}

TABLES_TO_CHECK = {
    "document_versions": DocumentVersion,
    "facts": Fact,
    "fact_edges": FactEdge,
}

ALLOWED_SCHEMA_ONLY_COLS: dict[str, set[str]] = {
    # Example future entry: "facts": {"embedding"},  # Tier 2 adds facts.embedding
}
ALLOWED_DTO_ONLY_FIELDS: dict[str, set[str]] = {
    # "id" and "created_at" are present in schema (BIGSERIAL + TIMESTAMPTZ DEFAULT now())
    # and in DTOs — no exception needed at Tier 1.
}


def _extract_columns(sql: str, table: str) -> set[str]:
    """Extract column names from a CREATE TABLE block (same approach as
    test_schema_migration_sync.py)."""
    pattern = rf"CREATE TABLE IF NOT EXISTS\s+{table}\s*\((.+?)\)\s*;"
    match = re.search(pattern, sql, re.DOTALL | re.IGNORECASE)
    if not match:
        raise AssertionError(f"CREATE TABLE {table} not found in schema.sql")
    body = match.group(1)
    body = re.sub(r"--.*", "", body)
    cols: set[str] = set()
    for line in body.split(","):
        line = line.strip()
        if not line:
            continue
        if re.match(r"^(UNIQUE|FOREIGN\s+KEY|PRIMARY\s+KEY|CHECK|CONSTRAINT)\b",
                    line, re.IGNORECASE):
            continue
        m = re.match(r"^([a-zA-Z_][a-zA-Z0-9_]*)\b", line)
        if m:
            cols.add(m.group(1).lower())
    return cols


def test_document_has_evolution_columns_in_schema():
    """schema.sql's documents CREATE TABLE contains all four evolution cols."""
    schema = SCHEMA_PATH.read_text()
    cols = _extract_columns(schema, "documents")
    missing = DOCUMENT_EVOLUTION_COLS - cols
    assert not missing, f"documents missing evolution cols in schema.sql: {missing}"


def test_document_dto_has_evolution_fields():
    """Document DTO has all four evolution fields."""
    fields = set(Document.model_fields.keys())
    missing = DOCUMENT_EVOLUTION_COLS - fields
    assert not missing, f"Document DTO missing evolution fields: {missing}"


def test_evolution_tables_schema_matches_dto():
    """Every evolution table's schema columns match its DTO fields 1:1."""
    schema = SCHEMA_PATH.read_text()
    for table, model_cls in TABLES_TO_CHECK.items():
        cols = _extract_columns(schema, table)
        fields = set(model_cls.model_fields.keys())
        schema_only = cols - fields - ALLOWED_SCHEMA_ONLY_COLS.get(table, set())
        dto_only = fields - cols - ALLOWED_DTO_ONLY_FIELDS.get(table, set())
        assert not schema_only, (
            f"{table}: columns in schema.sql but no DTO field: {sorted(schema_only)}"
        )
        assert not dto_only, (
            f"{table}: DTO fields not in schema.sql: {sorted(dto_only)}"
        )
