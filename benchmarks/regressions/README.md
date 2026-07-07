# Latency / behavior regression checks

Runnable-by-hand checks, not CI asserts — wall-clock numbers are
machine-dependent and flaky in CI.

## `query_latency_profile.py`

Per-phase breakdown of `rag.query()` wall time (embed / retrieval SQL /
context packing / status round trips / pool + connection plumbing). Built to
chase the HorizonDB h2h finding (~120 ms wall above the internal retrieval
timer); keep using it whenever query-path wall time looks off.

```bash
# Own throwaway DB (pg_raggraph_perf), 200 deterministic synthetic docs:
uv run --no-sync python benchmarks/regressions/query_latency_profile.py

# Against an existing corpus, no ingest:
uv run --no-sync python benchmarks/regressions/query_latency_profile.py \
    --db-url postgresql://postgres:postgres@localhost:5434/pg_raggraph_h2h \
    --skip-ingest --top-k 400 --modes naive

# Manual regression gate — fail if p50 non-retrieval overhead exceeds budget:
uv run --no-sync python benchmarks/regressions/query_latency_profile.py \
    --modes naive --assert-overhead-ms 80
```

Needs Postgres on :5434 and the `lede` package (`uv pip install lede`) for
the default "balanced" profile's context packing; `PGRG_LLM_BASE_URL` is
forced empty so no LLM ever joins the measurement.

Reference numbers (M5 Max, Docker PG, 200 synthetic docs, mode=naive,
default profile, 2026-07-07 after the per-connection pgvector-registration
cache): wall p50 ~70 ms = context packing ~59 ms (lede, by design for the
"balanced" profile) + retrieval ~8 ms (incl. ~2 ms embed) + ~2 ms status/
profile lookups. With `--profile raw`, wall ~= retrieval. Non-retrieval
overhead materially above ~80 ms here means something regressed.
