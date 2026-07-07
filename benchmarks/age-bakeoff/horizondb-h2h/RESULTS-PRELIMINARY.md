# RESULTS — PRELIMINARY

**Every number here is single-seed, single-machine, preliminary, and based on
ONE gold-labeled question** (all Microsoft's accelerator publishes). Do not
quote any of it without the caveats section. Method: see `README.md`.

- Date: 2026-07-07
- Machine: Apple M5 Max, 128 GB RAM (macOS; both DBs in Docker)
- AGE arm: PostgreSQL 16.14 + Apache AGE 1.5.0 + pgvector 0.8.0 (port 5440)
- pg-raggraph arm: pg-raggraph 0.5.0a19 on PostgreSQL 16.14 + pgvector 0.8.3
  + pg_trgm 1.6 (port 5434, database `pg_raggraph_h2h`)
- Corpus: Microsoft's full shipped demo set — 410 CAP cases, 1,048 in-corpus
  citation edges (manifest sha256 `8a69ebf5…c52a449`)
- Embedder (both arms): fastembed `BAAI/bge-small-en-v1.5`, 384-dim
- Gold question: `"Water leaking into the apartment from the floor above."`
- Gold sets: strict n=20 (labels `gold*`), plus n=26 (adds `orig*`/`maybe*`)
- Latency: 15 questions x (1 warmup + 5 repeats), plus gold question
  (3 warmups + 15 repeats); p50/p95 in ms

## The AAT-002 fact (settled)

Microsoft's single-statement composition of `ag_catalog.cypher()` with
pgvector — their exact CTE shape including the verbatim
`AS (case_id TEXT, ref_id TEXT)` column list — **executed successfully on
stock Apache AGE 1.5.0** and the TEXT-cast join matched correctly
(7/10 vector hits joined citation refs; raw probe output in
`data/results_age.json` → `composability_probe`).

> Our repo's claim "AGE Cypher and pgvector cannot combine in a single
> query" (CLAUDE.md / research/apache-age-evaluation.md) is **false** and
> must be corrected. The defensible narrower claims are about cloud
> availability, ergonomics (agtype casting), and performance at scale — not
> composability.

Portability footnote the other way: Microsoft's *seed* SQL
(`properties ->> 'case_id'`) errors on stock AGE 1.5.0 and required
`->> '"case_id"'::agtype`; their managed Azure build evidently diverges from
stock AGE.

## Recall@k + latency (one question; read caveats first)

R = recall vs gold_strict (n=20), R+ = vs gold_plus (n=26).
"wall" = client-observed per-query time over the 15-question latency set.
"int" = pg-raggraph's internal retrieval timer (`QueryResult.latency_ms`) —
the number comparable to the AGE arm's raw-SQL wall time (see Latency notes).

| arm | R@5 | R@10 | R@20 | R@30 | R@60 | R+@10 | R+@30 | R+@60 | wall p50 | wall p95 | int p50 | int p95 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| AGE vector_baseline | 0.10 | 0.10 | 0.30 | 0.40 | 0.55 | 0.15 | 0.38 | 0.50 | 8.5 | 20.0 | — | — |
| AGE pattern1 (doc verbatim) | 0.15 | **0.25** | 0.30 | 0.40 | 0.55 | 0.23 | 0.38 | 0.50 | 10.3 | 21.4 | — | — |
| AGE accelerator (no rerank) | 0.15 | 0.20 | 0.25 | 0.40 | 0.55 | 0.23 | 0.38 | 0.50 | 13.6 | 28.8 | — | — |
| pgrg naive | 0.10 | **0.25** | **0.35** | 0.35 | 0.55 | **0.27** | 0.42 | **0.62** | 155.4 | 166.6 | 30.3 | 39.4 |
| pgrg naive_boost | 0.15 | **0.25** | **0.35** | 0.40 | 0.55 | 0.23 | **0.46** | **0.62** | 162.1 | 245.8 | 29.0 | 53.5 |
| pgrg local | 0.15 | 0.15 | 0.20 | 0.25 | 0.40 | 0.15 | 0.27 | 0.38 | 201.5 | 214.1 | 67.5 | 82.3 |
| pgrg global | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 155.3 | 165.1 | 24.0 | 25.9 |
| pgrg hybrid | 0.15 | 0.15 | 0.20 | 0.25 | 0.40 | 0.15 | 0.27 | 0.38 | 209.6 | 225.3 | 78.7 | 91.3 |

Raw outputs: `data/results_age.json`, `data/results_pgrg.json` (gitignored;
regenerate via README "Reproduce").

## Reading the table honestly

**Microsoft's authority-boost thesis reproduces directionally on their own
gold set.** Pattern 1 lifts early-rank recall over the vector baseline
(R@10 0.10 → 0.25; it visibly pulls `gold-graph`-labeled cases into the
top 10). It cannot move R@60 because it reranks the same 60 vector
candidates — @60 both are candidate-coverage-bound at 0.55.

**pg-raggraph's best modes here are naive / naive_boost, not the heavy graph
modes.** naive matches Pattern 1 at @10 (0.25) and leads at @20 (0.35 vs
0.30) and on gold_plus @60 (0.62 vs 0.50) — that lead comes from chunking
(≈4 chunks/case = more retrieval surface), not from graph traversal.
naive_boost's 1-hop boost adds a little (R@5 0.15, R+@30 0.46).

**Negative results (ours), verbatim:**

- `local` and `hybrid` UNDERPERFORM naive on this workload (R@60 0.40 vs
  0.55). The query names no entities, so entity-first traversal anchors on
  weak fuzzy entity matches and dilutes the vector signal. On this corpus
  the citation graph helps as a *rescoring* signal (their pattern, our
  naive_boost) — not as an entry point.
- `global` scores 0.00 across the board. It is built for LLM-generated
  community summaries, which don't exist in this no-LLM setup; it degrades
  to retrieval that surfaces zero gold cases (it even surfaced two
  `no`-labeled cases at the top). Recorded as-is; arguably "not applicable"
  rather than "0", but 0 is what a user of that mode would get here.
- **Latency: the AGE arm wins at this scale.** Raw SQL 8.5-13.6 ms p50 vs
  pg-raggraph 24-79 ms p50 internal retrieval, 155-210 ms p50 through the
  Python API. A single-table 410-row corpus with a full edge-list dump is
  exactly where AGE's overheads don't show; nothing here supports (or
  refutes) our repo's 2-40x traversal claims — different scale, different
  shape. The earlier single-machine "42-111x" numbers should not be cited
  alongside these.
- **pg-raggraph API overhead follow-up:** wall time is ~120 ms above the
  internal retrieval timer (trace shows retrieval done at ~17-30 ms). That
  gap is pg-raggraph Python-side post-processing, unprofiled in this run.
  Worth an engineering look; not fixed here (out of scope for a benchmark
  branch).

## Caveats (complete list)

1. **N=1 gold-labeled question** — the accelerator's entire published eval.
   No statistical claim survives N=1; treat every recall figure as an
   anecdote with provenance.
2. **Their 40%→70% is not reproducible from their repo** (no eval script, no
   500K corpus shipped); our vector baseline lands at 0.50-0.55 R@60 on the
   410-case slice with a different embedder — not comparable to either of
   their published numbers.
3. Reranker stage skipped in both arms (azure_ml/azure_ai unavailable
   locally) — the AGE arm is NOT Microsoft's full pipeline.
4. Embedder differs from theirs (bge-small 384-dim vs text-embedding-3-small
   1536-dim); symmetric across arms.
5. Retrieval granularity differs by design (1 vector/case vs ~4 chunks/case
   — each system's native shape over identical raw text).
6. Latency measurement asymmetry: AGE arm = raw SQL wall; pgrg wall includes
   Python API overhead; pgrg "int" is its internal retrieval timer. All
   three reported.
7. 410 cases fits entirely in cache — latency says nothing about 500K-scale
   behavior in either direction.
8. pg-raggraph's fuzzy entity resolution merged 3 of 410 case entities
   (1,043 vs 1,048 edges) — left as shipped behavior.
9. Single seed, single machine, Docker on macOS/ARM.

## What a publishable run needs

See README "What a publishable run would need": a real multi-question gold
set, the full/large CAP corpus under index pressure, a local cross-encoder
rerank stage for both arms, multi-seed runs with confidence intervals, and
ideally a second machine.
