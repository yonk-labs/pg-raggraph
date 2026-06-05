"""Runnable sample: a bounded-memory ingest service over pg-raggraph (issue #46).

pg-raggraph is a library; this is the *service* a consumer runs around it. The
two things that keep it from OOM-ing on a large corpus:

  1. ONE long-lived GraphRAG for the whole process — models (embedder, extractor)
     load once, not per request. This is the biggest win for the small-corpus
     OOM case, which is dominated by fixed model overhead, not record count.
  2. ingest_records(..., batch_size=...) — records are pulled and processed in
     bounded batches, so peak memory is O(batch_size), not O(corpus). The
     `records` payload is streamed straight in; the service never slices it on
     the BFF side.

Run:
    pip install 'pg-raggraph[server]'
    uvicorn streaming_ingest_service:app --port 8080

    curl -s localhost:8080/v1/ingest -H 'content-type: application/json' -d '{
      "namespace": "kb",
      "records": [
        {"text": "Acme ships pg-raggraph.", "source_id": "doc:1"},
        {"text": "pg-raggraph is PostgreSQL-native.", "source_id": "doc:2"}
      ]
    }'

This file is documentation, not library code — it is intentionally minimal
(no auth, no error envelope). Wire those in for real deployments.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from pydantic import BaseModel

from pg_raggraph import GraphRAG

DSN = os.environ.get("PGRG_DSN", "postgresql://postgres:postgres@localhost:5434/pg_raggraph")

# Tune to the container's memory + CPU budget.
BATCH_SIZE = int(os.environ.get("PGRG_BATCH_SIZE", "32"))
MAX_CONCURRENT_DOCS = int(os.environ.get("PGRG_MAX_CONCURRENT_DOCS", "4"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    # One GraphRAG for the whole process: the embedder + extractor models load
    # exactly once here, not on every /v1/ingest call.
    app.state.rag = GraphRAG(dsn=DSN)
    await app.state.rag.connect()
    try:
        yield
    finally:
        await app.state.rag.close()


app = FastAPI(lifespan=lifespan)


class IngestRequest(BaseModel):
    namespace: str
    records: list[dict]
    # Keep extraction off the request hot path; the graph backfills via
    # `pgrg extract`. Flip to False if you want the graph synchronously.
    defer_extraction: bool = True


def _stream(records: list[dict]) -> Iterator[dict]:
    """Yield records one at a time.

    Even though the request already holds the list, streaming it (rather than
    re-slicing) lets pg-raggraph own the batching. Swap this for a DB cursor or
    an object-store reader to ingest corpora that never fit in one request.
    """
    yield from records


@app.post("/v1/ingest")
async def ingest(req: IngestRequest):
    rag: GraphRAG = app.state.rag
    # One bounded call. pg-raggraph pulls BATCH_SIZE records at a time; memory
    # stays O(BATCH_SIZE) regardless of len(req.records). No BFF-side slicing.
    await rag.ingest_records(
        _stream(req.records),
        namespace=req.namespace,
        batch_size=BATCH_SIZE,
        max_concurrent_docs=MAX_CONCURRENT_DOCS,
        defer_extraction=req.defer_extraction,
    )
    return {"ingested": len(req.records), "namespace": req.namespace}


# --- No-framework version: stream a huge directory in bounded memory ---------
async def ingest_directory(rag: GraphRAG, root: str, namespace: str) -> None:
    """Ingest every .md under `root` without holding them all in memory."""
    import pathlib

    def gen():
        for path in pathlib.Path(root).rglob("*.md"):
            yield {"text": path.read_text(encoding="utf-8"), "source_id": f"file:{path}"}

    await rag.ingest_records(gen(), namespace=namespace, batch_size=BATCH_SIZE)
