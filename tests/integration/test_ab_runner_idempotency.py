"""SC-019: a second run cleanly overwrites the first run's per-cell JSONs."""

import json
from pathlib import Path

import pytest

from pg_raggraph import GraphRAG
from pg_raggraph.ab_gate import GoldQuestion
from pg_raggraph.ab_gate.runner import run_ab_matrix

pytestmark = pytest.mark.integration

DSN = "postgresql://postgres:postgres@localhost:5434/pg_raggraph"


async def test_overwrite_is_clean(tmp_path: Path):
    ns = "test_ab_runner_idem"
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
        [emb] = await embedder.embed(["idem body"])
        await rag.db.execute(
            "INSERT INTO chunks (document_id, content, embedded_content, embedding, metadata) "
            "VALUES (%s, %s, %s, %s, %s::jsonb)",
            (doc_id, "idem body", "idem body", emb, '{"kind": "episode"}'),
        )
        gold = {ns: [GoldQuestion(id="q1", question="idem body")]}

        # First run.
        await run_ab_matrix(
            rag,
            corpora=[ns],
            modes=["naive_vector"],
            gold_questions_per_corpus=gold,
            output_dir=tmp_path,
            top_k=10,
        )
        first_manifest = json.loads((tmp_path / "manifest.json").read_text())
        first_started = first_manifest["run_started_at"]

        # Second run with same output_dir.
        await run_ab_matrix(
            rag,
            corpora=[ns],
            modes=["naive_vector"],
            gold_questions_per_corpus=gold,
            output_dir=tmp_path,
            top_k=10,
        )
        second_manifest = json.loads((tmp_path / "manifest.json").read_text())
        assert second_manifest["run_started_at"] != first_started, (
            "second-run manifest must have a different run_started_at"
        )

        data = json.loads((tmp_path / f"{ns}__naive_vector.json").read_text())
        assert data["corpus_id"] == ns
        assert len(data["results"]) == 1
        assert isinstance(data, dict)
        assert set(data.keys()) >= {"corpus_id", "mode", "results"}
    finally:
        await rag.delete(ns)
        await rag.close()
