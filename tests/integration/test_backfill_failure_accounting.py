"""Extraction failure accounting on the backfill path (issue #93).

Regression suite for the silent-extraction-failure incident: per-chunk LLM
errors used to yield empty results indistinguishable from "no entities in
this chunk", and the doc flipped to graph_status='ready' with a hollow
graph. Now:

- all chunks errored + zero yield  -> 'failed' + graph_error (retryable)
- some chunks errored, partial yield -> 'ready' + graph_error preserved
  ("degraded"; counted in graph_status_summary)
- no chunk errored, zero entities  -> plain 'ready', graph_error NULL
"""

import json
import os
import uuid

import pytest
from click.testing import CliRunner

from pg_raggraph import GraphRAG
from pg_raggraph.backfill import claim_pending, extract_documents
from pg_raggraph.cli import main

pytestmark = pytest.mark.integration

DSN = os.environ.get("PGRG_DSN", "postgresql://postgres:postgres@localhost:5434/pg_raggraph")


class _AlwaysFailLLM:
    """Every chunk-extraction call errors — the mlx-lm truncation class."""

    async def complete(self, messages):
        raise TimeoutError("simulated provider timeout")

    async def complete_text(self, messages, temperature=0.2):  # pragma: no cover
        raise TimeoutError("simulated provider timeout")


class _FailFirstLLM:
    """First call errors, the rest return a valid extraction — partial yield."""

    def __init__(self):
        self.calls = 0

    async def complete(self, messages):
        self.calls += 1
        if self.calls == 1:
            raise TimeoutError("simulated provider timeout")
        return (
            '{"entities": [{"name": "PostgreSQL", "entity_type": "technology",'
            ' "description": "the database"}], "relationships": []}'
        )

    async def complete_text(self, messages, temperature=0.2):  # pragma: no cover
        return ""


class _EmptyLLM:
    """Succeeds but finds nothing — a genuinely entity-free chunk."""

    async def complete(self, messages):
        return '{"entities": [], "relationships": []}'

    async def complete_text(self, messages, temperature=0.2):  # pragma: no cover
        return ""


async def _make_rag(namespace: str, **kwargs) -> GraphRAG:
    rag = GraphRAG(
        dsn=DSN,
        namespace=namespace,
        # Truthy base_url keeps the LLM leg enabled; the provider itself is
        # replaced with a fake before extraction runs.
        llm_base_url="http://localhost:9/v1",
        **kwargs,
    )
    await rag.connect()
    return rag


def _unique_text(n_sentences: int = 3) -> str:
    """Content unique per run so the shared pgrg_llm_cache can't interfere."""
    tag = uuid.uuid4().hex
    return " ".join(
        f"Sentence {i} about corpus {tag} and the PostgreSQL backfill path."
        for i in range(n_sentences)
    )


async def test_all_chunks_fail_marks_doc_failed_not_ready():
    """Acceptance (#93): every chunk-extraction call raising must NOT end in
    a plain 'ready' — the doc lands in 'failed' with graph_error set, and the
    summary shows it."""
    ns = "test_bf93_allfail"
    rag = await _make_rag(ns)
    try:
        await rag.ingest_records(
            [{"text": _unique_text(), "source_id": "bf93:allfail:1"}],
            namespace=ns,
            defer_extraction=True,
        )
        ids = await claim_pending(rag.db, ns, 8)
        assert len(ids) == 1

        rag._llm = _AlwaysFailLLM()
        stats = await extract_documents(rag, ids, namespace=ns)

        assert stats.failed == 1
        assert stats.ready == 0
        assert stats.chunks_failed >= 1
        assert stats.errors and "extraction failed on" in stats.errors[0][1]

        row = await rag.db.fetch_one(
            "SELECT graph_status, graph_error FROM documents WHERE id = %s", (ids[0],)
        )
        assert row["graph_status"] == "failed"
        assert row["graph_error"].startswith("extraction failed on ")
        assert "TimeoutError" in row["graph_error"]

        summary = await rag._graph_status_summary(ns)
        assert summary["failed"] == 1
        assert summary["ready"] == 0
    finally:
        await rag.delete(ns)
        await rag.close()


