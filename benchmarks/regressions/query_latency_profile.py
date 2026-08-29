#!/usr/bin/env python3
"""Query-API latency profile + regression check.

Answers "where does rag.query() wall time go beyond the internal retrieval
timer?" (h2h finding: 24-79 ms internal vs 155-210 ms wall at 410 docs).

Phases measured per query (perf_counter wrappers, no library changes):
  - profile resolution (calibration JSON load + namespace_settings lookup)
  - retrieval (pg_raggraph.retrieval.query), split into
      embed / SQL / python remainder (row->model, tsquery, scoring)
  - context packing (pack_query_context), split into SQL / python (lede)
  - graph_status_summary round trip
  - fetch_all plumbing: pool checkout + per-connection prepare
    (register_vector + set_config round trips), summed across all calls

No LLM anywhere: PGRG_LLM_BASE_URL is forced empty, ingest uses skip_llm.

Usage (own throwaway DB, deterministic synthetic corpus):
    uv run --no-sync python benchmarks/regressions/query_latency_profile.py

Against an existing corpus (e.g. the h2h DB) without ingesting:
    uv run --no-sync python benchmarks/regressions/query_latency_profile.py \
        --db-url postgresql://postgres:postgres@localhost:5434/pg_raggraph_h2h \
        --skip-ingest --top-k 400

Regression gate (manual, not CI — timings are machine-dependent):
    ... --assert-overhead-ms 60   # fail if p50 (wall - retrieval) exceeds this
"""

from __future__ import annotations

import argparse
import asyncio
import os
import statistics
import time

# No LLM may join the measurement (machine may have a live Ollama).
os.environ["PGRG_LLM_BASE_URL"] = ""

import psycopg  # noqa: E402

DEFAULT_DB = "postgresql://postgres:postgres@localhost:5434/pg_raggraph_perf"

QUESTIONS = [
    "Water leaking into the apartment from the floor above.",
    "What are the tenant's obligations for property maintenance?",
    "Negligence claims arising from structural building defects.",
    "How is liability apportioned between landlord and contractor?",
    "Breach of warranty in residential lease agreements.",
]

# ---------------------------------------------------------------- corpus

_WORDS = (
    "landlord tenant lease premises damages liability negligence contract "
    "warranty repair water pipe ceiling apartment building inspection court "
    "plaintiff defendant appeal judgment evidence statute maintenance floor "
    "leak injury notice breach covenant habitability rent eviction insurance"
).split()


def synth_corpus(n_docs: int, seed: int = 42) -> list[dict]:
    """Deterministic sentence-shaped legal-ish text, ~4-5 KB per doc."""
    import random

    rng = random.Random(seed)
    records = []
    for i in range(n_docs):
        sentences = []
        for _ in range(40):
            words = rng.choices(_WORDS, k=rng.randint(9, 16))
            sentences.append(" ".join(words).capitalize() + ".")
        records.append(
            {
                "text": f"Case {i}: " + " ".join(sentences),
                "source_id": f"perfcase:{i}",
                "skip_llm": True,
            }
        )
    return records


def ensure_database(db_url: str) -> None:
    base, _, dbname = db_url.rpartition("/")
    with psycopg.connect(base + "/postgres", autocommit=True) as conn:
        row = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (dbname,)).fetchone()
        if not row:
            conn.execute(f'CREATE DATABASE "{dbname}"')
            print(f"created database {dbname}")
    with psycopg.connect(db_url, autocommit=True) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        conn.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")


# ------------------------------------------------------- instrumentation

PHASE = "other"  # queries run sequentially; a plain global is enough
ACC: dict[str, float] = {}
COUNTS: dict[str, int] = {}


def _add(key: str, ms: float) -> None:
    ACC[key] = ACC.get(key, 0.0) + ms
    COUNTS[key] = COUNTS.get(key, 0) + 1


def reset_acc() -> None:
    ACC.clear()
    COUNTS.clear()


