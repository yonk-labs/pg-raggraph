"""Per-chunk extraction failure marker (issue #93).

An errored chunk-extraction call must be distinguishable from a chunk that
legitimately contains no entities — otherwise the doc silently flips to
graph_status='ready' with a hollow graph (the 111-vs-1,004 incident).
"""

from __future__ import annotations

import asyncio

import pytest

from pg_raggraph.extraction import _extract_single
from pg_raggraph.lede_extraction import _merge_results
from pg_raggraph.models import (
    ExtractedEntity,
    ExtractionResult,
)


class _FakeDB:
    """Cache-miss DB stub that records writes."""

    def __init__(self):
        self.executed: list[tuple] = []

    async def fetch_one(self, sql, params=None):
        return None  # always a cache miss

    async def execute(self, sql, params=None):
        self.executed.append((sql, params))


class _RaisingLLM:
    async def complete(self, messages):
        raise TimeoutError("provider timed out")

    async def complete_text(self, messages, temperature=0.2):  # pragma: no cover
        raise TimeoutError("provider timed out")


class _TruncatedJSONLLM:
    """Models the mlx-lm incident: completion budget truncates the JSON."""

    async def complete(self, messages):
        return '{"entities": [{"name": "Postg'

    async def complete_text(self, messages, temperature=0.2):  # pragma: no cover
        return ""


class _GoodLLM:
    async def complete(self, messages):
        return (
            '{"entities": [{"name": "PostgreSQL", "entity_type": "technology",'
            ' "description": "a database"}], "relationships": []}'
        )

    async def complete_text(self, messages, temperature=0.2):  # pragma: no cover
        return ""


def _run_single(llm, db=None):
    chunk = {"content": "PostgreSQL stores the graph.", "embedded_content": ""}
    sem = asyncio.Semaphore(1)
    return asyncio.run(_extract_single(chunk, llm, db or _FakeDB(), sem))


def test_llm_exception_returns_failure_marker():
    result = _run_single(_RaisingLLM())
    assert result.failed is True
    assert "TimeoutError" in result.error
    assert result.entities == [] and result.relationships == []


def test_truncated_json_returns_failure_marker():
    result = _run_single(_TruncatedJSONLLM())
    assert result.failed is True
    assert "JSONDecodeError" in result.error


def test_successful_extraction_is_not_failed():
    result = _run_single(_GoodLLM())
    assert result.failed is False
    assert result.error is None
    assert [e.name for e in result.entities] == ["PostgreSQL"]


def test_failed_result_is_never_cached():
    db = _FakeDB()
    _run_single(_RaisingLLM(), db)
    cache_writes = [sql for sql, _ in db.executed if "pgrg_llm_cache" in sql]
    assert cache_writes == [], "a failure marker must not be cached as an extraction"


def test_empty_result_defaults_to_not_failed():
    """Back-compat: plain empty results (legit no-entity chunks) stay clean."""
    r = ExtractionResult()
    assert r.failed is False and r.error is None
    # And round-trips through model_validate (LLM-cache read path).
    assert ExtractionResult.model_validate(r.model_dump()).failed is False


# --- llm+lede union propagation ---------------------------------------------


def _ok(names):
    return ExtractionResult(
        entities=[ExtractedEntity(name=n, entity_type="concept", description="") for n in names]
    )


@pytest.mark.parametrize(
    ("primary", "secondary", "want_failed", "want_error"),
    [
        (
            ExtractionResult(failed=True, error="TimeoutError: boom"),
            _ok(["gumbo"]),
            True,
            "TimeoutError: boom",
        ),
        (
            _ok(["Gumbo"]),
            ExtractionResult(failed=True, error="ValueError: spacy"),
            True,
            "ValueError: spacy",
        ),
        (_ok(["Gumbo"]), _ok(["gumbo"]), False, None),
    ],
)
def test_merge_results_propagates_failure(primary, secondary, want_failed, want_error):
    merged = _merge_results(primary, secondary)
    assert merged.failed is want_failed
    assert merged.error == want_error


def test_merge_failed_llm_leg_keeps_deterministic_yield():
    """LLM leg errored but the lede leg still contributed — the union carries
    the partial yield AND the failure marker."""
    merged = _merge_results(
        ExtractionResult(failed=True, error="HTTPStatusError: 503"),
        _ok(["gumbo", "Bayou Belle"]),
    )
    assert merged.failed is True
    assert {e.name for e in merged.entities} == {"gumbo", "Bayou Belle"}