async def test_partial_failure_marks_ready_but_degraded():
    """Some chunks errored, others yielded → 'ready' with graph_error kept,
    yield persisted to metadata, and a 'degraded' count in the summary."""
    ns = "test_bf93_partial"
    # Small chunks so one doc produces at least two extraction calls.
    rag = await _make_rag(ns, chunk_max_tokens=64)
    try:
        await rag.ingest_records(
            [{"text": _unique_text(n_sentences=16), "source_id": "bf93:partial:1"}],
            namespace=ns,
            defer_extraction=True,
        )
        ids = await claim_pending(rag.db, ns, 8)
        assert len(ids) == 1
        n_chunks = (
            await rag.db.fetch_one(
                "SELECT count(*) AS n FROM chunks WHERE document_id = %s", (ids[0],)
            )
        )["n"]
        assert n_chunks >= 2, "test needs a multi-chunk doc"

        rag._llm = _FailFirstLLM()
        stats = await extract_documents(rag, ids, namespace=ns)

        assert stats.ready == 1
        assert stats.failed == 0
        assert stats.degraded == 1
        assert stats.chunks_failed == 1
        assert stats.entities >= 1

        row = await rag.db.fetch_one(
            "SELECT graph_status, graph_error, metadata FROM documents WHERE id = %s",
            (ids[0],),
        )
        assert row["graph_status"] == "ready"
        assert row["graph_error"] == (
            f"extraction failed on 1/{n_chunks} chunks: TimeoutError: simulated provider timeout"
        )
        meta = row["metadata"]
        if isinstance(meta, str):  # driver-dependent JSONB decoding
            meta = json.loads(meta)
        assert meta["extraction"]["chunks"] == n_chunks
        assert meta["extraction"]["chunks_failed"] == 1
        assert meta["extraction"]["entities"] >= 1

        summary = await rag._graph_status_summary(ns)
        assert summary["ready"] == 1
        assert summary["degraded"] == 1
        assert summary["failed"] == 0
    finally:
        await rag.delete(ns)
        await rag.close()


async def test_genuinely_empty_doc_stays_plain_ready():
    """Acceptance (#93): zero yield with NO chunk errors is not an error —
    the doc stays 'ready' with graph_error NULL and no degraded count."""
    ns = "test_bf93_empty"
    rag = await _make_rag(ns)
    try:
        await rag.ingest_records(
            [{"text": _unique_text(), "source_id": "bf93:empty:1"}],
            namespace=ns,
            defer_extraction=True,
        )
        ids = await claim_pending(rag.db, ns, 8)

        rag._llm = _EmptyLLM()
        stats = await extract_documents(rag, ids, namespace=ns)

        assert stats.ready == 1
        assert stats.failed == 0
        assert stats.degraded == 0

        row = await rag.db.fetch_one(
            "SELECT graph_status, graph_error, metadata FROM documents WHERE id = %s",
            (ids[0],),
        )
        assert row["graph_status"] == "ready"
        assert row["graph_error"] is None
        meta = row["metadata"]
        if isinstance(meta, str):
            meta = json.loads(meta)
        assert meta["extraction"]["chunks_failed"] == 0
        assert meta["extraction"]["entities"] == 0

        summary = await rag._graph_status_summary(ns)
        assert summary["degraded"] == 0
    finally:
        await rag.delete(ns)
        await rag.close()


async def test_sync_ingest_counts_per_chunk_failures_as_degraded():
    """Synchronous ingest: one errored chunk (not a whole-call raise) marks
    the doc degraded — graph_error persisted, chunks_failed in metadata."""
    ns = "test_bf93_sync"
    rag = await _make_rag(ns, chunk_max_tokens=64)
    try:
        rag._llm = _FailFirstLLM()
        await rag.ingest_records(
            [{"text": _unique_text(n_sentences=16), "source_id": "bf93:sync:1"}],
            namespace=ns,
        )

        row = await rag.db.fetch_one(
            "SELECT graph_status, graph_error, metadata FROM documents WHERE namespace = %s",
            (ns,),
        )
        assert row["graph_status"] == "ready"
        assert row["graph_error"] is not None
        assert row["graph_error"].startswith("extraction failed on 1/")
        meta = row["metadata"]
        if isinstance(meta, str):
            meta = json.loads(meta)
        assert meta["extraction"]["chunks_failed"] == 1

        summary = await rag._graph_status_summary(ns)
        assert summary["degraded"] == 1
    finally:
        await rag.delete(ns)
        await rag.close()


