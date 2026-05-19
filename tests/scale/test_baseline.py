"""Regression baseline harness for scale-remediation.

Task 0.1: proves the harness can ingest ~50 records and retrieve via
``mode="naive"``.  Every later scale task imports the ``scale_rag`` fixture
from conftest.py and extends this baseline.
"""

import pytest

pytestmark = pytest.mark.integration


async def test_query_returns_chunks_baseline(scale_rag):
    """Ingest 50 synthetic records and assert naive retrieval finds Paris."""
    await scale_rag.ingest_records(
        [
            {
                "text": f"Paris is the capital of France. fact {i}",
                "source_id": f"base:d{i}",
            }
            for i in range(50)
        ],
        namespace="base",
    )
    r = await scale_rag.query(
        "What is the capital of France?",
        mode="naive",
        namespace="base",
    )
    assert r.chunks, "expected at least one chunk returned by naive retrieval"
    assert any(
        "Paris" in c.content for c in r.chunks
    ), f"expected 'Paris' in at least one chunk; got: {[c.content[:80] for c in r.chunks]}"
