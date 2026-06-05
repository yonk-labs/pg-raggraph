# Streaming / batched ingest — ingest a big corpus in bounded memory

> **TL;DR.** `ingest_records()` pulls records in batches of `batch_size`
> (default 64), so peak memory is **O(batch_size)**, not O(corpus). Pass a
> `list`, a **generator**, a **DB cursor**, or an **`async` iterator** — a
> streamed source is never fully materialized. This is the primitive a
> wrapping service (FastAPI proxy, worker, CLI) uses to ingest large corpora
> without OOM.

## Why

pg-raggraph is a library, not a service. When you wrap it in your own ingest
service, you control the memory ceiling — but only if the library lets you feed
it incrementally. Previously `ingest_records()` materialized the entire input
list and scheduled one task per record across the whole corpus, so memory grew
with corpus size and large ingests got OOM-killed (issue #46).

Now the call processes the input in bounded batches: pull `batch_size` records →
chunk → embed → extract → write (one transaction **per document**) → free the
batch → pull the next. Entity resolution is DB-backed, so dedup is correct
across batch boundaries regardless of `batch_size`.

## The four input shapes

```python
from pg_raggraph import GraphRAG

async with GraphRAG(dsn=DSN) as rag:
    # 1. List (back-compat — validated eagerly, fails before any write on a bad row)
    await rag.ingest_records(records, namespace="kb")

    # 2. Generator — never materialized; memory stays O(batch_size)
    def gen():
        for path in huge_file_list:
            yield {"text": path.read_text(), "source_id": f"file:{path}"}
    await rag.ingest_records(gen(), namespace="kb", batch_size=32)

    # 3. DB cursor — stream rows straight from another database
    def from_crm():
        with psycopg.connect(crm_dsn) as conn, conn.cursor(name="srv") as cur:
            cur.itersize = 200
            cur.execute("SELECT note_id, note_text FROM sales_notes")
            for row in cur:                       # server-side cursor: bounded
                yield {"text": row[1], "source_id": f"sales_note:{row[0]}"}
    await rag.ingest_records(from_crm(), namespace="crm", batch_size=64)

    # 4. Async iterator — e.g. an async queue / paginated API
    async def apaginated():
        async for page in api.iter_pages():
            for item in page.items:
                yield {"text": item.body, "source_id": item.id}
    await rag.ingest_records(apaginated(), namespace="kb", batch_size=64)
```

### List vs stream — one behavior difference

| | `list` / `tuple` | generator / async iterator |
|---|---|---|
| Validation | **eager**, up front | **per batch**, as pulled |
| A bad row… | raises before **any** write | raises at its batch; **earlier batches are already committed** |
| Progress log | `Processing N records` | `Processing records (streaming…)` then `[idx/?]` |

If you need all-or-nothing semantics, pass a `list` (or wrap your own
transaction around the call). For unbounded sources, accept that a malformed
record fails forward from where it occurs.

## What batching does NOT fix

Batching makes ingest **O(batch_size)** — it does nothing about the **fixed,
per-process model overhead** that dominates a *small* ingest:

- the fastembed ONNX embedder (~150 MB),
- chunkshop's optional extractors (spaCy / KeyBERT / RAKE — 0.5–1 GB+ under
  Patterns C/D, see [chunkshop-integration.md](chunkshop-integration.md)),
- the in-process LLM extractor's transient buffers.

If five small files OOM your container, batching won't help — the models are the
floor. Two levers that do:

1. **Reuse one long-lived `GraphRAG`** across requests so models load **once**,
   not per call. This is the single biggest win for a service wrapper.
2. **`defer_extraction=True`** keeps the LLM extractor off the ingest hot path —
   chunks + embeddings land (so `naive` works immediately) and the graph
   backfills via `pgrg extract`. See
   [background-extraction.md](background-extraction.md).

## Sizing a service wrapper

Peak working set ≈ `min(batch_size, max_concurrent_docs)` × per-document cost +
the fixed model floor. So:

- Set **`max_concurrent_docs`** to your CPU/LLM concurrency budget.
- Set **`batch_size`** to bound how many records are *resident* — start at 32–64
  and lower it if memory is tight; raise it for throughput on roomy hosts.
- Pair with **`defer_extraction=True`** to keep each document's hot-path cost to
  chunk + embed.

```python
await rag.ingest_records(
    records,                 # list, generator, cursor, or async iterator
    namespace=kb_id,
    batch_size=32,           # memory ceiling
    max_concurrent_docs=4,   # CPU/LLM budget
    defer_extraction=True,   # graph backfills out-of-band
)
```

See the runnable FastAPI service in
[`samples/streaming_ingest_service.py`](samples/streaming_ingest_service.py):
one long-lived `GraphRAG`, a `POST /v1/ingest` that streams its `records`
straight into one bounded call — replacing BFF-side slicing.
