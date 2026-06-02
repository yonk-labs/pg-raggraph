"""SC-014: every ABCaseResult.latency_ms is a non-negative float ≤ 60000."""

import json
from pathlib import Path

import pytest

from pg_raggraph import GraphRAG
from pg_raggraph.ab_gate import GoldQuestion
from pg_raggraph.ab_gate.runner import run_ab_matrix

pytestmark = pytest.mark.integration

DSN = "postgresql://postgres:postgres@localhost:5434/pg_raggraph"


async def test_per_case_latency_within_bounds(tmp_path: Path):
    ns = "test_ab_runner_latency"
    rag = GraphRAG(
        dsn=DSN,
        namespace=ns,
        llm_base_url="http://localhost:99999/v1",
        fact_extractor="lede_spacy",
    )
    await rag.connect()
    try:
        await rag.delete(ns)
        embedder = rag._get_embedder()
        doc_id = await rag.db.insert_returning_id(
            "INSERT INTO documents (namespace, content_hash, source_path) "
            "VALUES (%s, %s, %s) RETURNING id",
            (ns, f"seed:{ns}", f"/seed/{ns}.md"),
        )
        [emb] = await embedder.embed(["latency test body"])
        await rag.db.execute(
            "INSERT INTO chunks (document_id, content, embedded_content, embedding, metadata) "
            "VALUES (%s, %s, %s, %s, %s::jsonb)",
            (doc_id, "latency test body", "latency test body", emb, '{"kind": "episode"}'),
        )
        gold = {
            ns: [
                GoldQuestion(id="q1", question="latency test body"),
                GoldQuestion(id="q2", question="other question"),
            ]
        }
        paths = await run_ab_matrix(
            rag,
            corpora=[ns],
            modes=["naive_vector"],
            gold_questions_per_corpus=gold,
            output_dir=tmp_path,
            top_k=10,
        )
        data = json.loads(paths[(ns, "naive_vector")].read_text())
        for case in data["results"]:
            lat = case["latency_ms"]
            assert isinstance(lat, float), f"latency_ms must be float; got {type(lat)}"
            assert 0.0 <= lat <= 60000.0, f"latency_ms out of bounds: {lat}"
    finally:
        await rag.delete(ns)
        await rag.close()
