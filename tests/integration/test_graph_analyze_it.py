"""Integration tests for graph_analyze (issue #100) — the cap-gold-v1 Tier 3
shape as a public API call.

Builds a synthetic citation graph (no LLM):

    caseA —CITES→ caseB —CITES→ landmark
    caseC —CITES→ landmark
    caseD —CITES→ landmark
    caseE (isolated; never reachable from caseA)

so a 2-hop CITES expansion from caseA reaches {caseA, caseB, landmark};
the landmark's in-degree is 3, caseB's is 1, caseA's is 0. Documents carry
a structured ``decision_year`` for the filter stage.
"""

from __future__ import annotations

import json
import os
import time
import uuid

import pytest

from pg_raggraph import GraphRAG
from pg_raggraph.graph_analyze import (
    RRF,
    Authority,
    Expand,
    MetadataFilter,
    NameSeed,
    SemanticSeed,
)

pytestmark = pytest.mark.integration

DSN = os.environ.get("PGRG_TEST_DSN", "postgresql://postgres:postgres@localhost:5434/pg_raggraph")
NS = f"test_pgrg_{int(time.time())}_graph_analyze"

# name -> (chunk text, decision_year, entity_type). caseE is typed "matter",
# not "case": the SemanticSeed entity_type filter must exclude it
# deterministically (short same-shaped texts embed too similarly for a
# purely semantic exclusion to be stable).
CASES = {
    "caseA": ("Case A: appellant challenges the standard for injunctive relief.", 2001, "case"),
    "caseB": ("Case B: interlocutory appeal on preliminary injunction factors.", 1995, "case"),
    "landmark": ("Landmark: the four-factor test for preliminary injunctions.", 1980, "case"),
    "caseC": ("Case C: applies the landmark injunction factors to trade secrets.", 1998, "case"),
    "caseD": ("Case D: applies the landmark injunction factors to patents.", 2005, "case"),
    "caseE": ("Case E: unrelated tax controversy on partnership basis.", 2010, "matter"),
}
CITES = [
    ("caseA", "caseB"),
    ("caseB", "landmark"),
    ("caseC", "landmark"),
    ("caseD", "landmark"),
]


@pytest.fixture
async def seeded():
    rag = GraphRAG(dsn=DSN, namespace=NS, structured_metadata_fields=["decision_year"])
    await rag.connect()
    await rag.delete(NS)

    from pg_raggraph.embedding import get_embedding_provider

    embedder = get_embedding_provider(rag.config)
    names = list(CASES)
    embeddings = await embedder.embed([CASES[n][0] for n in names])

    entity_ids: dict[str, int] = {}
    chunk_ids: dict[str, int] = {}
    for name, emb in zip(names, embeddings, strict=True):
        text, year, entity_type = CASES[name]
        doc_id = await rag.db.insert_returning_id(
            "INSERT INTO documents (namespace, content_hash, source_path, metadata) "
            "VALUES (%s, %s, %s, %s) RETURNING id",
            (NS, uuid.uuid4().hex, f"cases/{name}.md", json.dumps({"decision_year": year})),
        )
        cid = await rag.db.insert_returning_id(
            "INSERT INTO chunks (document_id, content, embedding, token_count) "
            "VALUES (%s, %s, %s, %s) RETURNING id",
            (doc_id, text, emb, len(text.split())),
        )
        chunk_ids[name] = cid
        eid = await rag.db.insert_returning_id(
            "INSERT INTO entities (namespace, name, entity_type, description, embedding) "
            "VALUES (%s, %s, %s, %s, %s) RETURNING id",
            (NS, name, entity_type, text, emb),
        )
        entity_ids[name] = eid
        await rag.db.execute(
            "INSERT INTO entity_chunks (entity_id, chunk_id) VALUES (%s, %s)",
            (eid, cid),
        )
    for src, dst in CITES:
        await rag.db.execute(
            "INSERT INTO relationships (namespace, src_id, dst_id, rel_type) "
            "VALUES (%s, %s, %s, %s)",
            (NS, entity_ids[src], entity_ids[dst], "CITES"),
        )

    try:
        yield rag, entity_ids, chunk_ids
    finally:
        await rag.delete(NS)
        await rag.close()


