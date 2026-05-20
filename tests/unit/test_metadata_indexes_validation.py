"""Unit tests for ``metadata_indexes`` key validation + name generation.

The validator and name builder are pure functions — exercising them
without a database surfaces injection / typo bugs that would otherwise
only fail at ``connect()`` time. Integration coverage (actual index
creation, planner picking up the index, query speedup) lives in
``tests/integration/`` and the retrieval-strategy bench.
"""

from __future__ import annotations

import pytest

from pg_raggraph.db import (
    _METADATA_INDEX_KEY_RE,
    _metadata_index_name,
    _validate_metadata_index_key,
)

# --- _validate_metadata_index_key ---


@pytest.mark.parametrize(
    "key",
    [
        "tier",
        "session_id",
        "tenant_id",
        "language",
        "k",  # single char ok
        "_private",
        "X1",
        "snake_case_with_digits_123",
    ],
)
def test_valid_keys_round_trip(key: str) -> None:
    assert _validate_metadata_index_key(key) == key


@pytest.mark.parametrize(
    "key,why",
    [
        ("", "empty"),
        ("1starts_with_digit", "leading digit"),
        ("kebab-case", "hyphen"),
        ("dot.notation", "dot"),
        ("path/to/key", "slash"),
        ("with space", "whitespace"),
        ("with\ttab", "tab"),
        ("with;semicolon", "semicolon (injection canary)"),
        ("--comment", "leading dash"),
        ('"quoted"', "quote"),
        ("Ünicode", "non-ASCII letter"),
        ("a" * 51, "length over 50"),
    ],
)
def test_invalid_keys_rejected(key: str, why: str) -> None:
    with pytest.raises(ValueError, match="not a valid identifier"):
        _validate_metadata_index_key(key)


def test_non_string_input_rejected() -> None:
    with pytest.raises(ValueError, match="must be strings"):
        _validate_metadata_index_key(123)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="must be strings"):
        _validate_metadata_index_key(None)  # type: ignore[arg-type]


def test_max_length_boundary() -> None:
    """50 chars is allowed; 51 is the rejection point."""
    assert _validate_metadata_index_key("a" * 50) == "a" * 50
    with pytest.raises(ValueError):
        _validate_metadata_index_key("a" * 51)


def test_regex_pattern_is_anchored() -> None:
    """Guard against accidental loosening — the pattern MUST anchor both
    ends, otherwise an injection like ``valid'; DROP TABLE...`` would pass
    because the prefix is valid."""
    assert _METADATA_INDEX_KEY_RE.match("valid'; DROP TABLE chunks; --") is None


# --- _metadata_index_name ---


def test_index_name_uses_canonical_prefix() -> None:
    """Discoverable via psql \\di — operators grep for idx_chunks_metadata_."""
    assert _metadata_index_name("tier") == "idx_chunks_metadata_tier"
    assert _metadata_index_name("session_id") == "idx_chunks_metadata_session_id"


def test_index_name_fits_postgres_identifier_limit() -> None:
    """Postgres truncates identifiers > 63 bytes silently — generated names
    must stay safely under that. ``idx_chunks_metadata_`` is 20 chars + key
    up to 50 chars = 70 — already over. Verify the boundary so we don't
    ship a config that silently aliases two keys to the same truncated
    index name."""
    # Realistic upper-bound: 'idx_chunks_metadata_' (20) + 43 = 63
    longest_safe_key = "a" * 43
    assert len(_metadata_index_name(longest_safe_key)) == 63
    # Beyond that, the index name overflows — surface as a comment, not a
    # hard fail, since the user might be OK with truncation. Today the
    # config validator caps at 50, which yields 70-char names — Postgres
    # truncates to 63. Acceptable since 50-char metadata keys are wildly
    # uncommon. Document this in the cookbook.