async def test_include_failed_requeues_failed_and_degraded_docs():
    """`pgrg extract --include-failed` retries both 'failed' docs and
    degraded 'ready' docs (graph_error set); clean ready docs are left alone."""
    ns = "test_bf93_retry"
    rag = await _make_rag(ns, chunk_max_tokens=64)
    try:
        await rag.ingest_records(
            [
                {"text": _unique_text(), "source_id": "bf93:retry:failed"},
                {"text": _unique_text(n_sentences=16), "source_id": "bf93:retry:degraded"},
                {"text": _unique_text(), "source_id": "bf93:retry:clean"},
            ],
            namespace=ns,
            defer_extraction=True,
        )

        # Doc 1 → 'failed' (every chunk errors).
        doc_failed = await rag.db.fetch_one(
            "SELECT id FROM documents WHERE namespace = %s AND source_path = %s",
            (ns, "bf93:retry:failed"),
        )
        rag._llm = _AlwaysFailLLM()
        await extract_documents(rag, [doc_failed["id"]])

        # Doc 2 → degraded 'ready' (first chunk errors, rest yield).
        doc_degraded = await rag.db.fetch_one(
            "SELECT id FROM documents WHERE namespace = %s AND source_path = %s",
            (ns, "bf93:retry:degraded"),
        )
        rag._llm = _FailFirstLLM()
        await extract_documents(rag, [doc_degraded["id"]])

        # Doc 3 → clean 'ready' with zero yield.
        doc_clean = await rag.db.fetch_one(
            "SELECT id FROM documents WHERE namespace = %s AND source_path = %s",
            (ns, "bf93:retry:clean"),
        )
        rag._llm = _EmptyLLM()
        await extract_documents(rag, [doc_clean["id"]])

        pre = {
            r["source_path"]: r["graph_status"]
            for r in await rag.db.fetch_all(
                "SELECT source_path, graph_status FROM documents WHERE namespace = %s", (ns,)
            )
        }
        assert pre["bf93:retry:failed"] == "failed"
        assert pre["bf93:retry:degraded"] == "ready"
        assert pre["bf93:retry:clean"] == "ready"

        clean_extracted_at = (
            await rag.db.fetch_one(
                "SELECT graph_extracted_at FROM documents WHERE id = %s", (doc_clean["id"],)
            )
        )["graph_extracted_at"]

        # Retry via the real CLI. PGRG_SKIP_EXTRACTION makes the retried docs
        # take the deterministic no-extractor path, so they terminate 'ready'
        # without a live LLM. Run in a thread — the CLI calls asyncio.run(),
        # which can't nest inside this test's running event loop.
        import asyncio

        runner = CliRunner()
        result = await asyncio.to_thread(
            runner.invoke,
            main,
            ["--db", DSN, "extract", "--namespace", ns, "--include-failed", "--once"],
            env={"PGRG_SKIP_EXTRACTION": "true"},
        )
        assert result.exit_code == 0, result.output

        rows = await rag.db.fetch_all(
            "SELECT source_path, graph_status, graph_error, graph_extracted_at "
            "FROM documents WHERE namespace = %s",
            (ns,),
        )
        by_src = {r["source_path"]: r for r in rows}
        # Failed and degraded docs were re-queued and re-extracted.
        assert by_src["bf93:retry:failed"]["graph_status"] == "ready"
        assert by_src["bf93:retry:failed"]["graph_error"] is None
        assert by_src["bf93:retry:degraded"]["graph_status"] == "ready"
        assert by_src["bf93:retry:degraded"]["graph_error"] is None
        # The clean ready doc was NOT re-queued (claim filter is pending-only).
        assert by_src["bf93:retry:clean"]["graph_status"] == "ready"
        assert by_src["bf93:retry:clean"]["graph_extracted_at"] == clean_extracted_at

        summary = await rag._graph_status_summary(ns)
        assert summary["failed"] == 0
        assert summary["degraded"] == 0
        assert summary["ready"] == 3
    finally:
        await rag.delete(ns)
        await rag.close()
