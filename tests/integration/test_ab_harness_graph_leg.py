"""SC-004: fact-triple walk. SC-005: cooccur walk. SC-006: episode-only citations.
SC-008 (continued): top_k=20 returns up to 20.
"""

import json

import pytest

from pg_raggraph import GraphRAG
from pg_raggraph.ab_gate import GoldQuestion
from pg_raggraph.ab_gate.harness import run_harness_mode

pytestmark = pytest.mark.integration

DSN = "postgresql://postgres:postgres@localhost:5434/pg_raggraph"


async def _connect(ns: str) -> GraphRAG:
    rag = GraphRAG(
        dsn=DSN,
        namespace=ns,
        llm_base_url="http://localhost:99999/v1",
        fact_extractor="lede_spacy",
    )
    await rag.connect()
    return rag


async def _seed_entity(rag: GraphRAG, ns: str, name: str) -> int:
    """Insert one entity row, return id."""
    embedder = rag._get_embedder()
    [emb] = await embedder.embed([name])
    row = await rag.db.fetch_one(
        "INSERT INTO entities (namespace, name, entity_type, description, embedding) "
        "VALUES (%s, %s, 'entity', '', %s) RETURNING id",
        (ns, name, emb),
    )
    return int(row["id"])


async def _seed_episode_with_fact(
    rag: GraphRAG,
    ns: str,
    *,
    subject: str,
    predicate: str,
    obj: str,
    source_path: str,
) -> tuple[int, int]:
    """Insert one episode chunk + one fact-row chunk pointing at the same fact."""
    embedder = rag._get_embedder()
    doc_id = await rag.db.insert_returning_id(
        "INSERT INTO documents (namespace, content_hash, source_path) "
        "VALUES (%s, %s, %s) RETURNING id",
        (ns, f"seed:{subject}:{predicate}:{obj}", source_path),
    )
    [emb_ep, emb_f] = await embedder.embed(
        [
            f"{subject} {predicate} {obj} — episode body",
            f"{subject} {predicate} {obj} — fact",
        ]
    )
    ep_id = await rag.db.insert_returning_id(
        "INSERT INTO chunks (document_id, content, embedded_content, embedding, metadata) "
        "VALUES (%s, %s, %s, %s, %s::jsonb) RETURNING id",
        (
            doc_id,
            f"{subject} {predicate} {obj}",
            f"{subject} {predicate} {obj}",
            emb_ep,
            '{"kind": "episode"}',
        ),
    )
    fact_meta = json.dumps(
        {"kind": "fact", "subject": subject, "predicate": predicate, "object": obj}
    )
    f_id = await rag.db.insert_returning_id(
        "INSERT INTO chunks (document_id, content, embedded_content, embedding, metadata) "
        "VALUES (%s, %s, %s, %s, %s::jsonb) RETURNING id",
        (
            doc_id,
            f"{subject} {predicate} {obj}",
            f"{subject} {predicate} {obj}",
            emb_f,
            fact_meta,
        ),
    )
    return ep_id, f_id


async def _seed_episode_with_cooccur(
    rag: GraphRAG,
    ns: str,
    *,
    a: str,
    b: str,
    source_path: str,
) -> int:
    """Insert one episode chunk carrying a cooccur entry. Returns chunk_id."""
    embedder = rag._get_embedder()
    doc_id = await rag.db.insert_returning_id(
        "INSERT INTO documents (namespace, content_hash, source_path) "
        "VALUES (%s, %s, %s) RETURNING id",
        (ns, f"seed:cooccur:{a}:{b}", source_path),
    )
    [emb] = await embedder.embed([f"{a} and {b} appear together"])
    meta = json.dumps({"kind": "episode", "cooccur": [{"a": a, "b": b, "weight": 0.8}]})
    ep_id = await rag.db.insert_returning_id(
        "INSERT INTO chunks (document_id, content, embedded_content, embedding, metadata) "
        "VALUES (%s, %s, %s, %s, %s::jsonb) RETURNING id",
        (doc_id, f"{a} and {b}", f"{a} and {b}", emb, meta),
    )
    return ep_id


