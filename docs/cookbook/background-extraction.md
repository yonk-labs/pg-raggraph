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

## Architectural patterns

Three patterns cover ~95% of deployments. Pick by how production-shaped
your workload is, not by what "feels right."

```
                    chunk + embed   extract entities/rels    pgrg ready
                    ─────────────   ─────────────────────    ──────────
  Pattern A (SYNC)  ████████████████████████████████████████ caller waits
  Pattern B (CRON)  ████                     ██████████████  drained later
  Pattern C (D)     ████                     ███████████     drained async
                    └──────────┘             └──────────┘
                    fast path                background path
```

### Pattern A — Synchronous extract (the original)

```python
await rag.ingest_records(records, namespace="crm")
# When this returns, every doc is 'ready' and the graph is built.
```

The default. `ingest()` returns when chunking + embedding + extraction +
graph writes are all done. Best for:

- **One-shot batch loads.** A nightly import where the operator wants the
  graph ready before any user query lands.
- **Small documents, fast extractor.** lede_spacy on 1-5 KB docs: the LLM
  isn't on the path; the whole pipeline is sub-second/doc.
- **Single-tenant tooling.** CLIs, dev scripts, demo flows where you
  don't want to manage a worker process.

Cost: caller waits ~1063 ms/doc on a 20-doc MHR batch with lede_spacy.
With an LLM extractor it grows proportionally.

### Pattern B — Deferred ingest + cron drain

```python
# Producer side — the path the caller actually executes
await rag.ingest_records(records, namespace="crm", defer_extraction=True)
# Returns in ~18 ms/doc. Doc is naive-queryable; graph is empty.

# Operator side — cron entry, e.g. */5 * * * *
$ pgrg --db $PGRG_DSN extract --namespace crm --once
```

The caller writes documents in roughly embedding-time only — 59× faster
than Pattern A for the same payload. A cron-triggered `pgrg extract`
drains the queue minutes (or whatever cadence you pick) later. Best for:

- **High-rate producers.** Webhooks, CDC streams, anything where you'd
  rather drop the request on the floor than block on the LLM endpoint.
- **Cost-managed extraction.** Schedule the drain in off-peak hours so
  the LLM bill lands during cheaper time-of-day pricing.
- **Operator-owned queue depth.** `graph_status_summary` (queryable via
  `rag.status()` or `result.metadata`) tells you how far behind the
  drain is.

### Pattern C — Deferred ingest + always-on daemon

```python
# Producer side — same as Pattern B
await rag.ingest_records(records, namespace="crm", defer_extraction=True)

# Operator side — systemd unit / k8s Deployment / docker run
$ pgrg --db $PGRG_DSN extract --namespace crm --daemon --poll-interval 1.0
```

A long-running worker drains the queue as it grows. SIGTERM/SIGINT
finish the current batch atomically then exit 0. Best for:

- **User-facing apps that want low time-to-full-graph.** Daemon polls
  every 1-2 s; a doc submitted at 12:00:00 becomes graph-complete by
  ~12:00:02 (plus extraction time).
- **Production services with monitoring.** Daemon emits
  `pgrg.backfill.claim`, `.extract`, and `.queue_depth` events on every
  iteration — wire these to your dashboards.
- **Multi-worker horizontal scaling.** Start multiple daemons against
  the same namespace; `SELECT … FOR UPDATE SKIP LOCKED` (claim) and the
  `(namespace, src_id, dst_id, rel_type)` unique constraint
  (relationships) make this safe by construction.

### Mixed pattern — per-record opt-in

```python
records = [
    # Small, high-priority docs extract synchronously.
    {"text": user_profile, "source_id": "user:42"},
    # Large, low-priority docs defer.
    {"text": full_audit_log,
     "source_id": "audit:42",
     "defer_extraction": True},
]
await rag.ingest_records(records, namespace="crm")
```

Per-record `defer_extraction` overrides the batch-level kwarg. Use when
some records are "must-have-graph-now" and others are "eventually."

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
database. Two invariants make this safe:

- `SELECT … FOR UPDATE SKIP LOCKED` on claim guarantees no two workers
  ever claim the same document.
- The `UNIQUE (namespace, src_id, dst_id, rel_type)` constraint on
  `relationships` (migration 013) plus `ON CONFLICT DO UPDATE
  SET weight = GREATEST(...)` in the INSERT make edge writes idempotent
  — even under the worst-case "two workers extract the same doc"
  scenario (e.g. crash → reaper → re-claim), no duplicate edges land.

