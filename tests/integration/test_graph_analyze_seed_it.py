"""Regression test for vector-only SemanticSeed seeding (issue #115).

``graph_analyze``'s SemanticSeed stage ranked chunks purely by cosine
distance. On template-near-duplicate corpora cosine among siblings is
uniform noise and a semantically-central hub chunk wins the seed slots for
every query — the reporter observed the identical noise chunk seeding
regardless of query, so traversal starts from a noise anchor and the gold
chunk never enters the plan. Same failure class #105 fixed for the
local/global builders; this test pins the same fix (lexical entity-anchor
leg unioned into ``seeds``) on graph_analyze.

The corpus makes the pre-fix failure deterministic, not probabilistic:
every decoy chunk carries the *question's own embedding* (cosine distance
0), so the SemanticSeed top-k slots are always fully occupied by decoys
and the CASE-2021-0454 entity can never seed through the vector leg. Only
the lexical leg (word_similarity over entity names) can anchor it — this
test fails on the pre-fix builder by construction.
"""

from __future__ import annotations

import os
import time
import uuid

import pytest

from pg_raggraph import GraphRAG
from pg_raggraph.graph_analyze import Expand, SemanticSeed

pytestmark = pytest.mark.integration

DSN = os.environ.get("PGRG_TEST_DSN", "postgresql://postgres:postgres@localhost:5434/pg_raggraph")
NS = f"test_pgrg_{int(time.time())}_ga_seed"

QUESTION = "What is the current status of case CASE-2021-0454?"

GOLD_CHUNK = (
    "Case record CASE-2021-0454: motion granted on appeal; the matter is "
    "stayed pending review by the circuit panel."
)
N_DECOYS = 8  # > SemanticSeed.top_k below: vector slots always fill with decoys


@pytest.fixture
async def seeded_rag():
    rag = GraphRAG(dsn=DSN, namespace=NS)
    await rag.connect()
    await rag.delete(NS)

    from pg_raggraph.embedding import get_embedding_provider

    embedder = get_embedding_provider(rag.config)
    q_emb, gold_emb = await embedder.embed([QUESTION, GOLD_CHUNK])

    async def _insert(name: str, text: str, emb) -> None:
        doc_id = await rag.db.insert_returning_id(
            "INSERT INTO documents (namespace, content_hash, source_path) "
            "VALUES (%s, %s, %s) RETURNING id",
            (NS, uuid.uuid4().hex, f"docs/{name}.md"),
        )
        cid = await rag.db.insert_returning_id(
            "INSERT INTO chunks (document_id, content, embedding, token_count) "
            "VALUES (%s, %s, %s, %s) RETURNING id",
            (doc_id, text, emb, len(text.split())),
        )
        eid = await rag.db.insert_returning_id(
            "INSERT INTO entities (namespace, name, entity_type, description, embedding) "
            "VALUES (%s, %s, %s, %s, %s) RETURNING id",
            (NS, name, "case", text, emb),
        )
        await rag.db.execute(
            "INSERT INTO entity_chunks (entity_id, chunk_id) VALUES (%s, %s)",
            (eid, cid),
        )

    await _insert("CASE-2021-0454", GOLD_CHUNK, gold_emb)
    for i in range(N_DECOYS):
        # Decoy chunks carry the question's own embedding: deterministic
        # occupation of every vector seed slot.
        await _insert(f"process note {i}", f"General process note {i} on docket workflows.", q_emb)

    try:
        yield rag
    finally:
        await rag.delete(NS)
        await rag.close()


@pytest.mark.asyncio
async def test_semantic_seed_anchors_verbatim_entity_name(seeded_rag):
    """The gold chunk must reach the results even though the vector seed
    slots are saturated by decoys — only the lexical entity leg can put
    CASE-2021-0454 into the seed set."""
    rows = await seeded_rag.graph_analyze(
        seed=SemanticSeed(QUESTION, top_k=5),
        expand=Expand(max_hops=1),
        top_k=20,
        namespace=NS,
    )
    contents = [r.content for r in rows]
    assert any("CASE-2021-0454" in c for c in contents), (
        f"gold chunk never entered the plan; got: {contents}"
    )
