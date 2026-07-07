# CAP gold v1 — RESULTS

Method: `METHODOLOGY.md` (preregistered and committed before any run; its
append-only Deviations section D1/D2 records the two ingest-procedure
changes, both made before any retrieval measurement). Raw per-arm JSON:
`results/results_pgrg.json`, `results/results_age.json` (gitignored;
regenerate via "Reproduce" below).

**Single machine. 3 seeds = a range, not a confidence interval. Read the
caveats before quoting anything.**

- Date: 2026-07-07
- Machine: Apple M5 Max, 128 GB RAM, macOS; both DBs in Docker (single
  machine — every number is machine-scoped)
- pg-raggraph arm: pg-raggraph 0.8.0 (commit 28f461a) on PostgreSQL 16.14,
  pgvector 0.8.3, pg_trgm 1.6 (port 5434, database `pg_raggraph_capgold`)
- AGE arm: PostgreSQL 16.14 + Apache AGE 1.5.0 + pgvector 0.8.0 (port 5440,
  database `capgold_age`)
- Python: psycopg 3.3.3, fastembed 0.8.0
- Embedder (both arms): fastembed `BAAI/bge-small-en-v1.5`, 384-dim,
  computed INSIDE every arm's timed loop
- `PGRG_LLM_BASE_URL=""` — no LLM anywhere (ingest, retrieval, or grading)

## Corpus (public domain, rebuilt from clone by scripts)