Run as many workers as you want against a namespace. Use one worker per
host if you're bound by extraction CPU, more if you're bound by I/O.

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
- **Namespace-scoped reaper.** Every `pgrg extract` invocation runs
  `release_processing(namespace=<your --namespace>)` at startup,
  returning any rows stuck in `'processing'` (from a prior crash) to
  `'pending'`. Scoped: a worker starting in namespace A leaves
  namespace B's in-flight claims alone. Run `pgrg extract` without
  `--namespace` and you get a global reap with a warning log — fine for
  repair scripts, never what you want in production.
- **Edge-level idempotency.** Relationships have a UNIQUE constraint on
  `(namespace, src_id, dst_id, rel_type)` (migration 013). Both ingest
  paths use `ON CONFLICT DO UPDATE SET weight = GREATEST(...)`, so
  re-extracting the same edge merges into the existing row (keeping the
  strongest weight) instead of duplicating. Workers can step on each
  other under crash/retry conditions without corrupting the graph.
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

## End-to-end walkthrough — Pattern C, fully worked

A realistic scenario: a webhook receives CRM notes, hands them to a
producer that defers extraction, and a daemon backfills the graph.
The customer-facing query path returns immediately for everything that's
already chunked; entities + edges fill in seconds later.

### 1. One-time setup

```bash
# Required pg extensions (pgvector + pg_trgm) and the schema. `init` is
# idempotent — run as many times as you want.
pgrg --db postgresql://… init
```

```bash
# Start the drain daemon — usually a systemd unit / Kubernetes Deployment.
pgrg --db $PGRG_DSN extract \
    --namespace crm \
    --daemon \
    --batch-size 8 \
    --poll-interval 1.0 \
    --rate-limit-rps 10
```

Wire your metrics shipper (Vector, Promtail, Datadog Agent) to forward
`pgrg.metrics`-tagged log lines. The three events to graph:

| Event | What it means | Alert on |
|---|---|---|
| `pgrg.backfill.claim` | Every iteration; `claimed=0` when queue is empty | `claimed=0` for > N min while producers are writing → daemon is wedged or wrong namespace |
| `pgrg.backfill.extract` | One per non-empty iteration | `failed / claimed > 0.1` → extractor is degraded |
| `pgrg.backfill.queue_depth` | Per-status counts: `pending`, `processing`, `ready`, `failed` | `pending > N` for > M min → worker isn't keeping up; scale out |

### 2. Producer (webhook handler)

```python
from pg_raggraph import GraphRAG

rag = GraphRAG(dsn=PGRG_DSN, namespace="crm")
await rag.connect()

@app.post("/crm/notes")
async def receive_note(payload: dict):
    record = {
        "text": format_note(payload),
        "source_id": f"crm_note:{payload['id']}",
        "metadata": {"account_id": payload["account_id"]},
        # Defer at the per-record level so future records on this
        # endpoint can override individually if needed.
        "defer_extraction": True,
    }
    await rag.ingest_records([record], namespace="crm")
    return {"status": "queued", "source_id": record["source_id"]}
```

`receive_note` returns in ~15-20 ms regardless of how busy the extractor
is. The note is immediately retrievable via naive/BM25 search; the
graph fills in seconds later.

### 3. Consumer (search API)

```python
@app.get("/crm/search")
async def search(q: str):
    result = await rag.query(q, mode="smart", namespace="crm")
    response = {
        "chunks": [c.dict() for c in result.chunks],
        "confidence": result.confidence,
    }
    # Surface the queue lag so the UI can render a "graph still building"
    # notice without polling.
    gs = result.metadata.get("graph_status_summary", {})
    if gs.get("pending", 0) > 0:
        response["graph_status"] = "backfilling"
        response["pending_docs"] = gs["pending"]
    return response
```

### 4. Operator playbook

| Symptom | Check | Fix |
|---|---|---|
| `pending > 0` for > 5 min | `queue_depth` metric, daemon logs | Scale: start a 2nd daemon — multi-worker is safe |
| `failed > 0` rising | Inspect `documents.graph_error` | Fix the upstream, then `pgrg extract --include-failed --once` |
| `claimed=0` despite writes | Confirm `--namespace` matches producer's `namespace=` | Restart with the right `--namespace` |
| Daemon won't shut down cleanly | systemd `kill -TERM`; should exit ≤ batch latency | If hung > 30 s on SIGTERM, `kill -KILL`; next startup reaper recovers |

### 5. Mid-batch crash recovery

Suppose a daemon gets OOM-killed while extracting docs [101, 102, 103].
After the crash, those rows show `graph_status='processing'`:

```
SELECT id, graph_status, graph_extracted_at
FROM documents WHERE id IN (101, 102, 103);
-- 101 | processing | (null)
-- 102 | processing | (null)
-- 103 | processing | (null)
```

Restart the daemon (or run `pgrg extract --once`). The namespace-scoped
startup reaper flips them back to `'pending'`, the next claim picks
them up, and they extract normally. No data loss — the failed per-doc
transactions rolled back cleanly.

