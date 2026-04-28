"""Unit test: migration DDL and fresh-install DDL must describe the same
post-migration schema for evolution tracking tables.

This catches drift at Tier 2/3 when someone forgets to mirror a migration
column into schema.sql."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "src" / "pg_raggraph" / "sql" / "schema.sql"
MIGRATION_PATH = ROOT / "src" / "pg_raggraph" / "sql" / "migrations" / "002_evolution_tracking.sql"

EVOLUTION_TABLES = ("document_versions", "facts", "fact_edges")

# Known legitimate divergences (empty for Tier 1; Tier 2 will populate).
# Format: {table_name: {column_name_only_in_schema, ...}}
ALLOWED_SCHEMA_ONLY_COLS: dict[str, set[str]] = {}


def _extract_columns(sql: str, table: str) -> set[str]:
    """Extract column names from a CREATE TABLE block for the given table."""
    # Find the CREATE TABLE block
    pattern = rf"CREATE TABLE IF NOT EXISTS\s+{table}\s*\((.+?)\)\s*;"
    match = re.search(pattern, sql, re.DOTALL | re.IGNORECASE)
    if not match:
        raise AssertionError(f"CREATE TABLE {table} not found in SQL")
    body = match.group(1)
    # Strip inline comments
    body = re.sub(r"--.*", "", body)
    cols: set[str] = set()
    for line in body.split(","):
        line = line.strip()
        if not line:
            continue
        # Skip constraint-only lines (UNIQUE, FOREIGN KEY, PRIMARY KEY, CHECK)
        if re.match(
            r"^(UNIQUE|FOREIGN\s+KEY|PRIMARY\s+KEY|CHECK|CONSTRAINT)\b", line, re.IGNORECASE
        ):
            continue
        # First whitespace-delimited token is the column name
        m = re.match(r"^([a-zA-Z_][a-zA-Z0-9_]*)\b", line)
        if m:
            cols.add(m.group(1).lower())
    return cols


def test_evolution_tables_match_between_migration_and_schema():
    schema = SCHEMA_PATH.read_text()
    migration = MIGRATION_PATH.read_text()
    for table in EVOLUTION_TABLES:
        sc = _extract_columns(schema, table)
        mc = _extract_columns(migration, table)
        schema_only = sc - mc - ALLOWED_SCHEMA_ONLY_COLS.get(table, set())
        migration_only = mc - sc
        assert not schema_only, (
            f"{table}: columns in schema.sql but not in migration 002: {sorted(schema_only)}"
        )
        assert not migration_only, (
            f"{table}: columns in migration 002 but not in schema.sql: {sorted(migration_only)}"
        )