| fact | value |
| --- | --- |
| Source | Caselaw Access Project, `static.case.law` (public domain) |
| Selection rule | reporter `wash-2d`, volumes 1–120 inclusive, every case with a non-empty lead opinion (preregistered; no cherry-picking) |
| Cases | **11,548** (all Washington Supreme Court, court 9029) |
| In-corpus citation edges | 48,877 |
| Per-case text (both arms) | `name + opinion[:8000]` (Microsoft's embedding-input shape) |
| pg-raggraph shape | 43,651 chunks (~3.8/case), 11,522 entities, 48,858 CITES edges |
| AGE shape | 11,548 rows/embeddings + `case_graph`: 11,548 nodes, 48,877 REF edges |
| Gold | 50 questions × 3 seeds (41/42/43) × 2 tasks, citation-derived, zero human/LLM labels; pool: 3,705 eligible targets (Task A), 3,073 (Task B) |

Gold set sizes: Task A |gold| = 5–29 (median 9; target + its in-corpus
citations); Task B |gold| = 4–26 (citations only). Because |gold| can
exceed k, recall@k has a mean ceiling < 1.0: Task A ceilings ≈
0.60/0.90/0.99 @5/10/20; Task B ceilings per seed are given with the table.

## Task A — issue-description retrieval

Question: scrubbed excerpt from `opinion[8500:]` — **beyond the 8,000-char
ingest cut**, so the question text has zero verbatim overlap with any
ingested text. Gold = {target} ∪ its in-corpus citations. Mean ± half-range
over seeds 41/42/43 (macro-average over 50 questions each).

| arm | R@5 | R@10 | R@20 |
|---|---|---|---|
| age_vector_baseline | 0.038 ±0.009 | 0.052 ±0.010 | 0.074 ±0.002 |
| age_pattern1 | 0.043 ±0.008 | 0.064 ±0.001 | 0.084 ±0.004 |
| pgrg_naive | 0.066 ±0.016 | 0.091 ±0.016 | 0.129 ±0.014 |
| pgrg_naive_rrf | 0.072 ±0.013 | 0.098 ±0.012 | 0.133 ±0.012 |
| **pgrg_naive_boost** | **0.073 ±0.011** | **0.099 ±0.012** | **0.133 ±0.013** |
| pgrg_local | 0.035 ±0.003 | 0.055 ±0.012 | 0.074 ±0.016 |
| pgrg_hybrid | 0.035 ±0.009 | 0.050 ±0.014 | 0.066 ±0.016 |
| pgrg_hybrid_rrf | 0.026 ±0.006 | 0.036 ±0.006 | 0.061 ±0.015 |

recall_cited (gold = citations only — the graph-shaped part of the gold):

| arm | Rc@5 | Rc@10 | Rc@20 |
|---|---|---|---|
| age_vector_baseline | 0.029 ±0.008 | 0.039 ±0.012 | 0.057 ±0.005 |
| age_pattern1 | 0.035 ±0.007 | 0.054 ±0.004 | 0.069 ±0.007 |
| pgrg_naive | 0.039 ±0.011 | 0.060 ±0.012 | 0.090 ±0.012 |
| pgrg_naive_rrf | 0.040 ±0.008 | 0.058 ±0.007 | 0.090 ±0.011 |
| pgrg_naive_boost | 0.042 ±0.006 | 0.058 ±0.007 | 0.090 ±0.011 |
| pgrg_local | 0.017 ±0.002 | 0.033 ±0.005 | 0.049 ±0.007 |
| pgrg_hybrid | 0.020 ±0.004 | 0.032 ±0.008 | 0.044 ±0.006 |
| pgrg_hybrid_rrf | 0.014 ±0.002 | 0.019 ±0.001 | 0.039 ±0.009 |

target_hit@5 (degeneracy diagnostic, METHODOLOGY §2.5): AGE arms 0.11–0.12,
pgrg naive family 0.25–0.29, graph modes 0.13–0.20. Nowhere near 1.0 → the
task did NOT degenerate into self-lookup; the beyond-the-cut excerpt design
held. (No question generator iterations were needed; the preregistered v1
generator is the one that ran.)

### Reading Task A honestly

- **Microsoft's authority-boost thesis replicates directionally at N=150.**
  Pattern 1 beats their own vector baseline on every metric (R@20 0.074 →
  0.084; Rc@10 0.039 → 0.054). The h2h saw the same direction on N=1; this
  is the same pattern on 150 real questions.
- **pg-raggraph's lead is retrieval surface, not graph traversal.**
  naive_boost (R@20 0.133) beats AGE pattern1 (0.084) by ~58% relative —
  but plain naive scores 0.129. The 1-hop graph boost adds ~3% relative
  over naive; chunking (~3.8 chunks/case) + BM25 fusion account for
  essentially all of the lead over the AGE arm's one-embedding-per-case
  shape. That is a real, shipped-default advantage — but it is not
  evidence that recursive-CTE traversal beats `cypher()` traversal.
- **Negative result, again: the graph-heavy modes lose.** local / hybrid /
  hybrid_rrf (R@20 0.061–0.074) underperform naive (0.129) on
  issue-description queries — at 11.5K docs and N=150, confirming the h2h's
  410-doc, N=1 observation. These questions name no entities, so
  entity-first traversal anchors on weak fuzzy matches and dilutes the
  vector+BM25 signal. On this workload the citation graph helps as a cheap
  rescoring signal (naive_boost), not as an entry point.
- **Absolute recall is low everywhere** (best R@20 0.133 against a ~0.99
  ceiling). Tail-of-opinion excerpts are a hard query class for any
  embedding retrieval — by design (no verbatim overlap). Relative
  comparisons are the point of this benchmark; do not quote absolute
  numbers as "pg-raggraph finds 13% of relevant law".

### Task A latency

Seed 42's 50 questions, 1 warmup pass + 3 timed repeats each (150
samples/arm). Every timed unit is *question text in → ranked cases out*
(single-string embed inside the loop, both arms). AGE arm = raw SQL
client-side; pgrg wall = full Python `GraphRAG.query()` API; pgrg
"internal" = `QueryResult.latency_ms` (its retrieval timer). ms.

| arm | wall p50 | wall p95 | internal p50 | internal p95 |
|---|---|---|---|---|
| age_vector_baseline (SQL) | 9.4 | 14.1 | — | — |
| age_pattern1 (SQL) | 26.9 | 32.1 | — | — |
| pgrg_naive (raw) | 30.6 | 39.2 | 24.1 | 32.8 |
| pgrg_naive_rrf (raw) | 30.2 | 40.4 | 23.9 | 33.7 |
| pgrg_naive_boost (raw) | 36.2 | 44.9 | 24.0 | 33.0 |
| pgrg_local (raw) | 255.3 | 485.8 | 237.1 | 466.1 |
| pgrg_hybrid (raw) | 274.9 | 500.1 | 254.9 | 479.1 |
| pgrg_hybrid_rrf (raw) | 271.6 | 502.7 | 251.9 | 481.8 |
| pgrg_naive (balanced) | 146.7 | 159.3 | 31.1 | 40.9 |
| pgrg_naive_rrf (balanced) | 144.3 | 158.0 | 30.5 | 41.5 |
| pgrg_naive_boost (balanced) | 152.8 | 163.5 | 30.6 | 41.0 |
| pgrg_local (balanced) | 369.3 | 610.5 | 223.2 | 459.1 |
| pgrg_hybrid (balanced) | 395.4 | 638.0 | 239.4 | 480.9 |
| pgrg_hybrid_rrf (balanced) | 397.2 | 631.2 | 239.6 | 476.4 |

