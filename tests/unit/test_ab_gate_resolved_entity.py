"""Unit tests for ResolvedEntity dataclass shape + import paths (SC-001, SC-002)."""

from dataclasses import FrozenInstanceError, fields

import pytest


def test_resolved_entity_importable_from_resolution_module():
    from pg_raggraph.resolution import ResolvedEntity  # noqa: F401


def test_resolved_entity_importable_from_top_level():
    from pg_raggraph import ResolvedEntity  # noqa: F401


def test_resolved_entity_has_five_locked_fields():
    from pg_raggraph.resolution import ResolvedEntity

    field_names = {f.name for f in fields(ResolvedEntity)}
    assert field_names == {"id", "surface", "canonical_name", "score", "match_type"}, (
        f"ResolvedEntity must have exactly the five locked fields; got {field_names}"
    )


def test_resolved_entity_is_frozen():
    from pg_raggraph.resolution import ResolvedEntity

    e = ResolvedEntity(
        id=1, surface="Apple", canonical_name="Apple Inc.", score=0.92, match_type="trgm"
    )
    with pytest.raises(FrozenInstanceError):
        e.score = 0.5  # type: ignore[misc]


def test_resolved_entity_field_types_documented():
    """Each field has the type the brief locks. Runtime type hints (not enforcement)."""
    from pg_raggraph.resolution import ResolvedEntity

    hints = {f.name: f.type for f in fields(ResolvedEntity)}
    # dataclasses store the annotation as str under PEP 563; normalize whitespace.
    assert "int" in str(hints["id"])
    assert "str" in str(hints["surface"])
    assert "str" in str(hints["canonical_name"])
    assert "float" in str(hints["score"])
    assert "str" in str(hints["match_type"])
