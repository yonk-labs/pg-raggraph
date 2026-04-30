# Proposal: pg-raggraph as database primitives

> **Status:** Forward-looking draft (2026-04-30). Captured from a user question: *"is there a way to do these as database functions/primitives? maybe a longer term ask."* Not committed for execution.
>
> **Hard constraints from the user, 2026-04-30:**
> - **No `pgai` integration.** pg-raggraph stands alone — same independence stance as our position on Apache AGE. Adding a dependency on Timescale's pgai contradicts the "use the Postgres you already have" thesis and limits deployment portability (pgai isn't on AWS RDS / GCP Cloud SQL / most managed providers).
> - **No new mandatory extensions beyond what we already require** (`pgvector`, `pg_trgm`).
> - **`pg_net` / `http` are acceptable optional dependencies** since they're widely supported and let us call out to sidecars without baking models into Postgres itself.

## TL;DR

Yes — buildable in stages, fully independent of pgai. The recommended shape:

1. **In pure SQL today:** chunking, entity resolution, graph traversal, graph storage. ~70% of the value, no new extension.
2. **Mid-term:** add a thin **pg-raggraph-native sidecar service** (a small HTTP server exposing `embed(text)` and `extract(chunk_text)`), called from SQL via `pg_net`. The sidecar is the same Python code we ship today, just bound to a port. Postgres functions compose its primitives with our SQL chunking + resolution + storage.
3. **Long-term:** native `pg_raggraph` extension via pgrx that bundles model loading inside Postgres. Optional, only if cloud-extension availability ever catches up.

End-state interface stays the same in any path:

```sql
SELECT pgrg.ingest_record(
    text       => sn.note_text || E'\n# Customer\n' || c.company_name,
    source_id  => 'sales_note:' || sn.note_id,
    namespace  => 'sales_calls',
    metadata   => jsonb_build_object('order_id', sn.order_id, 'status', so.status)
)
FROM sales_demo_app.sales_notes sn
JOIN sales_demo_app.sales_orders so ON so.order_id = sn.order_id
JOIN sales_demo_app.customers c ON c.customer_id = so.customer_id
WHERE so.status = 'won';
```

The user calls one SQL primitive. Whether that primitive ultimately routes to a sidecar HTTP endpoint or a native extension is an implementation detail under our control — *not* a dependency on someone else's stack.

## What's pure SQL today (no new dep at all)

These already work as plain stored procedures wrapping current logic:

- **Chunking** — text manipulation. `pgrg.chunk(text, strategy)` returns `setof (sequence int, content text, embedded_content text)`. Markdown-aware, code-aware, sentence-aware splitters all expressible via `regexp_split_to_table` + post-processing.
- **Entity resolution** — already SQL via `pg_trgm` + `pgvector`. Today's `resolution.py` is essentially three SQL statements; `pgrg.resolve_entity(name text, embedding vector(384))` is a 50-line wrapper that returns the resolved entity_id.
- **Graph storage** — flat INSERTs into `entities`, `relationships`, `entity_chunks`, `relationship_chunks`. Trivially callable from SQL.
- **Graph traversal** — recursive CTEs already power `local`/`global`/`hybrid` modes. `pgrg.search(question text, mode text)` returns `setof retrieval_result`.

**This subset alone covers ~70% of the value.** Anyone who has embeddings + extraction available some other way — already-computed via an ETL job, or coming from a pre-extracted JSON cache — can do everything else from SQL today.

## What needs a runtime

Two pieces that aren't SQL:

- **Embeddings** — needs a transformer model. Postgres has no native way to run one without an extension that bundles a runtime.
- **LLM extraction** — needs an HTTP call to an OpenAI-compatible endpoint.

Three implementation paths, ranked by alignment with the "stand alone" mandate:

### Path A — pgrg-native sidecar over `pg_net` (recommended near-term)

Ship a small HTTP service alongside pg-raggraph (or have users run it themselves). The sidecar exposes:

```
POST /embed       body: {"text": "..."}                       → 384-dim vector
POST /extract     body: {"chunks": [...], "namespace": "..."} → entities + relationships
```

Implementation is **literally the existing Python code** in `extraction.py` + `embedding.py`, wrapped in a FastAPI app. We already ship this for use as a library; binding it to a port is ~80 lines.

From SQL, call it via `pg_net`:

```sql
CREATE OR REPLACE FUNCTION pgrg.embed(text)
RETURNS vector(384)
LANGUAGE sql
AS $$
    SELECT (response.body::jsonb->'embedding')::text::vector(384)
    FROM net.http_post(
        url     => current_setting('pgrg.sidecar_url') || '/embed',
        body    => jsonb_build_object('text', $1),
        timeout_milliseconds => 5000
    ) AS response
$$;
```

Then `pgrg.ingest_record()` becomes a pure-SQL function that composes `pgrg.chunk` → `pgrg.embed` → `pgrg.extract` → `pgrg.resolve_entity` → graph-storage INSERTs, all in one transaction.

