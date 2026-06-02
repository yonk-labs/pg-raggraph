# Bench Results — 2026-05-28 (post-merge of PR #51 + #52 + #53)

Three benchmarks covering the three subsystems shipped in v0.5.0a2 / 0.5.0a3 /
0.5.0a4. Run on the local dev box against `localhost:5434` test DB right
after merging all three feature PRs into `chunkshop-0.6-integration`.

## Bench A — MCP staleness chokepoint overhead

**Script:** `benchmarks/mcp_freshness_perf.py`
**Code under test:** `pg_raggraph.mcp_helpers._apply_freshness` + `Database.list_pending_documents`
**Method:** 200 chokepoint calls per cell against a synthetic response dict;
cumulative growth of pending docs in the namespace.

| Pending docs in namespace | p50 ms | p95 ms | Mean ms | Banner present? |
|---:|---:|---:|---:|---|
| 0 | 1.23 | 5.41 | 1.84 | no (empty) |
| 10 | 1.05 | 3.38 | 1.50 | yes |
| 100 | 1.21 | 3.79 | 1.66 | yes |
| 1,000 | 1.35 | 3.87 | 1.74 | yes |
| 10,000 | 4.23 | 10.61 | 5.26 | yes |

**Takeaways:**

- The chokepoint adds **~1 ms p50 overhead per MCP tool call** for namespaces under 1k pending docs. Negligible.
- At 10k pending docs the cost climbs to ~4 ms p50 / ~11 ms p95 — still well below the chunk-retrieval cost, so the freshness signal stays cheap even on big backlogs.
- The "empty" case (no pending docs) costs **1.2 ms** — same order as the populated cases, dominated by the partial-index scan that finds zero matches.

**Recommendation:** ship as-is. If a deployment routinely carries >50k pending docs per namespace, revisit the partial-index strategy or memoize the per-namespace summary at the chokepoint level.

## Bench B — `resolve_entity_lookup` throughput

**Script:** `benchmarks/resolve_lookup_perf.py`
**Code under test:** `pg_raggraph.resolution.resolve_entity_lookup`
**Method:** 500 lookups per cell, round-robin over 10 surfaces per match type.

| Entities | Match type | calls/s | p50 ms | p95 ms |
|---:|---|---:|---:|---:|
| 100 | exact | 487 | 1.26 | 6.48 |
| 100 | trgm / vector | 45 | 20.4 | 31.0 |
| 1,000 | exact | 539 | 1.35 | 4.40 |
| 1,000 | trgm / vector | 40 | 24.3 | 34.6 |
| **10,000** | **exact** | **611** | **1.22** | **3.93** |
| **10,000** | **trgm / vector** | **17** | **59.4** | **70.6** |

**Takeaways:**

- Exact-name lookups hit the `entities(namespace, name)` btree index and scale flat: ~500-600 calls/s across 100→10k entities, p50 ~1.2-1.4 ms.
- The fuzzy path (`pg_trgm` similarity + vector cosine fallback) is **15-50× slower** than exact and **degrades super-linearly with entity count** — 20 ms → 24 ms → 59 ms p50 going from 100 → 1k → 10k entities. HNSW search + trgm sequential scan are the dominant costs.

**Operational implications:**

- A chunkshop A/B run on a typical question (~5-20 surfaces per question, 12-30 questions, 2 modes, 2 corpora) is ~500-2000 lookups. At 17 calls/s worst-case (10k-entity namespace, fuzzy path), that's a **~30-120 s** entity-resolution wall slot per A/B run.
- The plans flagged caller-side caching as the strategy. Bench B confirms it's load-bearing — without an LRU around `resolve_entity_lookup`, the harness wall time will be dominated by re-resolving the same surfaces.

## Bench C — A/B gate end-to-end smoke

**Script:** `benchmarks/ab_gate_smoke.py`
**Code under test:** the full `#47 → #48 → #49 → #50` chain
**Method:** Tiny synthetic 4-doc corpus + 2 gold questions, all four stages composed.

| Stage | Wall time | Output |
|---|---:|---|
| 1. Ingest (`fact_extractor=lede_spacy`) | **1.14 s** | 4 docs, 4 chunks, 3 entities, 1 relationship |
| 2. A/B matrix (`run_ab_matrix`) | **0.09 s** | 2 cells written (naive_vector 13.8 ms/q, graph_leg 30.9 ms/q) |
| 3. Verdict (`compute_verdict.from_premeasured`) | **<1 ms** | `ABVerdict(label=NAIVE_WINS, …)` |
| 4. Report (`write_verdict_report`) | **<1 ms** | `verdict.json` (1.2 KB), `verdict.md` (0.9 KB), `latency.json` (0.5 KB) |
| **Total** | **1.23 s** | All four PRs compose end-to-end |

**Takeaways:**

- The whole chain works. `resolve_entity_lookup` (PR #47) → `run_harness_mode` (PR #48) → `run_ab_matrix` (PR #49) → `compute_verdict.from_premeasured` + `write_verdict_report` (PR #50) compose without error.
- **Production-path `compute_verdict(runner_outputs, judge_config)` still raises `NotImplementedError`** — waits on the live llm-judge integration against real bakeoff corpora. The fixture path (`from_premeasured`) is the only fully wired path until that lands. The smoke uses `from_premeasured` driven by metrics computed from real runner output, which is the closest thing to the production path that's actually wireable today.
- The NAIVE_WINS verdict is **noise** — synthetic 4-doc corpus + placeholder 50/50 judge + `lede_spacy` empty-NER on short questions (warning logged, whitespace fallback fired). Meaningful verdict signal needs chunkshop's `bakeoff-scotus-ab` / `bakeoff-ntsb-ab` corpora ingested + a real LLM judge endpoint.

**What this smoke proves vs. what it doesn't:**

- ✅ The four PRs compose at the API level
- ✅ `ABRunnerOutput` round-trips cleanly through writer + reader
- ✅ Verdict report artifacts (JSON + Markdown + latency) emit in the right shape
- ❌ Does NOT validate the verdict against a meaningful corpus (needs chunkshop corpora)
- ❌ Does NOT exercise the production `compute_verdict(runner_outputs)` path (NotImplementedError)
- ❌ Does NOT call an actual LLM judge (placeholder 50/50)

## Next steps to get the real verdict

1. Ingest chunkshop's `bakeoff-scotus-ab.yaml` and `bakeoff-ntsb-ab.yaml` into pg-raggraph namespaces.
2. Wire the production `compute_verdict(runner_outputs, judge_config)` path to call `llm_judge.engine.evaluate_cases` over the loaded `ABRunnerOutput` files. The seam (`_chunkshop_judge_config_to_llm_judge_provider`) is already in place from PR #52.
3. Run `pgrg ab-gate run` against both corpora with a real LLM key set.
4. Run `pgrg ab-gate verdict` (or wire the production path into the CLI) on the resulting output dir.
5. Flip chunkshop emission contract §4.1-§4.4 status checkboxes via a chunkshop PR.
6. Post the verdict back to chunkshop.

## Environment

- Python 3.13
- pg-raggraph 0.5.0a4 (post-merge HEAD `2faa252`)
- PostgreSQL 16 + pgvector + pg_trgm on `localhost:5434`
- `lede_spacy 0.4.5` + `en_core_web_sm 3.8.0`
- `llm-judge 0.1.0` from `git+https://github.com/yonk-labs/llm-judge.git`
- Test DB `pg_raggraph` (warm with pre-existing benchmark data; each bench drops its own namespace before+after)
