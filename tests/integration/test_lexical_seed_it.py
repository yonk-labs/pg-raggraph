"""Regression test for vector-only graph-mode seeding (issue #105).

`_build_local_query` seeded traversal by pure vector-kNN over entity
embeddings; `_build_global_query` seeded relationships the same way. When
the query's anchor is an opaque identifier (case ids, ticket numbers),
vector-kNN anchors the wrong entities, the gold chunk never enters the
graph-gated candidate pool, and no downstream scoring can recover.

The corpus here makes the pre-fix failure deterministic, not probabilistic:
every decoy entity carries the *question's own embedding* (cosine sim 1.0),
so the seed_k=5 vector slots are always fully occupied by decoys and the
CASE-2021-0454 entity can never enter the seed set through the vector leg.
Only the lexical leg (word_similarity over entity names, #105) can anchor
it — these tests fail on pre-fix builders by construction.
"""

from __future__ import annotations

import os
import time
import uuid

import pytest

from pg_raggraph import GraphRAG

pytestmark = pytest.mark.integration

DSN = os.environ.get("PGRG_TEST_DSN", "postgresql://postgres:postgres@localhost:5434/pg_raggraph")
NS = f"test_pgrg_{int(time.time())}_lexical_seed"

QUESTION = "What is the current status of case CASE-2021-0454?"

GOLD_CHUNK = (
    "Case record CASE-2021-0454: motion granted on appeal; the matter is "
    "stayed pending review by the circuit panel."
)
DECOY_CHUNKS = [
    "Quarterly overview of active matters and staffing across the office.",
    "Process notes on docket management and scheduling conventions.",
    "General discussion of appellate workflows and review timelines.",
]
N_DECOY_ENTITIES = 8  # > seed_k (5): vector slots always fill with decoys


@pytest.fixture
async def seeded_rag():
    rag = GraphRAG(dsn=DSN, namespace=NS)
    await rag.connect()
    await rag.delete(NS)

    from pg_raggraph.embedding import get_embedding_provider

    embedder = get_embedding_provider(rag.config)
    texts = [QUESTION, GOLD_CHUNK, "CASE-2021-0454"] + DECOY_CHUNKS
    q_emb, gold_emb, id_emb, *decoy_embs = await embedder.embed(texts)

    doc_id = await rag.db.insert_returning_id(
        "INSERT INTO documents (namespace, content_hash, source_path) "
        "VALUES (%s, %s, %s) RETURNING id",
        (NS, uuid.uuid4().hex, "cases/case-2021-0454.md"),
    )
    gold_chunk_id = await rag.db.insert_returning_id(
        "INSERT INTO chunks (document_id, content, embedding, token_count) "
        "VALUES (%s, %s, %s, %s) RETURNING id",
        (doc_id, GOLD_CHUNK, gold_emb, len(GOLD_CHUNK.split())),
    )
    decoy_chunk_ids = []
    for text, emb in zip(DECOY_CHUNKS, decoy_embs, strict=True):
        cid = await rag.db.insert_returning_id(
            "INSERT INTO chunks (document_id, content, embedding, token_count) "
            "VALUES (%s, %s, %s, %s) RETURNING id",
            (doc_id, text, emb, len(text.split())),
        )
        decoy_chunk_ids.append(cid)

    # The gold entity: opaque identifier, embedded as the opaque string it is.
    id_entity = await rag.db.insert_returning_id(
        "INSERT INTO entities (namespace, name, entity_type, description, embedding) "
        "VALUES (%s, %s, %s, %s, %s) RETURNING id",
        (NS, "CASE-2021-0454", "case", "Appeal, stayed pending review", id_emb),
    )
    await rag.db.execute(
        "INSERT INTO entity_chunks (entity_id, chunk_id) VALUES (%s, %s)",
        (id_entity, gold_chunk_id),
    )

    # Decoy entities: names lexically unrelated to the question, embeddings
    # IDENTICAL to the question's — they occupy every vector seed slot.
    decoy_ids = []
    for i in range(N_DECOY_ENTITIES):
        eid = await rag.db.insert_returning_id(
            "INSERT INTO entities (namespace, name, entity_type, description, embedding) "
            "VALUES (%s, %s, %s, %s, %s) RETURNING id",
            (NS, f"docket workflow topic {i}", "concept", "generic office theme", q_emb),
        )
        decoy_ids.append(eid)
        await rag.db.execute(
            "INSERT INTO entity_chunks (entity_id, chunk_id) VALUES (%s, %s)",
            (eid, decoy_chunk_ids[i % len(decoy_chunk_ids)]),
        )

    # Relationships among decoys only: global mode's rel_matches can never
    # reach the gold entity through the relationship-seeded leg.
    for a, b in zip(decoy_ids, decoy_ids[1:], strict=False):
        await rag.db.execute(
            "INSERT INTO relationships (namespace, src_id, dst_id, rel_type) "
            "VALUES (%s, %s, %s, %s)",
            (NS, a, b, "RELATED_TO"),
        )

    try:
        yield rag, gold_chunk_id
    finally:
        await rag.delete(NS)
        await rag.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["local", "global", "hybrid"])
async def test_exact_id_anchors_graph_modes(seeded_rag, mode):
    """The gold chunk enters the graph-gated pool through the lexical seed
    leg despite every vector seed slot being occupied by decoys."""
    rag, gold_chunk_id = seeded_rag
    result = await rag.query(QUESTION, mode=mode, top_k=10)
    returned = [c.chunk_id for c in result.chunks]
    assert gold_chunk_id in returned, (
        f"gold chunk missing from {mode} results — lexical seed leg (#105) "
        f"did not anchor the CASE-2021-0454 entity (got chunks {returned})"
    )


@pytest.mark.asyncio
async def test_unrelated_query_keeps_vector_only_seeding(seeded_rag):
    """A question with no entity-name mention must behave exactly as before:
    the lexical leg matches nothing and the vector leg drives seeding."""
    rag, gold_chunk_id = seeded_rag
    result = await rag.query(
        "Summarize appellate workflows and scheduling conventions.",
        mode="local",
        top_k=10,
    )
    assert result.chunks, "vector-only seeding regressed for lexical-miss queries"