A peer daemon running in a *different* namespace at the moment of
restart is unaffected: PR-001 made the startup reaper namespace-scoped.

## When to use which surface

| Use case | Surface |
|---|---|
| Cron-driven backfill, one-shot | `pgrg extract --once` |
| Periodic catch-up, bounded work | `pgrg extract --max-iterations N` |
| Long-running service, always-on drain | `pgrg extract --daemon` |
| In-process worker inside a Python app | Call `claim_pending` + `extract_documents` directly |

All four share the same `extract_documents` primitive — single
implementation, multiple surfaces.

## Re-extracting a corpus with different settings

You changed `extraction_prompt`, `fact_extractor`, or `llm_model` and want
the graph rebuilt over already-ingested documents. Two traps to know about
before you flip anything back to `'pending'`:

**1. Old edges are never deleted.** Entity and relationship writes are
idempotent *upserts* — re-extraction merges into the existing graph, it does
not replace it. Edges produced by the old settings stay. For a clean
comparison (e.g. auditing what a new prompt extracts), either re-ingest into
a **fresh namespace**, or clear the old graph in place first:

```sql
-- In-place reset for one namespace (documents + chunks stay).
DELETE FROM relationships WHERE namespace = 'my_ns';
DELETE FROM entities      WHERE namespace = 'my_ns';  -- optional, see below
UPDATE documents SET graph_status = 'pending' WHERE namespace = 'my_ns';
```

Then run any drain surface from the table above. Keeping `entities` retains
their embeddings (cheaper), but old entity descriptions merged from the
previous run persist — delete them too when you want a truly fresh graph.

**2. The extraction cache keys on prompt + content, NOT on the model.**
`pgrg_llm_cache` is keyed `sha256(prompt_name + chunk_content)`. The
consequences are asymmetric:

- Changing `extraction_prompt` → every chunk misses the cache → real
  re-extraction. Nothing to do.
- Changing `llm_model` (or the LLM server) **alone** → every chunk *hits*
  the cache → the "re-extraction" silently replays the old model's cached
  output and the graph comes back identical. To actually exercise the new
  model, wipe the cache first:

```sql
DELETE FROM pgrg_llm_cache;  -- safe: it's a cache, repopulates on the next drain
```

The deterministic extractors (`lede_spacy`, `lede_prose`) don't use the
cache; switching `fact_extractor` between them re-extracts unconditionally.
The LLM leg of `llm+lede` caches like any other LLM extraction.

## Code KBs — backfilling the call graph

`pgrg extract` backfills **generic entities** (the GraphRAG prose graph) and owns
`documents.graph_status`. It does **not** rebuild the chunkshop **code graph**
(`CALLS`/`INHERITS`/`IMPLEMENTS`) — that is a corpus-level resolve, not a per-doc
one. For a code KB ingested with `chunk_strategy="chunkshop:symbol_aware"` and
`defer_extraction=True`, run a second, orthogonal pass:

```bash
# 1. fast deferred ingest: chunks + embeddings land, graph deferred.
#    Code docs also stage their raw file content in `code_backfill_stage`,
#    and the docs are graph_status='pending'.
# 2. generic entity backfill (owns graph_status: pending -> ready)
pgrg extract --namespace myrepo
# 3. code-graph backfill (rebuilds CALLS/INHERITS/IMPLEMENTS from staged content)
pgrg backfill-code-graph --namespace myrepo
```

`backfill-code-graph` is a **corpus finalize**: per namespace it re-parses the
staged file content, rebuilds the cross-file symbol index, and writes the
resolved edges, then deletes the staged rows. It is **crash-resumable** (rows are
deleted only after the resolve succeeds, so a re-run finishes an interrupted
pass) and idempotent. Because it keys off the `code_backfill_stage` queue and
never touches `graph_status`, it composes freely with `pgrg extract` in either
order.

Run **one worker per namespace** — cross-file resolution needs the whole
namespace's symbols in one pass, so it is a single-worker finalize rather than a
SKIP-LOCKED queue like `pgrg extract`. Let an in-flight `backfill-code-graph`
finish before re-ingesting that namespace's code docs: a doc re-ingested with
*changed* content lands as a new row that the next run picks up, but starting
overlapping backfills or re-ingests over the same namespace mid-run only
duplicates work. The staged content lives in a durable (LOGGED) table — unlike
the transient `code_calls_stage` spill table — so it survives between the
deferred ingest and the backfill run, then is cleaned up.

Programmatic equivalent:

```python
from pg_raggraph.backfill import backfill_code_graph

stats = await backfill_code_graph(rag, "myrepo")
print(stats.edges, "edges across", stats.docs, "docs")
```
