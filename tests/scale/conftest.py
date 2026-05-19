"""Scale-test fixtures.

Shared across all tasks in the scale-remediation plan.  The ``scale_rag``
fixture connects to the integration database, yields a ready-to-use
GraphRAG instance with extraction disabled (pure vector RAG), then deletes
every row whose namespace starts with one of the prefixes used by this suite
(``base``, ``scale``, ``ts``, ``ten``).

Teardown uses raw SQL LIKE patterns so later tasks that create namespaces
such as ``base_t0``, ``scale_1k``, ``ts_123``, ``ten_A`` are all cleaned up
by a single fixture yield.
"""

import os

import pytest

from pg_raggraph import GraphRAG

TEST_DSN = os.environ.get(
    "PGRG_TEST_DSN",
    "postgresql://postgres:postgres@localhost:5434/pg_raggraph",
)

# Namespace prefixes owned by the scale test suite.  Teardown removes any row
# whose namespace LIKE-matches one of these patterns.
_SCALE_NS_PATTERNS = ("base%", "scale%", "ts%", "ten%")


@pytest.fixture
async def scale_rag():
    """Ready-to-use GraphRAG with extraction disabled.

    skip_extraction=True means no LLM is required — pure vector RAG mode.
    All 50-record baseline ingests complete in seconds without a running
    Ollama/OpenAI endpoint.

    Tests should always pass an explicit namespace; ``"scale"`` is a safe
    default that falls within a teardown-owned prefix.
    """
    rag = GraphRAG(
        TEST_DSN,
        namespace="scale",
        skip_extraction=True,
    )
    await rag.connect()
    yield rag
    # Best-effort cleanup: swallows errors intentionally (e.g. if the test
    # closed the connection early).  All owned prefixes are wiped so no
    # cross-test namespace pollution occurs.
    try:
        for pattern in _SCALE_NS_PATTERNS:
            await rag.db.execute(
                "DELETE FROM relationships WHERE namespace LIKE %s", (pattern,)
            )
            await rag.db.execute(
                "DELETE FROM entities WHERE namespace LIKE %s", (pattern,)
            )
            await rag.db.execute(
                "DELETE FROM documents WHERE namespace LIKE %s", (pattern,)
            )
    except Exception:
        pass
    await rag.close()