def install_wrappers(rag) -> None:
    """Wrap the phases of GraphRAG.query() with timers. Idempotent per process."""
    global PHASE
    import pg_raggraph.context as context_mod
    import pg_raggraph.profiles as profiles_mod
    import pg_raggraph.retrieval as retrieval_mod
    from pg_raggraph.db import Database

    # -- calibration JSON load (disk read inside resolve_profile)
    orig_load = profiles_mod.load_profile_calibration

    def timed_load(path=None):
        t0 = time.perf_counter()
        out = orig_load(path)
        _add("calibration_load", (time.perf_counter() - t0) * 1000)
        return out

    profiles_mod.load_profile_calibration = timed_load
    # resolve_profile captured load_profile_calibration at def time via module
    # global lookup — same module attr, so the patch is picked up.

    # -- retrieval (smart mode re-enters retrieval.query; time outermost only)
    orig_retrieval = retrieval_mod.query
    depth = 0

    async def timed_retrieval(*args, **kwargs):
        global PHASE
        nonlocal depth
        PHASE = "retrieval"
        depth += 1
        t0 = time.perf_counter()
        try:
            return await orig_retrieval(*args, **kwargs)
        finally:
            depth -= 1
            if depth == 0:
                _add("retrieval_total", (time.perf_counter() - t0) * 1000)
                PHASE = "other"

    retrieval_mod.query = timed_retrieval

    # -- context packing
    orig_pack = context_mod.pack_query_context

    async def timed_pack(**kwargs):
        global PHASE
        PHASE = "context"
        t0 = time.perf_counter()
        try:
            return await orig_pack(**kwargs)
        finally:
            _add("context_total", (time.perf_counter() - t0) * 1000)
            PHASE = "other"

    context_mod.pack_query_context = timed_pack

    # -- graph status + namespace profile lookup (instance methods)
    orig_status = rag._graph_status_summary
    orig_ns_profile = rag._namespace_profile_value

    async def timed_status(ns):
        global PHASE
        PHASE = "status"
        t0 = time.perf_counter()
        try:
            return await orig_status(ns)
        finally:
            _add("graph_status", (time.perf_counter() - t0) * 1000)
            PHASE = "other"

    async def timed_ns_profile(ns):
        t0 = time.perf_counter()
        try:
            return await orig_ns_profile(ns)
        finally:
            _add("ns_profile_lookup", (time.perf_counter() - t0) * 1000)

    rag._graph_status_summary = timed_status
    rag._namespace_profile_value = timed_ns_profile

    # -- embedder
    embedder = rag._get_embedder()
    orig_embed = embedder.embed

    async def timed_embed(texts):
        t0 = time.perf_counter()
        try:
            return await orig_embed(texts)
        finally:
            _add("embed", (time.perf_counter() - t0) * 1000)

    embedder.embed = timed_embed

    # -- fetch_all plumbing. Mirrors Database.fetch_all (db.py) so we can
    # split pool checkout / prepare_connection / execute+fetch / dict-convert.
    # If db.py's fetch_all changes shape, update this copy.
    async def timed_fetch_all(self, query_str, params=None):
        t0 = time.perf_counter()
        async with self._pool_for_read().connection() as conn:
            t1 = time.perf_counter()
            await self._prepare_connection(conn)
            t2 = time.perf_counter()
            cur = await conn.execute(query_str, params, prepare=False)
            if cur.description is None:
                out = []
                t3 = t4 = time.perf_counter()
            else:
                columns = [desc.name for desc in cur.description]
                rows = await cur.fetchall()
                t3 = time.perf_counter()
                out = [dict(zip(columns, row)) for row in rows]
                t4 = time.perf_counter()
        _add("sql_pool_checkout", (t1 - t0) * 1000)
        _add("sql_conn_prepare", (t2 - t1) * 1000)
        _add("sql_execute", (t3 - t2) * 1000)
        _add("sql_row_convert", (t4 - t3) * 1000)
        _add(f"sql_in_{PHASE}", (t3 - t0) * 1000)
        _add("fetch_all_calls", 0.0)  # count only
        return out

    Database.fetch_all = timed_fetch_all


# --------------------------------------------------------------- report

PHASE_ROWS = [
    ("embed (query embedding)", "embed"),
    ("retrieval total (int timer scope)", "retrieval_total"),
    ("  retrieval: SQL (incl. plumbing)", "sql_in_retrieval"),
    ("context packing total", "context_total"),
    ("  context: SQL (incl. plumbing)", "sql_in_context"),
    ("graph_status_summary", "graph_status"),
    ("namespace profile lookup", "ns_profile_lookup"),
    ("calibration JSON load", "calibration_load"),
    ("SQL plumbing: pool checkout", "sql_pool_checkout"),
    ("SQL plumbing: conn prepare", "sql_conn_prepare"),
    ("SQL: execute+fetch", "sql_execute"),
    ("SQL: row->dict convert", "sql_row_convert"),
]