- **The AGE arm is faster at like-for-like work.** Their vector baseline
  (9.4 ms) beats pgrg naive raw (30.6 ms); their pattern1 (26.9 ms) is
  slightly faster than pgrg naive_boost raw (36.2 ms) for the analogous
  vector+1-hop-boost job. Note pgrg fetches 200 chunks per query (to
  yield ≥20 distinct cases) vs the AGE arm's 60 rows — more result
  plumbing per query by design.
- pattern1's cost over the baseline (9.4 → 26.9 ms) is its
  `cypher()` full-edge-list enumeration — at 48,877 edges it costs ~17 ms
  per query and grows with the graph, since the published pattern
  enumerates ALL edges, not the neighborhood of the candidates.
- `profile="balanced"` adds ~115 ms of LLM-free context packing over
  `raw` for the naive family (146.7 vs 30.6 wall; internal stays ~31 ms) —
  the packing cost profiled in `benchmarks/regressions/query_latency_profile.py`.
  Rankings are identical raw-vs-balanced (0 mismatches in 5 checked).
- local/hybrid at 255–275 ms raw: 2-hop expansion + rescoring over a
  48.9K-edge graph. Usable, but 8–9× naive for LOWER recall on this
  workload — a shipped-mode result worth stating plainly.

## Task B — citation lookup (the #95 / graph-primitive class)