**Tradeoffs:**
- **Pro: stands alone.** No pgai, no Apache AGE, no Timescale-specific extension. Just pgrg + pgvector + pg_trgm + pg_net.
- **Pro: cloud-portable.** `pg_net` is in Supabase by default, available on Neon, and trivially installable elsewhere. AWS RDS supports it via `rds.allowed_extensions`.
- **Pro: same code, two surfaces.** The sidecar IS the Python library, just running as a service. Bug fix in one = bug fix in both.
- **Pro: failure isolation.** A slow LLM call doesn't block PG backends — `pg_net` is async; calls go through a background worker.
- **Con: need to deploy + run the sidecar.** Adds an operational concern. Mitigated by shipping a `docker compose` snippet and a single binary for self-hosted users.
- **Con: latency floor includes localhost HTTP roundtrip (~1-3 ms each call).** Marginal at our scale.
- **Con: pg_net itself isn't yet in core Postgres** — but it's installable nearly everywhere we care about and the bar to add it is much lower than installing extension-of-the-month.

This is the recommended near-term path. It honors the "stand alone" mandate, ships in months not years, and gives a real `SELECT pgrg.ingest_record(...)` SQL surface.

### Path B — Native `pg_raggraph` extension via pgrx (long-term aspiration)

Rust extension via [pgrx](https://github.com/pgcentralfoundation/pgrx) — bundle the embedding runtime + HTTP client natively, no sidecar.

```rust
#[pg_extern]
fn pgrg_ingest_record(
    text: &str,
    source_id: &str,
    namespace: &str,
    metadata: pgrx::JsonB,
) -> Result<(), Error> {
    // chunk in pure Rust
    // embed via candle-rs (Rust-native ONNX)
    // extract via reqwest to configured LLM endpoint
    // resolve, write — all native, one transaction
}
```

**Tradeoffs:**
- **Pro: best performance + native types + proper transaction semantics, no sidecar to operate.**
- **Pro: fully aligned with the "use Postgres" thesis.** `CREATE EXTENSION pg_raggraph` and the user has everything.
- **Con: significant engineering** — multi-month effort with proper test coverage and packaging.
- **Con: cloud-extension availability is the same blocker that killed Apache AGE for us.** AWS RDS, GCP Cloud SQL, Supabase, Neon all need to whitelist new extensions individually. Without that adoption story, the extension is only useful for self-hosted users who could run a sidecar anyway.
- **Con: model loading inside PG backend processes** — significant memory + restart cost per backend.

Don't start here. This is the right long-term aspiration only if (a) cloud providers solve their extension story, or (b) we decide pg-raggraph's audience is exclusively self-hosted.

### Path C — PL/Python sidecars-in-process

Same code as Path A but running inside the Postgres backend via `plpython3u` instead of as an external service.

**Tradeoffs:**
- **Pro: no separate process to run.**
- **Con: PL/Python isn't on most managed providers** (AWS RDS supports it, but Cloud SQL doesn't, Supabase doesn't, Neon doesn't). Worse availability than `pg_net`.
- **Con: model loaded per Postgres backend** — every connection that touches `pgrg.embed` instantiates the embedding model. Memory cost ~50-200 MB × backends.
- **Con: synchronous LLM calls block backend processes.** One slow call = one stuck connection.

Strict downgrade from Path A on every dimension that matters.

Listed for completeness; not recommended.

## Recommended sequencing

1. **Now:** the `ingest_records()` Python API closes the disk-roundtrip gap for SQL-source pipelines via a small Python orchestrator (50 lines). Cookbook covers this in Pattern B.
2. **Mid-term (3-6 months) — Path A:** ship the pgrg sidecar service + SQL functions (`pgrg.chunk`, `pgrg.embed`, `pgrg.extract`, `pgrg.resolve_entity`, `pgrg.ingest_record`, `pgrg.search`). Binary distribution + docker-compose snippet. Document `pg_net` install for self-hosted users.
3. **Long-term (12+ months) — Path B:** evaluate the native pgrx extension if cloud-extension availability improves. Right now it's a strict liability for cloud users.

## What should we ship next?

Honest read: the in-memory `ingest_records()` API closes the immediate "no disk roundtrip" gap. Path A is the next real workstream IF user demand for SQL-callable ingest emerges from real users (not just architectural neatness). Most ETL/CDC jobs already run from Python; the script is 50 lines.

Don't pre-build Path A. Capture the design here, ship the Python API, wait for actual demand.

## Open questions

- **Sidecar packaging.** Single Docker image? Standalone binary via `pyinstaller`? Both? Decided when we actually start Path A.
- **`pg_net` availability gating.** Which managed providers offer `pg_net` today? Supabase yes; Neon yes; RDS via allowlist; Cloud SQL no. Should pgrg fall back to a Python-orchestrated path if `pg_net` isn't installed? Probably yes — same model as the Python API today.
- **Async/queueing.** Sync `pgrg.ingest_record()` calls from triggers will block when the LLM is slow. The PG-side answer is `pg_cron` + a queue table; the function writes the queue row, a background worker drains it. Real engineering, deferred until Path A is committed.
- **GPU access.** Sidecar can use GPU; native extension faces the usual "GPU inside Postgres backend" problem. Default both paths to CPU embeddings; GPU is an opt-in deployment choice.

## What this proposal is NOT

- Not a commitment to build any of this. The user explicitly said "longer term ask."
- **Not pgai integration.** Hard ruled out by the user. pg-raggraph remains independent of Timescale's stack the same way it's independent of Apache AGE.
- Not a replacement for the Python `pg_raggraph` library. The Python API stays the primary surface for batch ingest, complex orchestration, async workflows, and any deployment that doesn't want to run a sidecar.
