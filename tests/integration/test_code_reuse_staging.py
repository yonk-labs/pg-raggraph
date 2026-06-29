"""Capability 1: a code doc whose chunks+vectors are REUSED via `pre_chunked`
must still feed the deferred code-graph staging — using a caller-supplied
faithful source (`code_source_content`), since the doc-level `text` on the reuse
path is joined-chunk text, not a faithful file. Loud-fail if it's missing."""

import os

import pytest

from pg_raggraph import GraphRAG

DSN = os.environ.get("PGRG_TEST_DSN", "postgresql://postgres:postgres@localhost:5434/pg_raggraph")
pytestmark = pytest.mark.integration

NS = "test_code_reuse_staging"

# Faithful original file vs the joined-chunk text a reuse bridge would pass as `text`.
FAITHFUL_SRC = "import os\n\n\ndef greet(name):\n    return f'hi {name}'\n"
JOINED_CHUNK_TEXT = "def greet(name):\n    return f'hi {name}'\n"


def _pre_chunked(dim: int):
    return [
        {
            "content": JOINED_CHUNK_TEXT,
            "embedding": [0.0] * dim,
            "metadata": {"language": "python", "fqn": "mod.greet"},
        }
    ]


@pytest.mark.asyncio
async def test_reused_code_doc_stages_faithful_source():
    rag = GraphRAG(dsn=DSN, namespace=NS)
    await rag.connect()
    await rag.delete(NS)
    try:
        dim = rag.config.embedding_dim
        await rag.ingest_records(
            [
                {
                    "text": JOINED_CHUNK_TEXT,  # joined-chunk text (NOT faithful)
                    "source_id": "f1.py",
                    "pre_chunked": _pre_chunked(dim),
                    "code_source_content": FAITHFUL_SRC,  # the faithful file
                    "skip_llm": True,
                }
            ],
            namespace=NS,
            defer_extraction=True,
        )
        rows = await rag._db.fetch_all(
            "SELECT content, language, source_path FROM code_backfill_stage WHERE namespace = %s",
            (NS,),
        )
        assert len(rows) == 1
        assert rows[0]["language"] == "python"
        assert rows[0]["content"] == FAITHFUL_SRC  # faithful, not the joined chunk
    finally:
        await rag.delete(NS)
        await rag.close()


@pytest.mark.asyncio
async def test_reused_code_doc_without_faithful_source_is_refused():
    # ingest_records contains per-record failures (batch semantics): the bad
    # record's ValueError is logged + counted failed and its per-doc transaction
    # rolls back — it is NOT raised to the caller. The refusal is observable as a
    # rolled-back doc (would have silently persisted-but-unstaged before the fix).
    rag = GraphRAG(dsn=DSN, namespace=NS)
    await rag.connect()
    await rag.delete(NS)
    try:
        dim = rag.config.embedding_dim
        await rag.ingest_records(
            [
                {
                    "text": JOINED_CHUNK_TEXT,
                    "source_id": "f2.py",
                    "pre_chunked": _pre_chunked(dim),
                    # no code_source_content → must be refused, not staged
                    "skip_llm": True,
                }
            ],
            namespace=NS,
            defer_extraction=True,
        )
        docs = await rag._db.fetch_one(
            "SELECT COUNT(*) AS n FROM documents WHERE namespace = %s", (NS,)
        )
        assert docs["n"] == 0  # transaction rolled back — nothing persisted
        staged = await rag._db.fetch_one(
            "SELECT COUNT(*) AS n FROM code_backfill_stage WHERE namespace = %s", (NS,)
        )
        assert staged["n"] == 0  # garbage never staged
    finally:
        await rag.delete(NS)
        await rag.close()