async def test_one_hop_fact_walk():
    """SC-004."""
    ns = "test_ab_gl_facts"
    rag = await _connect(ns)
    try:
        await rag.delete(ns)
        await _seed_entity(rag, ns, "Bostock")
        await _seed_episode_with_fact(
            rag,
            ns,
            subject="Bostock",
            predicate="cites",
            obj="Title VII",
            source_path="/seed/bostock.md",
        )
        gold = [GoldQuestion(id="q1", question="What did Bostock cite?")]
        out = await run_harness_mode(
            rag, corpus_id=ns, mode="graph_leg", gold_questions=gold, top_k=10
        )
        assert len(out.results) == 1
        retrieved = out.results[0].retrieved
        assert retrieved, "expected at least one retrieved item from fact-triple walk"
        sources = [item.source for item in retrieved]
        assert "/seed/bostock.md" in sources, f"expected episode source path; got {sources}"
    finally:
        await rag.delete(ns)
        await rag.close()


async def test_one_hop_cooccur_walk():
    """SC-005."""
    ns = "test_ab_gl_cooccur"
    rag = await _connect(ns)
    try:
        await rag.delete(ns)
        await _seed_entity(rag, ns, "Apple")
        await _seed_episode_with_cooccur(
            rag, ns, a="Apple", b="iPhone", source_path="/seed/apple.md"
        )
        gold = [GoldQuestion(id="q1", question="What is Apple associated with?")]
        out = await run_harness_mode(
            rag, corpus_id=ns, mode="graph_leg", gold_questions=gold, top_k=10
        )
        retrieved = out.results[0].retrieved
        assert retrieved, "expected at least one retrieved item from cooccur walk"
        sources = [item.source for item in retrieved]
        assert "/seed/apple.md" in sources, f"expected cooccur episode source; got {sources}"
    finally:
        await rag.delete(ns)
        await rag.close()


async def test_only_episode_rows_cited():
    """SC-006."""
    ns = "test_ab_gl_episode_only"
    rag = await _connect(ns)
    try:
        await rag.delete(ns)
        await _seed_entity(rag, ns, "NASA")
        await _seed_episode_with_fact(
            rag,
            ns,
            subject="NASA",
            predicate="launched",
            obj="Saturn V",
            source_path="/seed/nasa.md",
        )
        gold = [GoldQuestion(id="q1", question="What did NASA launch?")]
        out = await run_harness_mode(
            rag, corpus_id=ns, mode="graph_leg", gold_questions=gold, top_k=10
        )
        for item in out.results[0].retrieved:
            row = await rag.db.fetch_one(
                "SELECT c.metadata->>'kind' AS kind "
                "FROM chunks c JOIN documents d ON d.id = c.document_id "
                "WHERE d.namespace = %s AND d.source_path = %s "
                "ORDER BY c.id LIMIT 1",
                (ns, item.source),
            )
            assert row is not None, f"could not find chunk for source={item.source}"
            assert row["kind"] == "episode", (
                f"graph_leg cited a non-episode chunk ({row['kind']}) for {item.source}"
            )
    finally:
        await rag.delete(ns)
        await rag.close()


async def test_top_k_respected_large():
    """SC-008 continued."""
    ns = "test_ab_gl_topk"
    rag = await _connect(ns)
    try:
        await rag.delete(ns)
        await _seed_entity(rag, ns, "Apple")
        for i in range(25):
            await _seed_episode_with_cooccur(
                rag, ns, a="Apple", b=f"product_{i}", source_path=f"/seed/apple_{i}.md"
            )
        gold = [GoldQuestion(id="q1", question="What is Apple?")]
        out = await run_harness_mode(
            rag, corpus_id=ns, mode="graph_leg", gold_questions=gold, top_k=20
        )
        assert len(out.results[0].retrieved) <= 20
    finally:
        await rag.delete(ns)
        await rag.close()
