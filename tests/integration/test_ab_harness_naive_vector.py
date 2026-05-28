"""SC-002: naive_vector mode excludes fact rows. SC-008: top_k respected."""

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
        fact_extractor="lede_spacy",  # deterministic, no LLM needed
    )
    await rag.connect()
    return rag


async def _seed_episode_and_fact(rag: GraphRAG, ns: str) -> tuple[int, int]:
    """Insert one episode chunk and one fact-row chunk with similar embeddings.

    Both reference 'Bostock v. Clayton County'. The naive_vector mode
    must return the episode chunk and NOT the fact row (chunkshop §4.2).
    Returns (episode_chunk_id, fact_chunk_id).
    """
    embedder = rag._get_embedder()
    doc_id = await rag.db.insert_returning_id(
        "INSERT INTO documents (namespace, content_hash, source_path, metadata) "
        "VALUES (%s, %s, %s, %s::jsonb) RETURNING id",
        (ns, "seed:bostock:doc", "/seed/bostock.md", "{}"),
    )
    [emb_episode, emb_fact] = await embedder.embed(
        [
            "Bostock v. Clayton County held that Title VII covers sexual orientation.",
            "Bostock cites Title VII as the controlling statute.",
        ]
    )
    episode_id = await rag.db.insert_returning_id(
        "INSERT INTO chunks (document_id, content, embedded_content, embedding, metadata) "
        "VALUES (%s, %s, %s, %s, %s::jsonb) RETURNING id",
        (
            doc_id,
            "Bostock v. Clayton County held Title VII covers sexual orientation.",
            "Bostock v. Clayton County held Title VII covers sexual orientation.",
            emb_episode,
            '{"kind": "episode"}',
        ),
    )
    fact_id = await rag.db.insert_returning_id(
        "INSERT INTO chunks (document_id, content, embedded_content, embedding, metadata) "
        "VALUES (%s, %s, %s, %s, %s::jsonb) RETURNING id",
        (
            doc_id,
            "Bostock cites Title VII",
            "Bostock cites Title VII",
            emb_fact,
            '{"kind": "fact", "subject": "Bostock", "predicate": "cites", "object": "Title VII"}',
        ),
    )
    return episode_id, fact_id


async def test_excludes_fact_rows():
    ns = "test_ab_nv_facts"
    rag = await _connect(ns)
    try:
        await rag.delete(ns)
        await _seed_episode_and_fact(rag, ns)
        gold = [GoldQuestion(id="q1", question="What did Bostock hold about Title VII?")]
        out = await run_harness_mode(
            rag, corpus_id=ns, mode="naive_vector", gold_questions=gold, top_k=10
        )
        assert out.corpus_id == ns
        assert out.mode == "naive_vector"
        assert len(out.results) == 1
        retrieved = out.results[0].retrieved
        assert retrieved, "expected at least one retrieved item"
        # No fact-row chunk should ever surface in naive_vector results.
        fact_present = any("cites" in item.content_snippet for item in retrieved)
        assert not fact_present, (
            f"naive_vector returned a fact-row chunk; chunkshop §4.2 says it must "
            f"be excluded via WHERE metadata->>'kind' IS DISTINCT FROM 'fact'. "
            f"retrieved={retrieved!r}"
        )
    finally:
        await rag.delete(ns)
        await rag.close()


async def test_top_k_respected_small():
    ns = "test_ab_nv_topk_small"
    rag = await _connect(ns)
    try:
        await rag.delete(ns)
        embedder = rag._get_embedder()
        doc_id = await rag.db.insert_returning_id(
            "INSERT INTO documents (namespace, content_hash, source_path) "
            "VALUES (%s, %s, %s) RETURNING id",
            (ns, "seed:topk:doc", "/seed/topk.md"),
        )
        texts = [f"chunk number {i} about apples" for i in range(8)]
        embs = await embedder.embed(texts)
        for text, emb in zip(texts, embs):
            await rag.db.execute(
                "INSERT INTO chunks (document_id, content, embedded_content, embedding, metadata) "
                "VALUES (%s, %s, %s, %s, %s::jsonb)",
                (doc_id, text, text, emb, '{"kind": "episode"}'),
            )
        gold = [GoldQuestion(id="q1", question="apples")]
        out = await run_harness_mode(
            rag, corpus_id=ns, mode="naive_vector", gold_questions=gold, top_k=3
        )
        assert len(out.results[0].retrieved) <= 3
    finally:
        await rag.delete(ns)
        await rag.close()