def p50(xs: list[float]) -> float:
    return statistics.median(xs) if xs else 0.0


async def run(args) -> int:
    from pg_raggraph import GraphRAG

    ensure_database(args.db_url)
    rag = GraphRAG(dsn=args.db_url, skip_extraction=True)
    await rag.connect()
    failed = False
    try:
        if not args.skip_ingest:
            n = (await rag.db.fetch_one("SELECT COUNT(*) AS n FROM documents"))["n"]
            if n < args.docs:
                print(f"ingesting {args.docs} synthetic docs (have {n}) ...")
                await rag.ingest_records(synth_corpus(args.docs))
            else:
                print(f"reusing existing corpus ({n} docs)")

        install_wrappers(rag)
        query_kwargs = {}
        if args.top_k:
            query_kwargs["top_k"] = args.top_k
        if args.profile:
            query_kwargs["profile"] = args.profile

        for mode in args.modes.split(","):
            # warmups (embedder ONNX session, pool, PG caches)
            for q in QUESTIONS[: args.warmups]:
                await rag.query(q, mode=mode, **query_kwargs)

            samples: list[dict[str, float]] = []
            walls, internals = [], []
            for i in range(args.repeats):
                q = QUESTIONS[i % len(QUESTIONS)]
                reset_acc()
                t0 = time.perf_counter()
                res = await rag.query(q, mode=mode, **query_kwargs)
                walls.append((time.perf_counter() - t0) * 1000)
                internals.append(res.latency_ms)
                samples.append(dict(ACC, fetch_calls=COUNTS.get("fetch_all_calls", 0)))

            wall = p50(walls)
            internal = p50(internals)
            print(
                f"\n=== mode={mode} db={args.db_url.rsplit('/', 1)[-1]} "
                f"kwargs={query_kwargs} repeats={args.repeats} ==="
            )
            print(f"{'phase':<40} {'p50 ms':>8} {'% wall':>7}")
            print("-" * 58)
            print(f"{'WALL rag.query()':<40} {wall:>8.1f} {'100.0':>7}")
            print(
                f"{'internal QueryResult.latency_ms':<40} {internal:>8.1f} "
                f"{100 * internal / wall:>7.1f}"
            )
            for label, key in PHASE_ROWS:
                vals = [s.get(key, 0.0) for s in samples]
                v = p50(vals)
                if v >= 0.05:
                    print(f"{label:<40} {v:>8.1f} {100 * v / wall:>7.1f}")
            accounted = p50(
                [
                    s.get("retrieval_total", 0)
                    + s.get("context_total", 0)
                    + s.get("graph_status", 0)
                    + s.get("ns_profile_lookup", 0)
                    for s in samples
                ]
            )
            print(
                f"{'unaccounted (wall - phases)':<40} {wall - accounted:>8.1f} "
                f"{100 * (wall - accounted) / wall:>7.1f}"
            )
            print(f"fetch_all calls/query (p50): {p50([s['fetch_calls'] for s in samples]):.0f}")

            overhead = wall - p50([s.get("retrieval_total", 0) for s in samples])
            if args.assert_overhead_ms and overhead > args.assert_overhead_ms:
                print(
                    f"REGRESSION: non-retrieval overhead {overhead:.1f} ms "
                    f"> budget {args.assert_overhead_ms} ms (mode={mode})"
                )
                failed = True
    finally:
        await rag.close()
    return 1 if failed else 0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db-url", default=DEFAULT_DB)
    ap.add_argument("--docs", type=int, default=200)
    ap.add_argument("--repeats", type=int, default=20)
    ap.add_argument("--warmups", type=int, default=3)
    ap.add_argument("--modes", default="naive,smart")
    ap.add_argument("--top-k", type=int, default=None)
    ap.add_argument("--profile", default=None, help="retrieval profile (e.g. raw, balanced)")
    ap.add_argument("--skip-ingest", action="store_true")
    ap.add_argument(
        "--assert-overhead-ms",
        type=float,
        default=None,
        help="exit 1 if p50 non-retrieval overhead exceeds this budget",
    )
    raise SystemExit(asyncio.run(run(ap.parse_args())))


if __name__ == "__main__":
    main()
