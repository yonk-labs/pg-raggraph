# Background extraction — make ingest a non-event

> **TL;DR.** Pass `defer_extraction=True` to `ingest_records()` and the
> document becomes `naive`-queryable in chunking + embedding time only.
> A background worker (`pgrg extract`, off-server or in-process daemon)
> drains the queue and backfills entities + relationships when it's ready.

## Why

LLM relationship extraction is the slow leg of ingestion. On a 40-doc /
~187-chunk MHR slice with `skip_llm=True`, embedding alone was 99% of the
wall time (~140 ms/chunk on local CPU bge-small). With LLM extraction
turned on it's much worse — and worse, it blocks `ingest()` from
returning.

For most queries — naive (vector + BM25) — the graph isn't even on the
path. Decoupling extraction means a caller writes a document and queries
it on the same connection, without waiting for the graph to land.

## The lifecycle

`documents.graph_status` (migration 012) tracks where each doc is:

```
pending     chunks + embeddings written; graph not yet extracted
processing  claimed by a worker (held under SELECT … FOR UPDATE SKIP LOCKED)
ready       entities + relationships written
failed      extraction raised; graph_error holds the reason
```

Existing rows backfill as `'ready'` (the column DEFAULT) — pre-feature
synchronous ingest is exactly what "ready" means.

## Surface 1 — opt-in deferred ingest

```python
await rag.ingest_records(
    records,
    namespace="crm",
    defer_extraction=True,   # batch default
)
```

Per-record override wins:

```python
records = [
    {"text": "small doc", "source_id": "x:1"},                       # batch default
    {"text": "huge doc",  "source_id": "x:2", "defer_extraction": True},
]
await rag.ingest_records(records, namespace="crm")   # default False
```

Chunks + embeddings still land synchronously, so `naive` retrieval works
immediately. Entity/relationship rows simply don't exist yet for the
deferred docs; `local`/`global`/`hybrid` modes return what's available
without raising.

## Surface 2 — `pgrg extract` (off-server CLI)

```bash
pgrg --db postgresql://… extract --namespace crm --batch-size 8 --once
```

Exits 0 when the queue is empty. Useful for cron-driven backfills or
one-shot drains.

Useful flags:

| Flag | Default | Meaning |
|---|---|---|
| `--namespace NS` | all | Drain only this namespace |
| `--batch-size N` | 4 | Docs claimed per iteration |
| `--max-iterations M` | 0 (unlimited) | Stop after M iterations (ignored with `--once`) |
| `--rate-limit-rps R` | 0 (unlimited) | Per-iter wall-time floor: `N / R` seconds |
| `--once` | off | Single iteration then exit |
| `--include-failed` | off | Flip `'failed'` rows back to `'pending'` at startup |

Multiple `pgrg extract` workers can run in parallel against the same
database: `SKIP LOCKED` guarantees no two workers ever claim the same
document.

## Surface 3 — `pgrg extract --daemon` (long-running)

```bash
pgrg --db postgresql://… extract --daemon --namespace crm --poll-interval 1.0
```

Same loop as the off-server CLI, but:

- Polls forever (sleeps `--poll-interval` between empty queue checks).
- Installs SIGTERM/SIGINT handlers that set an `asyncio.Event`. The
  current batch finishes atomically; then the worker exits 0.
- `--daemon` and `--once` are mutually exclusive — the CLI refuses both.

This is the right shape for a long-running service that wants ingestion
to be a true non-event: producers append documents, the daemon drains.

## Idempotency & crash recovery

- **Per-doc transaction.** Extraction → resolution → graph writes →
  `graph_status='ready'` all commit together. A failure rolls everything
  back; a separate small UPDATE marks the doc `'failed'` with `graph_error`.
- **Reaper.** Every `pgrg extract` invocation runs `release_processing`
  at startup, returning any rows stuck in `'processing'` (from a prior
  crash) to `'pending'`. Cheap UPDATE; safe across workers.
- **Retry failed.** Pass `--include-failed` to flip `'failed'` rows back
  to `'pending'` so they're re-attempted. Re-running on a `'ready'` doc
  is a no-op because the claim filter is `'pending'`-only.

## Query-time hint

`QueryResult.metadata['graph_status_summary']` gives the per-status doc
count for the queried namespace, e.g.:

