"""SC-012: per-(corpus, mode) JSON files parse back through ABRunnerOutput."""

import json
from pathlib import Path

import pytest

from pg_raggraph import GraphRAG
from pg_raggraph.ab_gate import GoldQuestion
from pg_raggraph.ab_gate.io import ABCaseResult, ABRetrievedItem, ABRunnerOutput
from pg_raggraph.ab_gate.runner import run_ab_matrix

pytestmark = pytest.mark.integration

DSN = "postgresql://postgres:postgres@localhost:5434/pg_raggraph"


async def _seed_tiny_corpus(rag: GraphRAG, ns: str) -> None:
    embedder = rag._get_embedder()
    doc_id = await rag.db.insert_returning_id(
        "INSERT INTO documents (namespace, content_hash, source_path) "
        "VALUES (%s, %s, %s) RETURNING id",
        (ns, f"seed:{ns}", f"/seed/{ns}.md"),
    )
    [emb] = await embedder.embed(["seed body for runner integration"])
    await rag.db.execute(
        "INSERT INTO chunks (document_id, content, embedded_content, embedding, metadata) "
        "VALUES (%s, %s, %s, %s, %s::jsonb)",
        (doc_id, "seed body", "seed body", emb, '{"kind": "episode"}'),
    )


def _parse_back(path: Path) -> ABRunnerOutput:
    data = json.loads(path.read_text())
    return ABRunnerOutput(
        corpus_id=data["corpus_id"],
        mode=data["mode"],
        results=[
            ABCaseResult(
                question_id=r["question_id"],
                question=r["question"],
                gold_answer=r.get("gold_answer"),
                retrieved=[
                    ABRetrievedItem(
                        rank=item["rank"],
                        source=item["source"],
                        score=item["score"],
                        content_snippet=item["content_snippet"],
                    )
                    for item in r["retrieved"]
                ],
                latency_ms=r["latency_ms"],
            )
            for r in data["results"]
        ],
    )


async def test_writes_one_file_per_corpus_per_mode(tmp_path: Path):
    ns = "test_ab_runner_writes"
    rag = GraphRAG(
        dsn=DSN,
        namespace=ns,
        llm_base_url="http://localhost:99999/v1",
        fact_extractor="lede_spacy",
    )
    await rag.connect()
    try:
        await rag.delete(ns)
        await _seed_tiny_corpus(rag, ns)
        gold = {ns: [GoldQuestion(id="q1", question="seed body")]}
        paths = await run_ab_matrix(
            rag,
            corpora=[ns],
            modes=["naive_vector"],
            gold_questions_per_corpus=gold,
            output_dir=tmp_path,
            top_k=10,
        )
        path = paths[(ns, "naive_vector")]
        assert path.exists()
        assert path.name == f"{ns}__naive_vector.json"
        parsed = _parse_back(path)
        assert parsed.corpus_id == ns
        assert parsed.mode == "naive_vector"
        assert len(parsed.results) == 1
        assert parsed.results[0].question_id == "q1"
    finally:
        await rag.delete(ns)
        await rag.close()
