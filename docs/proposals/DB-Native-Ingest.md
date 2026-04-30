# Proposal: pg-raggraph as database primitives

> **Status:** Forward-looking draft (2026-04-30). Captured from a user question: *"is there a way to do these as database functions/primitives? maybe a longer term ask."* Not committed for execution. The goal here is to sketch what the SQL-callable shape could look like and what's actually doable today vs needs heavier engineering.

## TL;DR

Yes — but in stages, and the right pragmatic path is **build on top of `pgai`** (Timescale's Postgres extension for AI workloads) rather than reimplement embedding/LLM clients in PL/Python. Three layers:

1. **Today, in pure SQL:** chunking + entity resolution + graph traversal — already SQL.
2. **Near-term, via `pgai`-or-similar integration:** embeddings + LLM extraction become `SELECT pgrg.embed(text)` and `SELECT pgrg.extract(chunk_text)` callable from any query.
3. **Longer-term, as a pgrx extension:** native `pg_raggraph` extension exposing `pgrg.ingest_record(text, source_id, namespace, metadata)` as a single SQL function. Set-returning functions for query (`pgrg.search(question, mode)`).

Final shape that "looks right":

```sql
-- One-call ingest from anywhere a query can run
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

-- Query with the same primitive
SELECT * FROM pgrg.search(
    question  => 'What were the most common reasons we won deals?',
    mode      => 'smart',
    namespace => 'sales_calls'
);
```

Same primitive composes with triggers, materialized views, scheduled jobs, CDC pipelines.

## What's pure SQL today

These already work — no new extension needed, just stored procedures wrapping current logic:

- **Chunking** — text manipulation. `pgrg.chunk(text, strategy)` returns `setof (sequence int, content text)`. Markdown-aware, code-aware, sentence-aware splitters all expressible in pure SQL with `regexp_split_to_table` + post-processing.
- **Entity resolution** — already SQL via pg_trgm + pgvector. Today's `resolution.py` is essentially three SQL statements; the Python layer just orchestrates. A `pgrg.resolve_entity(name, embedding)` function returning the resolved entity_id is a 50-line wrapper.
- **Graph storage** — flat INSERTs into `entities`, `relationships`, `entity_chunks`, `relationship_chunks`. Trivially callable from SQL.
- **Graph traversal** — recursive CTEs already power `local`/`global`/`hybrid` modes. `pgrg.search()` returns `setof retrieval_result` — straightforward.

**This subset alone covers ~70% of the value.** A user with embeddings already-computed (e.g. inserted via pgai or a separate ETL job) could do everything from SQL today.

## What's not pure SQL today

The two remaining pieces:

- **Embeddings** — needs to run a transformer model (bge-small via fastembed/onnx). Postgres has no native way to do this.
- **LLM extraction** — needs an HTTP call to an OpenAI-compatible endpoint.

Three implementation paths, ranked by pragmatism:

### Path 1 — `pgai` integration (recommended)

[Timescale's `pgai` extension](https://github.com/timescale/pgai) already provides:

- `ai.embed(text, model => 'BAAI/bge-small-en-v1.5')` — runs locally via the extension's bundled embedding runtime
- `ai.openai_chat_complete(messages, model => 'gpt-4o-mini', api_key => ...)` — direct LLM call from SQL

Both are already mature, both are pure-Postgres, both compose with triggers/materialized views.

What we'd add to pg-raggraph:

```sql
-- Wrapper that uses pgai under the hood
CREATE OR REPLACE FUNCTION pgrg.embed(text)
RETURNS vector(384)
LANGUAGE sql
AS $$ SELECT ai.embed(text, model => current_setting('pgrg.embedding_model', true)) $$;

CREATE OR REPLACE FUNCTION pgrg.extract(chunk_text text)
RETURNS table(entities jsonb, relationships jsonb)
LANGUAGE sql
AS $$
    SELECT entities, relationships
    FROM ai.openai_chat_complete(
        messages => jsonb_build_array(
            jsonb_build_object('role','system','content', current_setting('pgrg.extraction_prompt')),
            jsonb_build_object('role','user','content', chunk_text)
        ),
        response_format => 'json_object'
    ) AS r,
    jsonb_to_record(r.content::jsonb) AS x(entities jsonb, relationships jsonb)
$$;
```

`pgrg.ingest_record()` then composes these primitives in a single transaction. Roughly 200-400 lines of SQL/PL-pgSQL, no new extension code.

**Tradeoffs:**
- Pro: cheapest path to working DB-native ingest.
- Pro: pgai handles model loading, caching, batching — we don't reinvent that.
- Pro: composes with anything pgai already supports (other embedders, providers).
- Con: depends on pgai. Adds an extension to the install matrix.
- Con: pgai availability varies — Timescale-managed Postgres has it; AWS RDS / GCP Cloud SQL / Supabase don't yet (but trending toward yes).
- Con: cloud-portability story softens — "use any Postgres" becomes "any Postgres with pgai."

### Path 2 — PL/Python sidecars (no pgai)

If pgai isn't available, fallback is PL/Python with `httpx` for LLM calls and `onnxruntime` (or a pure-Python fastembed wrapper) for embeddings.

```sql
CREATE EXTENSION plpython3u;

CREATE OR REPLACE FUNCTION pgrg.embed(text) RETURNS vector(384)
LANGUAGE plpython3u AS $$
    import onnxruntime as ort  # loaded once per backend
    # ... embed and return
$$;
```

**Tradeoffs:**
- Pro: works on any Postgres that allows PL/Python (most cloud providers don't, in fairness).
- Pro: no extension install beyond plpython3u.
- Con: model loaded per Postgres backend → memory cost ~50-200 MB × backends. Heavyweight.
- Con: LLM HTTP calls block PG backend processes. One slow call = one stuck connection. Throttle carefully.
- Con: PL/Python is hard to debug, hard to deploy, hard to upgrade.

I would not recommend this for production unless pgai isn't available AND you've measured the memory cost.

### Path 3 — Native `pg_raggraph` extension via pgrx

A Rust extension via [pgrx](https://github.com/pgcentralfoundation/pgrx) — native types, native function dispatch, native memory management.

```rust
#[pg_extern]
fn pgrg_ingest_record(
    text: &str,
    source_id: &str,
    namespace: &str,
    metadata: pgrx::JsonB,
) -> Result<(), Error> {
    // chunk, embed (via candle or onnxruntime-rs), call LLM (via reqwest),
    // resolve, write — all native Rust, no extension hops.
}
```

**Tradeoffs:**
- Pro: best performance. Native types, proper transaction handling, no Python interpreter overhead.
- Pro: same install model as pgvector/pg_trgm — drop-in `CREATE EXTENSION pg_raggraph`.
- Pro: aligns with the existing thesis — "use Postgres for everything." `pg_raggraph` becomes a real Postgres extension, not a Python framework.
- Con: significant engineering — multi-month effort for a maintainable extension.
- Con: model loading + GPU access in Rust is harder than in Python (smaller ecosystem).
- Con: cloud-availability is the same problem as pgai but worse — extensions need provider whitelisting (no AWS RDS without explicit support, etc.).

This is the long-term aspirational shape. Don't start here.

## Recommended sequencing

1. **Now:** the `ingest_records()` Python API is enough for same-DB pipelines via a thin Python orchestrator script. Cookbook covers this in Pattern B.
2. **Mid-term (3-6 months):** implement Path 1 (pgai integration). New SQL functions: `pgrg.chunk`, `pgrg.embed`, `pgrg.extract`, `pgrg.resolve_entity`, `pgrg.ingest_record`, `pgrg.search`. Keep Python API as the orchestration layer for batch/CDC; the SQL surface handles trigger/scheduled-job use cases.
3. **Long-term (12+ months):** evaluate whether the pgrx native extension is worth building. Probably only if pgai is not on a supported deployment path and the cloud-availability problem is solvable independently (e.g. Supabase or Neon adds it as a first-class extension).

## What should we ship next?

Honest read: the in-memory `ingest_records()` API closes the immediate "no disk roundtrip" gap. Path 1 (pgai integration) is the next real step but it's a separate workstream from the accuracy roadmap and the public-release work — it's an integration project, not a feature project.

If demand for "pure SQL ingest" emerges from real users (not just blog-post-credibility), prioritize Path 1. If the demand stays theoretical, the Python `ingest_records()` API + cookbook Pattern B is enough — most ETL jobs and CDC streams already run from Python, and the script is 50 lines.

Capture the proposal here, revisit when there's a real user with `pgrg.ingest_record()` written into a trigger.

## Open questions

- **What's the right name for the extension?** `pg_raggraph`, `raggraph`, `pgrg`? Today the Python package is `pg_raggraph`. The SQL surface namespace would naturally be `pgrg.*`.
- **How does this interact with `evolution_tier`?** Tier 1 metadata (`effective_from`, `retracted_at`) should naturally pass through as JSONB metadata; the schema already supports it.
- **GPU usage from inside Postgres** — pgai supports GPU backends but adds complexity. For pgrg-on-postgres, default to CPU embeddings; let the GPU live elsewhere (sidecar, fastembed-server) if needed.
- **Async LLM calls from PG** — Postgres functions are synchronous. A long LLM call blocks one backend. For trigger-driven ingest, that's a problem at any meaningful volume. Solution: enqueue via `pg_cron` + a worker queue table; functions write the queue row and return immediately. The actual extraction happens in a background worker. Good pattern, but real engineering.

## What this proposal is NOT

- Not a commitment to build any of this. The user explicitly said "longer term ask."
- Not a critique of `ingest_records()` — that's the right Python-side API and stays the recommended path until DB-native primitives have a real reason to exist.
- Not advocacy for replacing `pg_raggraph` (the Python library) with an extension. The Python orchestration layer remains valuable for complex workflows, debugging, async batch processing, and any deployment that doesn't want to install an extension.
