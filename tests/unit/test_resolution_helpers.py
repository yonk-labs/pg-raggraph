"""Unit tests for the PR-222 description cap and AAT-004 version guard helpers."""

from importlib.resources import files

from pg_raggraph.config import PGRGConfig
from pg_raggraph.resolution import differs_only_by_version, merge_description

DEFAULT_PATTERN = PGRGConfig.model_fields["entity_version_guard_pattern"].default


# ---------------------------------------------------------------------------
# merge_description (PR-222 cap math)
# ---------------------------------------------------------------------------


def test_merge_appends_novel_description():
    assert merge_description("A database.", "Open source.", 2000) == "A database. Open source."


def test_merge_suppresses_substring_repeat():
    assert merge_description("A database. Open source.", "Open source.", 2000) == (
        "A database. Open source."
    )


def test_merge_from_empty_existing():
    assert merge_description("", "First fact.", 2000) == "First fact."


def test_merge_empty_new_is_noop():
    assert merge_description("A database.", "", 2000) == "A database."


def test_cap_enforced_and_keep_first():
    out = merge_description("x" * 90, "y" * 90, 100)
    assert len(out) == 100
    assert out.startswith("x" * 90)  # oldest text survives


def test_cap_enforced_across_repeated_merges():
    desc = ""
    for i in range(100):
        desc = merge_description(desc, f"novel fact number {i} with padding", 200)
    assert len(desc) <= 200
    assert desc.startswith("novel fact number 0")


def test_cap_zero_disables():
    out = merge_description("x" * 90, "y" * 90, 0)
    assert len(out) == 181


# ---------------------------------------------------------------------------
# differs_only_by_version (AAT-004 guard)
# ---------------------------------------------------------------------------


def test_version_suffix_blocks():
    assert differs_only_by_version("PostgreSQL 14", "PostgreSQL 15", DEFAULT_PATTERN)


def test_dotted_version_blocks():
    assert differs_only_by_version("Python 3.11", "Python 3.12", DEFAULT_PATTERN)
    assert differs_only_by_version("v1.2.3", "v1.2.4", DEFAULT_PATTERN)


def test_version_infix_blocks():
    assert differs_only_by_version("Python 3.11 docs", "Python 3.12 docs", DEFAULT_PATTERN)


def test_non_version_difference_allows_merge():
    assert not differs_only_by_version("OpenAI", "Open AI", DEFAULT_PATTERN)
    assert not differs_only_by_version("Boeing 747", "Airbus 320", DEFAULT_PATTERN)


def test_versioned_vs_unversioned_allows_merge():
    # "PostgreSQL" vs "PostgreSQL 14" differ by more than a version swap.
    assert not differs_only_by_version("PostgreSQL", "PostgreSQL 14", DEFAULT_PATTERN)


def test_identical_names_not_blocked():
    assert not differs_only_by_version("PostgreSQL 14", "PostgreSQL 14", DEFAULT_PATTERN)


def test_empty_pattern_disables_guard():
    assert not differs_only_by_version("PostgreSQL 14", "PostgreSQL 15", "")


# ---------------------------------------------------------------------------
# entity_merge_log shape guards (migration 017 <-> schema.sql <-> writers)
# ---------------------------------------------------------------------------

EXPECTED_COLUMNS = (
    "namespace",
    "kept_id",
    "merged_entity_id",
    "merged_name",
    "merged_type",
    "merged_description",
    "merged_properties",
    "trgm_score",
    "vec_score",
    "combined_score",
    "source",
    "document_id",
    "merged_at",
)


def test_migration_017_has_expected_columns():
    sql = files("pg_raggraph.sql").joinpath("migrations/017_entity_merge_log.sql").read_text()
    assert "CREATE TABLE IF NOT EXISTS entity_merge_log" in sql
    for col in EXPECTED_COLUMNS:
        assert col in sql, f"migration 017 missing column {col!r}"


def test_schema_sql_mirrors_merge_log():
    sql = files("pg_raggraph.sql").joinpath("schema.sql").read_text()
    assert "CREATE TABLE IF NOT EXISTS entity_merge_log" in sql
    for col in EXPECTED_COLUMNS:
        assert col in sql, f"schema.sql entity_merge_log missing column {col!r}"
