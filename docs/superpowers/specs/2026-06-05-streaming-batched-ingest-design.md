# Streaming / Batched `ingest_records` — Design & Plan (2026-06-05)

Issue: [#46 — `ingest_records` loads entire input list into memory](https://github.com/yonk-labs/pg-raggraph/issues/46)
Reported by: downstream consumer (EnterpriseDB `dx-poc`, `pg-raggraph-proxy`) wrapping pg-raggraph in a FastAPI service.

## TL;DR

pg-raggraph is a **library**, not a service. The fix is to let the library ingest a corpus in **bounded memory** so a consumer can run their own ingest service without OOM. The mechanism: make `ingest_records()` accept an iterator / async-iterator and process it in **bounded batches**, instead of eagerly scheduling one coroutine per record over the whole corpus.

**The issue's stated root cause is partly wrong** (verified against the code, 2026-06-05) — correcting it changes the plan and shrinks it:

| Issue's claim | Reality in `src/pg_raggraph/__init__.py` |
|---|---|
| "Single bulk write to all tables at the **end**; peak memory just before the final write" | **False.** `_ingest_one_content` writes each document in its **own per-doc transaction** (`__init__.py:886`). Chunks / embeddings / entity dicts are freed per document, not accumulated until a final write. |
| "Entity-resolution dedup state must live across batches" | **Non-issue.** Resolution is **DB-backed** — `resolve_entity` does `SELECT id FROM entities WHERE namespace=%s AND name=%s` (`resolution.py:75`). Dedup state already lives in PostgreSQL (single-DB thesis). Batching cannot break it. |

So the genuine, narrow defect is the scheduling shape, not the write shape.

## Root cause (verified)

`ingest_records` (`__init__.py:619`) does two things that scale memory with corpus size `N`:

1. **`__init__.py:940` — eager fan-out over the whole corpus:**
   ```python
   await asyncio.gather(*[_process_record(i + 1, rec) for i, rec in enumerate(records)])
   ```
   The `doc_sem` semaphore throttles how many records **execute** at once (`doc_concurrency`), but `gather` still constructs **N coroutine objects + N `Task` objects up front**, each capturing its `rec`, and holds all of them (plus results/exceptions) alive until the **last** one finishes. Steady-state working set is bounded by the semaphore; the *task graph and its retained results* are O(N).

2. **`__init__.py:788` — `records` must be a fully-materialized sized list:**
   ```python
   _progress(f"Processing {len(records)} records (in-memory ingest).")
   ```
   `len(records)` forbids a generator / DB cursor / async stream as input. The caller must hold the entire corpus in Python before the call begins.

### What batching will NOT fix (be honest)

The issue reports **5 markdown files / ~50 KB → SIGKILL at a 1.5 GB ceiling**. That is **not** the O(N) records problem — 5 records cannot fill 1.5 GB via the task graph. That case is **fixed per-process model overhead**, co-resident in one interpreter:

- fastembed ONNX embedder (~150 MB),
- chunkshop's optional extractors under Pattern C/D (spaCy / KeyBERT / RAKE can add 0.5–1 GB+),
- the LLM extractor's transient buffers,
- the FastAPI proxy itself.

Batching makes ingest **O(batch_size)** instead of **O(N)** — it does nothing for the fixed model floor. The plan must say this plainly to the downstream consumer, and pair the API fix with **operational guidance** (reuse one long-lived `GraphRAG`; prefer `defer_extraction=True` to keep the LLM extractor off the ingest hot path; size `batch_size` × `max_concurrent_docs` to the container's memory ceiling).

## Mission Brief

### Purpose
Let a library consumer ingest an arbitrarily large corpus in bounded memory, so they can run their own ingest service (a FastAPI proxy, a worker, a CLI) without OOM and without BFF-side slicing hacks.

### Desired Outcome
`ingest_records()` accepts an `Iterable[dict]` **or** `AsyncIterable[dict]` and processes it in batches of `batch_size`. Peak Python heap attributable to the call is O(batch_size), independent of corpus size. The existing `list[dict]` call site keeps working unchanged.

### Success Criteria
- **SC-1** Passing a generator / async-iterator (never a full list) ingests correctly; the full corpus is never materialized by pg-raggraph.
- **SC-2** Peak task-graph size is O(batch_size), not O(N) — asserted by a test that ingests N≫batch_size and checks live `Task` count / tracemalloc stays bounded.
- **SC-3** Back-compat: every existing `ingest_records(list, ...)` call and kwarg behaves identically; entity/relationship counts and dedup are byte-for-byte unchanged on a fixture corpus.
- **SC-4** Dedup correctness across batch boundaries: the same entity in batch 1 and batch 3 collapses to one row (already guaranteed by DB-backed resolution; covered by a regression test).
- **SC-5** Docs: a cookbook page + sample showing the streaming pathway for a service wrapper, including the model-overhead guidance and `defer_extraction` pairing.

### Constraints (ALWAYS / ASK FIRST / NEVER)
- **ALWAYS** keep the per-document transaction boundary (no batch-wide mega-transaction — that would *reintroduce* an O(batch) write and risk one bad doc rolling back a batch).
- **ALWAYS** preserve the public signature and all current kwargs; `batch_size` is additive with a default that reproduces today's behavior for small inputs.
- **ASK FIRST** before changing `doc_concurrency` profile defaults or the metrics/`_progress` contract shape (downstream parses the "Processing N records" log line per the issue).
- **NEVER** hold the whole corpus in memory once the streaming path exists; **NEVER** break the `list[dict]` call site.

### Testing Requirements
- Unit: generator input, async-iterator input, empty input, `batch_size=1`, `batch_size > N`, list back-compat.
- Integration (DB): cross-batch dedup; equivalence of entity/rel counts between one-shot list and streamed batches on the same corpus.
- Perf/bounded-memory: the issue's `tracemalloc` test shape (N=2000, batch_size=50), asserting bounded peak. Mark it `integration` (needs DB) and keep the threshold loose — it's a guardrail, not a microbenchmark.

### Out of Scope
- Reducing the fixed model-loading floor (separate concern; document, don't fix here).
- Streaming a single oversized document's chunks (this is about many docs, not one giant doc — the hard token-split fallback already bounds per-doc chunking).
- Changing the extraction or embedding internals.

## Architecture

### The batched driver
Replace the single eager `gather` with a pull-loop that fans out at most `batch_size` coroutines, awaits the batch, frees it, then pulls the next:

```python
async def ingest_records(self, records, namespace=None, on_progress=None, *,
                         batch_size: int = 64, max_concurrent_docs=None,
                         defer_extraction: bool = False, **living_kwargs):
    ...
    processed = 0
    async for batch in _abatched(records, batch_size):     # see helper below
        with self.db.tenant(ns):
            await asyncio.gather(*[
                _process_record(processed + j + 1, rec) for j, rec in enumerate(batch)
            ])
        processed += len(batch)
        _progress(f"Processed {processed} records so far (batch of {len(batch)}).")
        # batch + its coroutines/results are now unreferenced → freed before next pull
```

- `doc_sem` still bounds concurrency **within** a batch; the new ceiling is `min(batch_size, doc_concurrency)` coroutines alive at once.
- `with self.db.tenant(ns)` stays per-batch (or hoist around the loop — it's a context var, cheap either way).

### Iterator normalization helper
One small helper accepts sync-iterables, async-iterables, and (for back-compat) lists, yielding `list[dict]` batches without ever materializing the whole input:

```python
async def _abatched(records, n):
    if hasattr(records, "__aiter__"):
        batch = []
        async for r in records:
            batch.append(r)
            if len(batch) >= n:
                yield batch; batch = []
        if batch: yield batch
    else:                                   # sync iterable (incl. list)
        it = iter(records)
        while (batch := list(islice(it, n))):
            yield batch
```

A `list` flows through the sync branch via `iter()` — no behavior change, no full re-materialization beyond what the caller already passed.

### Progress / metrics contract
`len(records)` is no longer available for a streamed source. Options (ASK FIRST — downstream parses this log):
- Keep the eager "Processing {len} records" line **only** when `records` is `Sized` (a list); for streamed sources emit running "Processed K so far".
- `documents=` in `_emit_metric` becomes the running `processed` count (accurate, just not known up front).

This preserves the exact current line for the list path the proxy uses today, and degrades gracefully for streams.

## Execution Plan — Thin Vertical Slices

Each slice leaves the tree green and is independently shippable.

- **Slice 1 — `batch_size` over lists (no API surface change for callers).**
  Add `_abatched`, route the existing list path through the batched driver with a default `batch_size` (e.g. 64). For a list, externally identical; internally the task graph is now O(batch_size). Tests: back-compat equivalence (counts/dedup), `batch_size=1`, `batch_size>N`. **This alone fixes the O(N) task-graph driver for the proxy's current list calls.**

- **Slice 2 — accept sync generators / iterables.**
  Drop the hard `len(records)`; gate the "Processing N" log on `isinstance(records, Sized)`. Test: generator input never materialized (assert via a generator that records how many items were pulled at peak).

- **Slice 3 — accept async-iterators.**
  `_abatched`'s `__aiter__` branch. Test: `async def` record source (e.g. an async DB cursor stub) ingests correctly.

- **Slice 4 — docs + sample.**
  `docs/cookbook/streaming-ingest.md` + a runnable sample under `docs/cookbook/samples/`: a FastAPI `POST /v1/ingest` that streams its `records` straight into `ingest_records(..., batch_size=…, defer_extraction=True)` — replacing the dx-poc BFF-side slicing workaround with one bounded call. Include the model-overhead guidance and the `defer_extraction` → `pgrg extract` pairing (cross-link `docs/cookbook/background-extraction.md`).

## Downstream pathway (what unblocks EDB `dx-poc` immediately)

Even before Slice 3 lands, the proxy can stop slicing on the BFF side and instead:
1. Reuse **one** long-lived `GraphRAG` instance across requests (models load once, not per call) — the single biggest win for the 5-file/1.5 GB case.
2. Call `ingest_records(records, batch_size=32, defer_extraction=True)` — bounded task graph **and** the LLM extractor stays off the request hot path; the graph backfills via `pgrg extract`.
3. Size `batch_size × max_concurrent_docs` to the container memory ceiling.

This is the "proven pathway / sample" the issue asks for: the library exposes the bounded-memory primitive; the consumer runs the service.

## Open questions for review
1. Default `batch_size` — 64? Tie it to the ingestion profile (`conservative`/`balanced`/`aggressive`/`max`) so it tracks `doc_concurrency`?
2. Keep `with self.db.tenant(ns)` per-batch or hoist around the whole loop?
3. Is preserving the literal "Processing {N} records" log line for the list path worth the `Sized` branch, or is a clean "Processed K so far" acceptable to downstream (they parse it — ASK)?