@pytest.mark.asyncio
async def test_id_seed_expansion_and_authority(seeded):
    """2-hop CITES expansion from caseA reaches the landmark; authority is
    the targeted in-degree over the expanded set."""
    rag, entity_ids, chunk_ids = seeded
    rows = await rag.graph_analyze(
        seed=[entity_ids["caseA"]],
        expand=Expand(rel_types="CITES", direction="out", max_hops=2),
        fuse=RRF(legs=("authority",)),
        top_k=10,
    )
    by_chunk = {r.chunk_id: r for r in rows}
    assert set(by_chunk) == {chunk_ids["caseA"], chunk_ids["caseB"], chunk_ids["landmark"]}
    assert by_chunk[chunk_ids["landmark"]].authority == 3
    assert by_chunk[chunk_ids["caseB"]].authority == 1
    assert by_chunk[chunk_ids["caseA"]].authority == 0
    # authority-only fusion: the landmark ranks first
    assert rows[0].chunk_id == chunk_ids["landmark"]
    # id-seeded plans carry no semantic leg
    assert all(r.semantic_score is None for r in rows)


@pytest.mark.asyncio
async def test_one_hop_does_not_reach_landmark(seeded):
    rag, entity_ids, chunk_ids = seeded
    rows = await rag.graph_analyze(
        seed=[entity_ids["caseA"]],
        expand=Expand(rel_types="CITES", max_hops=1),
        fuse=RRF(legs=("authority",)),
    )
    assert chunk_ids["landmark"] not in {r.chunk_id for r in rows}


@pytest.mark.asyncio
async def test_metadata_filter_excludes_old_decisions(seeded):
    """The landmark (1980) is expanded into the hood and still scores
    authority, but the structured-field filter drops its chunk."""
    rag, entity_ids, chunk_ids = seeded
    rows = await rag.graph_analyze(
        seed=[entity_ids["caseA"]],
        expand=Expand(rel_types="CITES", max_hops=2),
        filter=MetadataFilter({"decision_year": ("gte", 1990)}),
        fuse=RRF(legs=("authority",)),
    )
    returned = {r.chunk_id for r in rows}
    assert chunk_ids["landmark"] not in returned
    assert {chunk_ids["caseA"], chunk_ids["caseB"]} <= returned


@pytest.mark.asyncio
async def test_metadata_filter_rejects_unstructured_field(seeded):
    rag, entity_ids, _ = seeded
    with pytest.raises(ValueError, match="not a structured field"):
        await rag.graph_analyze(
            seed=[entity_ids["caseA"]],
            expand=Expand(rel_types="CITES"),
            filter=MetadataFilter({"free_text_topic": "injunctions"}),
        )


@pytest.mark.asyncio
async def test_semantic_seed_full_tier3_shape(seeded):
    """The full PGRG_TIER3 pipeline: semantic top-K seed → typed 2-hop
    expansion → in-degree authority → RRF(semantic, authority)."""
    rag, _, chunk_ids = seeded
    rows = await rag.graph_analyze(
        seed=SemanticSeed(
            "What is the standard for preliminary injunctive relief?",
            top_k=6,
            # caseE is entity_type="matter": the seed's type filter excludes
            # it deterministically, and with no edges touching it, it stays
            # out of the pool entirely (the negative control).
            entity_type="case",
        ),
        expand=Expand(rel_types="CITES", direction="out", max_hops=2),
        score=Authority(metric="in_degree", rel_types="CITES"),
        fuse=RRF(legs=("semantic", "authority")),
        top_k=10,
    )
    assert rows, "semantic-seeded plan returned nothing"
    by_chunk = {r.chunk_id: r for r in rows}
    # the landmark is reachable (via citations) and carries in-degree 3
    assert by_chunk[chunk_ids["landmark"]].authority == 3
    # semantic leg populated, fused scores ordered
    assert all(r.semantic_score is not None for r in rows)
    assert [r.score for r in rows] == sorted((r.score for r in rows), reverse=True)
    # the isolated tax case never enters the pool
    assert chunk_ids["caseE"] not in by_chunk


@pytest.mark.asyncio
async def test_name_seed_binds_fuzzily(seeded):
    rag, _, chunk_ids = seeded
    rows = await rag.graph_analyze(
        seed=NameSeed("case a", entity_type="case"),  # case-insensitive binding
        expand=Expand(rel_types="CITES", max_hops=2),
        fuse=RRF(legs=("authority",)),
    )
    assert chunk_ids["landmark"] in {r.chunk_id for r in rows}


@pytest.mark.asyncio
async def test_name_seed_unbindable_returns_empty(seeded):
    rag, _, _ = seeded
    rows = await rag.graph_analyze(
        seed=NameSeed("zzz-no-such-entity-zzz", fuzzy=False),
        expand=Expand(rel_types="CITES"),
    )
    assert rows == []