Question names the caption + official cite ("Which precedents does
Scanlan v. Smith, 66 Wash. 2d 601 (1965), rely on?"); gold = the case's
in-corpus citations; the anchor case is removed from every ranked list
before scoring. This is the class where a graph primitive applies
naturally; `graph_join` proper (bind+intersect) has no analog in a
single-edge-type citation schema and remains unbenchmarked (as
preregistered).

Recall ceilings (|gold| often > 5): @5 0.66–0.76, @10 0.93–0.95, @20 ≈ 1.0
per seed.

| arm | R@5 | R@10 | R@20 |
|---|---|---|---|
| age_vector_baseline | 0.012 ±0.005 | 0.016 ±0.007 | 0.020 ±0.010 |
| age_pattern1 | 0.011 ±0.006 | 0.022 ±0.011 | 0.023 ±0.010 |
| **age_cypher_traverse** | **0.712 ±0.048** | **0.934 ±0.010** | **0.999 ±0.001** |
| pgrg_naive | 0.014 ±0.004 | 0.021 ±0.007 | 0.023 ±0.009 |
| pgrg_naive_boost | 0.017 ±0.005 | 0.020 ±0.008 | 0.023 ±0.009 |
| **pgrg_typed_traverse** | **0.700 ±0.045** | **0.924 ±0.012** | **0.992 ±0.004** |

Latency (seed 42, ms):

| arm | wall p50 | wall p95 |
|---|---|---|
| age_vector_baseline | 4.0 | 5.2 |
| age_pattern1 | 26.3 | 28.9 |
| age_cypher_traverse | 3.5 | 4.2 |
| pgrg_naive | 28.6 | 32.2 |
| pgrg_naive_boost | 35.8 | 41.0 |
| pgrg_typed_traverse | 33.9 | 48.1 |

### Reading Task B honestly

- **This is a task-structure result, not a model achievement**
  (preregistered framing). Both traversal arms sit at or within ~2% of the
  mathematical ceiling; embedding retrieval sits at ~2%. The value of the
  number is the *magnitude of the gap* (~40× at @10) and the failure
  accounting, not "graph beats vector".
- **AGE's Cypher traverse is EXACTLY at the ceiling** on all three seeds
  (its edge set is complete). **pg-raggraph's typed traverse is ~1–2%
  below ceiling** — the measured cost of its fuzzy entity resolution: 32
  false merges collapsed some case entities, dropping 19 of 48,877 CITES
  edges. Anchor misses: 0 in all 300 lookups for both arms.
- **AGE wins Task B latency by ~10×** (3.5 ms vs 33.9 ms p50). Two honest
  reasons: (a) the AGE arm binds the anchor by exact caption equality on
  `cases_updated`, while pg-raggraph's `find_entities` must run a pg_trgm
  fuzzy match because our entity names carry an " (id)" suffix (the
  METHODOLOGY §5 fallback — the naming scheme costs exact-match binding);
  (b) pgrg goes through the full Python API. A 1-hop indexed walk is cheap
  in both systems; nothing here supports the repo's historical multi-x
  traversal claims in either direction at 1 hop.

## Ingest (recorded, not a claim)

| arm | wall | notes |
| --- | --- | --- |
| AGE | 338 s embed + 8 s load | one embedding/case; bulk REF edge insert; all 48,877 edges present |
| pg-raggraph | 888 s ingest + 12 s HNSW rebuild/analyze | doc_concurrency 8, HNSW indexes dropped during load (D1), lexstats triggers disabled + stats recomputed (D2) |

**Library findings from getting the ingest to run at this scale** (all in
Deviations D1/D2; none fixed in this branch):

1. **BM25 lexstats triggers serialize same-namespace concurrent ingest.**
   `lexical_corpus_stats` is one row per namespace, upserted by every
   chunk-insert statement and row-locked until the per-document transaction
   commits — `pg_blocking_pids` showed all 8 writers in `transactionid`
   waits on each other. `doc_concurrency` is structurally ineffective for
   same-namespace ingest while the triggers are enabled. Migration 016's
   own comment names this ceiling and an upgrade path ("move the
   maintenance to an async aggregation of per-statement deltas"); at 11.5K
   docs the ceiling is no longer theoretical: ~9 h projected → 15 min with
   the triggers bypassed for bulk load.
2. **Default ingest profile is slow at corpus scale**: `balanced`
   (doc_concurrency 2) paced ~0.35 docs/s here.
3. **Parallel HNSW builds die on Docker's default 64 MB /dev/shm**
   (`DiskFull`); serial build (`max_parallel_maintenance_workers = 0`)
   completes in seconds at this size.
4. **Entity fuzzy resolution false-merges legal captions at scale.** With
   the h2h naming convention: 137/11,548 entities absorbed (1.19%) —
   including clearly distinct cases ("…Kennewick School District No. 17
   v. Coates" absorbed "…v. Lamanna" and "…v. Black"; combined scores
   0.85–0.87, driven by the 0.6-weighted name-embedding similarity). This
   tripped the preregistered >1% fallback: with all entity names
   " (id)"-suffixed (numeric version guard then refuses same-caption
   merges), merges drop to 32 distinct (0.28%), which still cost 19 CITES
   edges and the ~1–2% Task B ceiling gap. Trade-off: the suffix scheme
   forces every caption-anchor bind through the fuzzy path (Task B latency
   note above).
5. **`hnsw.ef_search` defaults (40) cap the vector candidate stage in both
   arms** — the AGE arm's LIMIT-60 vector stage returns 40 rows through
   the HNSW plan; pg-raggraph's config default is also 40. Recall is
   reported only to @20, within candidate depth everywhere; both arms ran
   shipped defaults (symmetric).

## Caveats (complete list — quote the table only with these)

1. **The gold definition presumes citation relevance.** Gold = the target
   case + what it cites. This measures citation-neighborhood retrieval, not
   general relevance — the same assumption as Microsoft's `gold-graph`
   labels, made explicit. A gold set partly defined by graph edges is
   structurally friendlier to graph-aware arms; the vector-only arms are
   reported on the same footing and the graph contribution is isolated in
   `recall_cited` and Task B.
2. **Questions are machine-scrubbed excerpts, not human queries.** Residual
   fragments of cited-authority names can survive scrubbing (documented in
   METHODOLOGY §2.5) — lexical leakage that, if anything, helps the
   vector-only arms find cited gold (conservative for graph claims). A few
   `[citation]` placeholders and cite fragments (e.g. "P. (2d) 693")
   remain in question text.
3. **Retrieval granularity differs by design** (their shape: 1
   embedding/case; pg-raggraph's shape: ~3.8 chunks/case over identical raw
   text). Task A's pgrg-vs-AGE gap is dominated by this surface difference
   plus BM25 — naive vs naive_boost isolates the graph's (small) Task A
   contribution.
4. **The AGE arm is Microsoft's published *pattern*, not their production
   pipeline** — the `azure_ml` cross-encoder rerank stage doesn't exist
   locally and was skipped (as in the h2h). Do not compare these numbers
   with their published 40%→70%.
5. **Latency asymmetry**: AGE arms time raw SQL client-side; pgrg walls
   include the full Python API (internal timer also reported; `raw` vs
   `balanced` packing cost shown separately). Embedding is inside the
   timed loop in every arm.
6. Single machine, Docker-on-macOS/ARM, 3 seeds (range, not CI), 50
   questions/seed. Question sampling is the only seed-dependent step;
   retrieval itself is deterministic.
7. bge-small-en-v1.5 (384-dim) everywhere — absolute recall is
   embedder-specific.
8. Single reporter/jurisdiction (Washington Supreme Court, wash-2d 1–120).
   Citation graph density and caption-collision rates elsewhere will
   differ.
9. pg-raggraph modes excluded with reasons (preregistered): `global`
   (needs LLM community summaries — none in a no-LLM benchmark; h2h
   measured 0.00), `smart` (router over included arms),
   `accelerator_norerank` (h2h ran it; adds nothing to the
   pattern-vs-baseline question).
10. Ingest wall times are single-run, on a machine also running Docker
    containers; recorded for context, not claims.

## Independent audit (smell-test, 2026-07-07)

An adversarial audit agent re-derived the headline numbers from the live
databases before publication. Verdict: CLEAN. Executed checks included:
full independent seed-42 rescore of pgrg_naive (50 questions replayed:
0.0446/0.0740/0.1182 — exact match) and both AGE arms via raw SQL replay
(exact match); Task B ceiling arithmetic verified to 4 decimals per seed;
the 19-edge merge loss verified at the edge level; ef_search=40 verified
live via EXPLAIN in both arms. Contamination audit: 0/150 Task A questions
contain a case caption (" v. "); 36/150 carry at least one gold-cited
caption *token*, but of pgrg_naive's 53 top-20 gold hits on seed 42 only 1
was attributable to such a leak — the lead is topical vocabulary matching,
not identifier leakage. Minor accounting note: 11,548−11,522 = 26 net
absorbed entities vs 32 distinct merged names in the log (some names
merged repeatedly); no claimed number depends on this.

## Reproduce from clone

Tested end-to-end on this machine (the numbers above are from exactly this
sequence, fresh databases):

```bash
# 0. deps (repo root)
uv sync --extra dev -p 3.12
# postgres for pg-raggraph arm (port 5434):
docker compose up -d postgres
# AGE container (port 5440) — reuses the h2h image/compose:
docker compose -f benchmarks/age-bakeoff/horizondb-h2h/docker-compose.yml up -d

# 1. corpus: downloads wash-2d vols 1-120 (~200 MB) from static.case.law,
#    builds data/corpus.jsonl + manifest (data/ is gitignored)
uv run --no-sync python benchmarks/age-bakeoff/cap-gold-v1/download_corpus.py

# 2. gold sets (deterministic; rerunning yields byte-identical files)
uv run --no-sync python benchmarks/age-bakeoff/cap-gold-v1/build_gold.py

# 3. load both arms (pg-raggraph ~15 min, AGE ~6 min)
uv run --no-sync python benchmarks/age-bakeoff/cap-gold-v1/load_age.py
uv run --no-sync python benchmarks/age-bakeoff/cap-gold-v1/load_pgrg.py

# 4. run (AGE ~4 min; pg-raggraph ~35 min incl. latency loops)
uv run --no-sync python benchmarks/age-bakeoff/cap-gold-v1/run_age.py
uv run --no-sync python benchmarks/age-bakeoff/cap-gold-v1/run_pgrg.py

# 5. tables (renders the markdown above from results/*.json)
uv run --no-sync python benchmarks/age-bakeoff/cap-gold-v1/make_tables.py
```

Determinism notes: gold generation was rerun and verified byte-identical
(sha256); recall is deterministic given the gold files (retrieval has no
randomness); latency numbers are machine- and load-dependent. The corpus
manifest records per-volume sha256 of the CAP zips.