```python
result = await rag.query("…", mode="local", namespace="crm")
gs = result.metadata["graph_status_summary"]
# {'pending': 12, 'processing': 0, 'ready': 488, 'failed': 0}
```

Callers that need a fully-populated graph can poll: if `gs['pending'] > 0`,
the daemon hasn't drained yet. Retrieval still succeeds — naive returns
whatever chunks exist; local/global/hybrid return whatever entities are
already written.

`GraphRAG.status(namespace)` returns the same shape under a top-level
`graph_status` key.

## Quick sanity check

```python
from pg_raggraph import GraphRAG
from pg_raggraph.backfill import claim_pending, extract_documents

rag = GraphRAG(dsn="…", namespace="crm")
await rag.connect()
await rag.ingest_records(
    [{"text": "hello world", "source_id": "demo:1"}],
    defer_extraction=True,
)
ids = await claim_pending(rag.db, "crm", batch_size=8)
stats = await extract_documents(rag, ids)
print(stats)   # ExtractStats(claimed=1, ready=1, failed=0, entities=…, relationships=…)
```

## Measured impact

Benchmark: `benchmarks/defer_extraction_bench.py` against the MHR slice,
extractor = `lede_spacy` (deterministic, no LLM — keeps the LLM provider
out of the variance).

Three arms on the same hardware, same corpus, same warm embedding cache:

| Arm | What it measures | Wall time (20 docs) | Wall time (40 docs) |
|---|---|---:|---:|
| **A — SYNC** ingest, `defer_extraction=False` | chunk + embed + extract + graph-write, one tx per doc, doc_concurrency=4 | 21.27 s | 26.27 s |
| **B — DEFER** ingest, `defer_extraction=True` | chunk + embed + mark pending | **0.36 s** | **0.44 s** |
| **C — DRAIN** via `claim_pending` + `extract_documents` | pgrg-extract equivalent — graph extraction + writes only | 7.24 s | 15.12 s |

Derived headlines:

| Metric | 20 docs | 40 docs |
|---|---:|---:|
| Time-to-queryable (B) | 0.36 s (**18 ms/doc**) | 0.44 s (**11 ms/doc**) |
| Caller speedup (A / B) | **59.0×** | **59.8×** |
| Async win (A − B) | +20.91 s | +25.83 s |
| Total async path (B + C) | 7.60 s | 15.56 s |
| Total-overhead delta ((B+C) − A) | **−13.67 s** | **−10.71 s** |
| Graph parity (entities A / B+C) | 902 / 901 | 1484 / 1482 |
| Graph parity (relationships A / B+C) | 2143 / 2143 | 4415 / 4415 |

Three things stand out:

1. **The caller wait drops to "nothing."** 18 ms/doc (20-doc run) is below
   the latency of most upstream HTTP calls. From the caller's seat,
   `ingest()` is no longer the slow leg.
2. **The async path is actually faster end-to-end.** B + C is 64% of A.
   The synchronous path holds a per-document transaction open across the
   extraction call, which serializes more than it should at
   `doc_concurrency=4`; the deferred path writes chunks immediately and
   runs extraction outside any held transaction.
3. **Graph parity is exact on edges, ~0.1% on nodes.** The small entity
   delta is dedup-order interaction (different per-doc execution order →
   slightly different first-seen entity rows merging). No relationships
   were lost; no facts were lost.

Repro:

```bash
uv run python -m benchmarks.defer_extraction_bench --docs 20
uv run python -m benchmarks.defer_extraction_bench --docs 40
```

### Caveats

- Numbers reflect lede_spacy. With LLM extraction (Ollama / OpenAI), Arm A
  gets much slower — the async win is correspondingly larger. Arm C grows
  the same amount, but the *caller* speedup grows because A grew.
- Embedding cache is pre-warmed in the harness; cold-cache adds ~140 ms/chunk
  to both A and B (see `ingest_perf_results-2026-05-27.md`).

## When to use which surface

| Use case | Surface |
|---|---|
| Cron-driven backfill, one-shot | `pgrg extract --once` |
| Periodic catch-up, bounded work | `pgrg extract --max-iterations N` |
| Long-running service, always-on drain | `pgrg extract --daemon` |
| In-process worker inside a Python app | Call `claim_pending` + `extract_documents` directly |

All four share the same `extract_documents` primitive — single
implementation, multiple surfaces.
