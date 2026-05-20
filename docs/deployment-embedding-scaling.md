# Deployment & Embedding Scaling

How pg-raggraph's embedding layer behaves under concurrency, what must
change in the library to make it fleet-safe, and how to run it as a
service.

> **TL;DR.** The default in-process local embedder (`BAAI/bge-small-en-v1.5`
> via fastembed/onnxruntime) is the right choice for a *solo library* —
> zero infra, private, no API cost. It is an **anti-pattern at process
> concurrency**: each process loads its own model and onnxruntime grabs
> all cores (measured: **~553% CPU for a single process**). At ~100
> processes you get N× memory, CPU oversubscription, no cross-process
> batching, and a second cliff in Postgres connections. The fix is not a
> rearchitecture — the provider abstraction already exists — it is a set
> of bounded defaults + a dedicated remote-embedding config + an operator
> deployment pattern. Both are below.

---

## 1. The failure mode (evidence-based)

Source of truth: `src/pg_raggraph/embedding.py`, `src/pg_raggraph/config.py`,
`src/pg_raggraph/sql/schema.sql`, and the 2026-05 LoCoMo/MHR sweep runs.

| Axis | Solo (1 proc) | ~100 procs (in-process local) |
|---|---|---|
| Model memory | 1× (~300 MB–1 GB resident incl. onnxruntime arena) | **N×** → OOM |
| CPU | onnxruntime takes ~5–6 cores (553% measured) | **N× oversubscription**; aggregate throughput falls *below* serial (context-switch + cache thrash) |
| Batching | per-process only | **no cross-process batching** (worst case for the most expensive op) |
| Postgres conns | `pool_max` (default 10) | N × `pool_max` → blows `max_connections` |
| Cold start | one model load | N process-level model loads across the fleet; repeated `GraphRAG()` instances now share the process cache |

Original root causes in code, now addressed by F1–F7:

1. **`FastEmbedProvider.__init__` needed thread control.**
   `embedding_threads` now defaults to 1 and is passed through to
   fastembed (`7d069ac`).
2. **Local models needed a process-level cache.** `FastEmbedProvider`
   now pulls from an `lru_cache` keyed by `(model_name, threads)`
   (`dcdc2a4`).
3. **Embeddings needed a dedicated endpoint.** `embedding_provider="http"`
   now uses `embedding_base_url` / `embedding_api_key`, while
   `local|openai|ollama` stay backwards-compatible (`da656f7`).
4. **HTTP embeddings needed connection reuse and explicit batching.**
   `HttpxEmbeddingProvider` now owns one `httpx.AsyncClient`, closes it on
   provider close, and chunks requests by `embed_batch_size` (`2a1e13b`).
5. **`ingest_records` always embeds.** `skip_extraction` / `skip_llm`
   skip *LLM graph extraction*, not the vector embedding. There is no
   embedding-skip; embedding is mandatory in the ingest path. F7 now
   avoids recomputing identical embedded text under the same embedding
   fingerprint.
6. **Embedding dimension is bootstrap-locked per database.**
   `schema.sql` creates `vector({dim})` from `embedding_dim` at schema
   bootstrap. You cannot mix embedders of different dims in one database;
   changing dims means a new database/schema + re-ingest.

---

## 2. Library fixes now implemented

Each item below has a library-side implementation and an automated scale
test. The operator guidance remains useful for deployment sizing and for
older releases.

### F1 — Bound onnxruntime threading (CRITICAL)

**Status:** implemented in `7d069ac`.

`FastEmbedProvider` must not let onnxruntime grab all cores. The config
knob is now passed through.

- `config.py`: `embedding_threads: int = 1` (0 = library default).
- `embedding.py`: constructs fastembed with bounded threads, e.g.
  `TextEmbedding(model_name=..., threads=cfg.embedding_threads)` (fastembed
  forwards to onnxruntime `SessionOptions.intra_op_num_threads`), and/or
  set `OMP_NUM_THREADS` before model init.
- Default `1` is correct for multi-process hosts; a dedicated batch
  ingester can raise it.

**Impact:** removes the 553%-CPU-per-process oversubscription — the
single highest-leverage fix for concurrency.

### F2 — Process-level model cache (CRITICAL)

**Status:** implemented in `dcdc2a4`.

Caches the loaded model by `model_name` at module scope so N `GraphRAG`
instances in one process share one ONNX session.

- `embedding.py`: `@lru_cache` registry keyed by
  `(model_name, threads)`; `FastEmbedProvider` pulls from it.
