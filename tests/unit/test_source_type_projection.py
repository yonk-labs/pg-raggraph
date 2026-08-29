"""SQL-shape tests for documents.source_type projection (issue #38).

Every retrieval strategy must project ``d.source_type`` so multi-source
responses are identifiable to the reader (citation chips). SELECT-list
extension only — ORDER BY untouched.
"""

from __future__ import annotations

import pytest

from pg_raggraph.config import PGRGConfig
from pg_raggraph.models import ChunkResult
from pg_raggraph.retrieval import (
    _build_global_query,
    _build_local_query,
    _build_naive_prefilter,
    _build_naive_query,
    _build_naive_query_twostage,
    _build_naive_vector_first,
)


def _sql(builder, **kw) -> str:
    out = builder(PGRGConfig(), **kw)
    return out[0] if isinstance(out, tuple) else out


@pytest.mark.parametrize(
    "builder",
    [
        _build_naive_query,
        _build_naive_query_twostage,
        _build_naive_prefilter,
        _build_naive_vector_first,
        _build_local_query,
        _build_global_query,
    ],
)
def test_builder_projects_source_type(builder):
    assert "d.source_type" in _sql(builder)


@pytest.mark.parametrize("builder", [_build_naive_query, _build_local_query, _build_global_query])
def test_rrf_variant_projects_source_type(builder):
    assert "d.source_type" in _sql(builder, fusion="rrf")


def test_chunk_result_carries_source_type():
    assert ChunkResult(content="x", score=0.0).source_type is None
    assert ChunkResult(content="x", score=0.0, source_type="crm").source_type == "crm"
