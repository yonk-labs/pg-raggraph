# Deploying pg-raggraph

pg-raggraph is a Python library + CLI. For a single-node deployment the
easiest path is the bundled `docker-compose.prod.yml`: one Postgres container
with pgvector + pg_trgm, one container running `pgrg serve`.

## 1. Single-node Docker (smallest viable deploy)

```bash
cp .env.example .env
# Edit .env and set PGRG_PASSWORD and (optional) PGRG_LLM_*
docker compose -f docker-compose.prod.yml up -d --build
```

The `pgrg` service builds from the local `Dockerfile` (source install —
`pg-raggraph` is not yet on PyPI). Rebuild with `--build` after upgrading.

`pgrg` will be available at `http://localhost:8080`. Postgres is only reachable
from inside the compose network by default — uncomment the `ports:` block in
`docker-compose.prod.yml` to expose it.

### .env.example

```
PGRG_DB=pg_raggraph
PGRG_USER=postgres
PGRG_PASSWORD=change-me
PGRG_LLM_BASE_URL=https://api.openai.com/v1
PGRG_LLM_API_KEY=YOUR_API_KEY_HERE
PGRG_LLM_MODEL=gpt-4o-mini
```

## 2. Managed Postgres (RDS, Cloud SQL, Supabase, Neon)

pg-raggraph only needs `pgvector` and `pg_trgm`. Most managed providers
support both. Steps:

1. Create a database instance with pgvector 0.7+ available.
2. Run once as superuser:
   ```sql
   CREATE EXTENSION IF NOT EXISTS vector;
   CREATE EXTENSION IF NOT EXISTS pg_trgm;
   ```
3. Point `PGRG_DSN` at the managed instance:
   ```
   PGRG_DSN=postgresql://user:pass@host:5432/dbname?sslmode=require
   ```
4. Run `pgrg init` once — the schema auto-creates on first connect.

## 3. Embedded (inside your own app)

```python
from pg_raggraph import GraphRAG

async with GraphRAG("postgresql://...") as rag:
    await rag.ingest(["./docs/"])
    result = await rag.ask("How does auth work?")
    print(result.answer)
```

No extra server needed. The library shares your app's Postgres — the tables
are namespaced (`pgrg_*`, `chunks`, `entities`, etc.) and isolated by
`namespace` so they can coexist with your own schema.

## Sizing

- **Memory:** Postgres wants at least 1 GB. `fastembed` adds ~250 MB for the
  default BGE-small model (loaded once).
- **Disk:** ~3× the raw corpus size (original text + vector index + BM25
  tsvector).
- **CPU:** Ingestion is the expensive path. Tune via `PGRG_INGEST_PROFILE`:
  `conservative`, `balanced` (default), `aggressive`, `max`.

## Backups

Standard `pg_dump`. All state lives in Postgres — no other files to back up.

```bash
pg_dump -Fc $PGRG_DSN > pgrg.dump
pg_restore -d $PGRG_DSN pgrg.dump
```

## Upgrades

On startup, `GraphRAG.connect()` checks `pgrg_meta.schema_version` and applies
any pending migrations from `sql/migrations/`. Migrations are run inside a
transaction and only commit on success. Back up first.

## LLM-less mode

The library works without an LLM — set `PGRG_SKIP_EXTRACTION=true` (or unset
`PGRG_LLM_BASE_URL`) and ingestion stores chunks + embeddings only. Queries
return ranked chunks; `rag.ask()` falls back to a top-chunk summary. This is
the simplest way to run pg-raggraph as a pure vector RAG.