- Eliminates repeat model loads in workers / sweeps / request handlers.

### F3 — Dedicated embedding endpoint config (HIGH)

**Status:** implemented in `da656f7`.

Embeddings can now be decoupled from the LLM endpoint.

- `config.py`: `embedding_base_url: str = ""`, `embedding_api_key: str = ""`.
- `embedding.py`: `embedding_provider="http"` (OpenAI-compatible)
  that uses `embedding_base_url`/`embedding_api_key`/`embedding_model`/
  `embedding_dim`. Keep `local|openai|ollama` for back-compat.
- Lets a fleet point all processes at one shared embedding service while
  LLM extraction (if any) goes elsewhere or nowhere.

### F4 — Reuse httpx client + honor batch size (HIGH)

**Status:** implemented in `2a1e13b`.

- `HttpxEmbeddingProvider`: construct one `httpx.AsyncClient` in
  `__init__` (keep-alive), close on provider close.
- Chunk `texts` into `config.embed_batch_size` sub-batches in `embed()`
  so a shared server batches predictably.

### F5 — Loud concurrency guidance (MED)

**Status:** implemented in `a1b3c74`.

Mirrors the existing default-DSN warning pattern: when
`embedding_provider == "local"`, emit a one-time WARNING pointing at this
doc ("local embedder is per-process; for >1 concurrent worker use a
shared embedding endpoint — see F3").

### F6 — Connection-pool guardrail (MED)

**Status:** implemented in `5fbe231`.

`pool_max` default 10 × 100 procs = 1000 connections. The docs retain the
pgbouncer requirement, and config now warns when either per-process
`pool_max` or the observed `pool_max × workers` heuristic is risky.

### F7 — Content-hash embedding cache (OPTIONAL)

**Status:** implemented in `35d8190`.

Cache `sha256(text) → vector` (in Postgres or a shared KV) so identical
text isn't re-embedded across processes / re-ingests. The cache is scoped
by embedding provider/model/dimension/endpoint fingerprint so changing
vector spaces cannot reuse stale vectors. Biggest win for re-ingest-heavy
or duplicate-doc corpora.

**Suggested order:** F1 → F2 → F3 → F4 → F5 → F6 → F7. F1+F2 alone make a
single host with a bounded worker count safe; F3+F4 enable true
horizontal scale; F5+F6 prevent foot-guns; F7 is throughput polish.

---

## 3. Running pg-raggraph as a service

Target topology for many concurrent processes:

```
                 ┌─────────────────────────────┐
  N app workers  │  pg-raggraph (as a library) │   embedding_provider=http
  (query path) ──┤  embedding_base_url ────────┼──────────────┐
                 │  dsn ───────────────────────┼───┐          │
                 └─────────────────────────────┘   │          │
                                                    ▼          ▼
                                          ┌──────────────┐  ┌───────────────────┐
  batch ingest worker(s) ─────────────────│  pgbouncer   │  │ shared embedding  │
  (few, high-throughput, embed-heavy)     │  → Postgres  │  │ service (TEI /    │
                                          │  (pgvector)  │  │ Infinity, batched │
                                          └──────────────┘  │ GPU or bounded CPU│
                                                             └───────────────────┘
```

Two invariants:

- **One model, many callers.** Exactly one embedding service loads the
  model; all pg-raggraph processes call it over the network. Memory and
  CPU become ~constant, not N×, and requests batch across callers.
- **Separate the embed-heavy path from the hot path.** Ingest embeds the
  corpus (heavy → a few bounded batch workers, can use GPU). Query embeds
  one short string (cheap → the many request workers). Never run the
  in-process local embedder on the request fleet.

### 3.1 Stand up a shared embedding service

Any OpenAI-compatible `/embeddings` server works. Recommended self-hosted,
batched options:

- **HuggingFace TEI** (`text-embeddings-inference`) — purpose-built,
  dynamic batching, CPU or GPU.
- **Infinity** — similar, multi-model.
- **Ollama** — convenient, lower throughput; fine for small fleets.

```yaml
# docker-compose.yml (sketch)
services:
  embedder:
    image: ghcr.io/huggingface/text-embeddings-inference:cpu-latest
    command: ["--model-id", "BAAI/bge-base-en-v1.5", "--max-batch-tokens", "16384"]
    ports: ["8080:80"]            # exposes OpenAI-compatible /v1/embeddings
    deploy: { resources: { limits: { cpus: "8", memory: 8g } } }

  pgbouncer:
    image: edoburu/pgbouncer
    environment:
      DATABASE_URL: postgres://postgres:postgres@postgres:5432/pg_raggraph
      POOL_MODE: transaction
      MAX_CLIENT_CONN: "1000"
      DEFAULT_POOL_SIZE: "25"
    ports: ["6432:6432"]

  postgres:
    image: pgvector/pgvector:pg16
    # pgvector + pg_trgm; max_connections sized for pgbouncer, not app procs
```

Pick the embedding model **once** — it fixes the vector dimension for the
whole database (`bge-base-en-v1.5` → 768, `bge-small` → 384,
`bge-large` → 1024). Changing it later means a new DB + re-ingest
(`schema.sql` locks `vector({dim})` at bootstrap).

### 3.2 Point pg-raggraph at it

Use the explicit HTTP embedding provider for an OpenAI-compatible embedding
endpoint:

```bash
# every app/ingest process
export PGRG_DSN="postgresql://app:***@pgbouncer:6432/pg_raggraph"
export PGRG_EMBEDDING_PROVIDER=http
export PGRG_EMBEDDING_BASE_URL="http://embedder:80/v1"
export PGRG_EMBEDDING_MODEL="BAAI/bge-base-en-v1.5"
export PGRG_EMBEDDING_DIM=768                # MUST match the server's model AND the DB
export PGRG_POOL_MAX=4                        # × workers must stay under pgbouncer pool
```

The older `ollama` provider remains supported for backwards compatibility
when embeddings intentionally share `llm_base_url`:

```bash
export PGRG_EMBEDDING_PROVIDER=ollama
export PGRG_LLM_BASE_URL="http://embedder:80/v1"
export PGRG_EMBEDDING_MODEL="BAAI/bge-base-en-v1.5"
export PGRG_EMBEDDING_DIM=768
```

> Compatibility caveat: `embedding_provider=ollama` still makes embeddings
> reuse `llm_base_url`. Prefer `embedding_provider=http` when embedding and
> LLM extraction should go to different endpoints.

### 3.3 Split ingest from serving

| Role | Count | Embedding | Notes |
|---|---|---|---|
| Ingest workers | few (1–4) | shared endpoint, larger batches | `embed_batch_size` high; can target a GPU embedder; `nice`/throttle via ingest profile |
| Query/request workers | many (≈100) | shared endpoint, batch≈1 | query embeds one short string; never the local in-process model |

Re-ingesting the same embedded text under the same embedding fingerprint
uses the shared content-hash embedding cache. Ingest is still embed-heavy
for new text, so schedule it as a bounded batch job, not on the request
path.

### 3.4 Sizing rules of thumb

- **Embedding service**: size for *ingest* peak, not query (query embed
  is tiny). Start 1 replica; add replicas behind a round-robin when
  ingest batch latency climbs. GPU only if ingest volume justifies it.
- **Postgres connections**: app procs connect to **pgbouncer**, not
  Postgres directly. `Postgres max_connections` sized for
  `pgbouncer DEFAULT_POOL_SIZE`, *not* for `N_procs × PGRG_POOL_MAX`.
  Keep `PGRG_POOL_MAX` small (2–4).
- **If you must run local in-process** (no shared service): set
  `embedding_threads=1`, cap concurrent processes at roughly
  `cores / 2`, and accept N× model memory. This is a stopgap, not scale.

### 3.5 Guardrails / common foot-guns

- ❌ Local embedder on a 100-worker request fleet → OOM + CPU thrash.
- ❌ `PGRG_EMBEDDING_DIM` ≠ the server model's real dim → silently wrong
  vectors / dimension errors at insert. It must equal the model dim
  **and** the DB's bootstrapped `vector(dim)`.
- ❌ App procs connecting straight to Postgres at high process count →
  `too many connections`. Always front with pgbouncer.
- ❌ Changing the embedding model on an existing DB → dimension mismatch.
  New model = new database + re-ingest.
- ✅ One embedding service, bounded threads, pgbouncer, ingest/serve
  split → flat memory & CPU as you scale workers.

---

## 4. Status of this guidance

- The failure mode and code references are verified against the current
  tree (`embedding.py`, `config.py`, `schema.sql`) and the 2026-05 sweep
  evidence (553% CPU/process; embedder is the dominant retrieval-quality
  *and* cost lever).
- §2 (F1–F7) is implemented in `7d069ac`, `dcdc2a4`, `da656f7`,
  `2a1e13b`, `a1b3c74`, `5fbe231`, and `35d8190`.
- §3 is operator-ready via the explicit `http` embedding provider. The
  `ollama` provider remains a compatibility escape hatch.
