"""Regression test for the hyphen-numeric ID tokenizer asymmetry (known
limitation, issues #951/#952).

pg-raggraph v0.9.0 rewrote retrieval onto native BM25+pgvector RRF (issue
#96) but did NOT fix the naive query tokenizer. ``_to_or_tsquery`` splits a
hyphen-numeric ID like "INC-0001" into 'inc' and '0001' via a bare ``\\w+``
regex (see tests/unit/test_hyphenated_id_tokenizer.py for the tokenizer-
level proof), while Postgres's own text search parser -- and therefore
``chunks.search_vector`` -- stores it as 'inc' + '-0001'. The '0001' half of
the naive query never matches the stored '-0001' lexeme, so only the
generic 'inc' term survives.

This file shows the retrieval-ranking consequence:

- Under ``lexical_backend="ts_rank"`` (default): v0.9.1 fixed
  ``_to_or_tsquery`` (issues #102/#103) to run the question through
  Postgres's own parser path, so hyphen-numeric tokens like '-0001' survive
  and match the stored lexeme. The first test asserts the ID chunk ranks
  first -- it was ``xfail(strict=True)`` while the bug existed and flipped
  to a plain regression test when the fix landed.
- Under ``lexical_backend="bm25"`` (issue #96, after
  ``rag.rebuild_lexical_stats()``), the BM25 leg derives its query lexemes
  from ``to_tsvector('english', question) || pgrg_identifier_tsvector(...)``
  (see ``lexical.py``'s ``_QUERY_LEXEMES_EXPR``) -- the SAME parser path used
  on the chunk side, run on the raw question text rather than a pre-split
  regex. '-0001' survives intact, and its rarity (df=1 in this corpus) gives
  it a dominant IDF weight, so the ID chunk wins with clear separation.
"""

from __future__ import annotations

import os
import time
import uuid

import pytest

from pg_raggraph import GraphRAG
from pg_raggraph.config import PGRGConfig
from pg_raggraph.lexical import lexical_score_sql
from pg_raggraph.retrieval import _to_or_tsquery

pytestmark = pytest.mark.integration

DSN = os.environ.get("PGRG_TEST_DSN", "postgresql://postgres:postgres@localhost:5434/pg_raggraph")
NS = f"test_pgrg_{int(time.time())}_hyphen_id"

QUESTION = "what is the status of INC-0001?"

TARGET_CHUNK = (
    "Runbook: Incident INC-0001 root cause was disk pressure on the ingest "
    "worker. Restart to recover."
)
# tf-heavy decoys that repeat the generic 'inc' term without the actual ID --
# exactly what the naive tokenizer's lost '-0001' half should have excluded.
DECOY_CHUNKS = [
    "Vendor notes: Acme Inc is our storage vendor. Inc appears in every "
    "vendor contract. Inc, Inc, Inc reference.",
    "General incident process document with no specific ticket number "
    "referenced here regarding vendor Inc.",
]


@pytest.fixture
async def seeded_rag():
    """Namespace with one target chunk (the real INC-0001 doc) plus two
    'Inc'-heavy decoys, embeddings included."""
    rag = GraphRAG(dsn=DSN, namespace=NS)
    await rag.connect()
    await rag.delete(NS)

    from pg_raggraph.embedding import get_embedding_provider

    embedder = get_embedding_provider(rag.config)
    texts = [TARGET_CHUNK] + DECOY_CHUNKS
    embeddings = await embedder.embed(texts)

    doc_id = await rag.db.insert_returning_id(
        "INSERT INTO documents (namespace, content_hash, source_path) "
        "VALUES (%s, %s, %s) RETURNING id",
        (NS, uuid.uuid4().hex, "runbooks/inc-0001.md"),
    )
    chunk_ids = []
    for text, embedding in zip(texts, embeddings, strict=True):
        cid = await rag.db.insert_returning_id(
            "INSERT INTO chunks (document_id, content, embedding, token_count) "
            "VALUES (%s, %s, %s, %s) RETURNING id",
            (doc_id, text, embedding, len(text.split())),
        )
        chunk_ids.append(cid)

    try:
        yield rag, chunk_ids
    finally:
        await rag.delete(NS)
        await rag.close()


async def _lexical_scores(db, cfg: PGRGConfig, question: str) -> list[dict]:
    """Score every chunk in the namespace by the configured lexical leg
    only -- no embedding noise, pure backend comparison."""
    sql = (
        f"SELECT c.id, {lexical_score_sql(cfg, 'c')} AS s "
        "FROM chunks c JOIN documents d ON d.id = c.document_id "
        "WHERE d.namespace = %(namespace)s ORDER BY s DESC, c.id"
    )
    return await db.fetch_all(
        sql,
        {
            "namespace": NS,
            "query": question,
            "tsquery": _to_or_tsquery(question),
            "bm25_k1": cfg.bm25_k1,
            "bm25_b": cfg.bm25_b,
        },
    )


@pytest.mark.asyncio
async def test_hyphenated_id_tokenizer_asymmetry(seeded_rag):
    """Under the default lexical_backend='ts_rank', INC-0001 ranks first by
    its own ID (regression guard for the v0.9.1 tokenizer fix, #102/#103)."""
    rag, chunk_ids = seeded_rag
    target_id = chunk_ids[0]
    rows = await _lexical_scores(rag.db, PGRGConfig(), QUESTION)
    assert rows[0]["id"] == target_id, "expected the ID chunk to rank first under ts_rank"


@pytest.mark.asyncio
async def test_hyphenated_id_bm25_recovers_after_rebuild(seeded_rag):
    """Same corpus/question under lexical_backend='bm25' after
    rebuild_lexical_stats(): '-0001' survives tokenization on the query side,
    and its rarity (df=1) dominates the IDF-weighted score -- the ID chunk
    ranks first with clear separation from the decoys."""
    rag, chunk_ids = seeded_rag
    target_id = chunk_ids[0]
    await rag.rebuild_lexical_stats(NS)

    rows = await _lexical_scores(rag.db, PGRGConfig(lexical_backend="bm25"), QUESTION)
    assert rows[0]["id"] == target_id
    runner_up = rows[1]["s"]
    assert rows[0]["s"] > 1.5 * runner_up
