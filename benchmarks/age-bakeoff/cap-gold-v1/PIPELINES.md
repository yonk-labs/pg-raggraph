# Addendum 2 — pipeline latency

**Instrumentation of the preregistered cap-gold-v1 corpus. No new accuracy
claims.** Same corpus, same honesty rules as `RESULTS.md` (single machine —
Apple M5 Max, Docker; disclose everything; timeouts are results). Script:
`run_pipelines.py`; raw: `results/results_pipelines.json` (gitignored).

Protocol: Tier 1 uses the 149 exact-id Task B anchors (150 minus 1
merged-away entity), 1 warmup pass + 3 timed repeats = 447 samples/arm.
Tiers 2–3 use seed-42's 50 Task A issue-description questions ×3 repeats =
150 samples/arm; question embeddings precomputed OUTSIDE timed loops for
all bare-SQL arms, INSIDE for API arms. `statement_timeout = 30 s` both
engines; a timed-out warmup skips that item's repeats and is counted.
**Timeout count across every arm below: 0.** Vector seed stages in both
engines run at the shipped `hnsw.ef_search = 40` default (LIMIT 60 → 40
effective rows, symmetric). pgrg returns chunks, AGE returns cases — native
shapes, as in the main benchmark.

## Tier 1 — traversal depth sweep (engine-isolated, bare SQL, exact ids)

| arm | 1-hop p50/p95 | 2-hop p50/p95 | 3-hop p50/p95 | mean rows 1/2/3 | timeouts |
|---|---|---|---|---|---|
| pgrg_cte (shipped `traverse()` SQL) | 0.34 / 0.38 | 0.42 / 0.85 | 0.95 / 3.83 | 8.2 / 59.7 / 366.7 | 0 |
| pgrg_cte_min (engine floor) | 0.23 / 0.26 | 0.25 / 0.34 | 0.47 / 1.13 | 8.2 / 59.7 / 366.7 | 0 |
| age_cypher `[:REF*1..N]` | 33.69 / 39.41 | 52.44 / 105.61 | 132.14 / 670.49 | 8.2 / 59.6 / 367.4 | 0 |

Work parity: per-depth row counts match across engines to ±0.2% (per-path
semantics both sides; the CTE's cycle guard — the `path` array check — is
included in its numbers at every depth, and the shipped-vs-floor delta shows
its cost stays sub-millisecond even at 3 hops / ~367 paths).

**Reading Tier 1 honestly.** The recursive CTE is effectively flat across
depth (0.23→0.95 ms p50) while AGE's variable-length expansion grows
33.7→132 ms p50 with a heavy tail (p95 670 ms at 3 hops) — roughly 100–280×
at every depth, no timeouts on either side at 30 s. One AGE-side nuance this
sweep exposed: addendum 1 measured the *fixed-form* 1-hop pattern
(`-[:REF]->`) at 2.72 ms, while the depth sweep's *variable-length form*
(`[:REF*1..1]`) costs 33.7 ms for identical output — AGE's VLE machinery is
~12× more expensive than its fixed-hop form at the same depth. The CTE has
no such cliff; it is the same plan shape at every depth. This is consistent
with (and quantifies) the repo's "exponential path expansion" note about
AGE — though at this graph's fan-out (~6 edges/node), 3 hops stayed well
under the timeout.

## Tier 2 — realistic RAG pipeline (vector seed → entities → typed expansion → re-scored results)

Single statement per query in both engines; API arms shown for the wall
number users actually see.

| arm | p50 ms | p95 ms | rows | note |
|---|---|---|---|---|
| age_sql_1hop | 9.46 | 10.39 | 20 | seeds→edge-dump join→re-rank cases |
| pgrg_api_naive_boost | 37.02 | 46.37 | — | full API, embed inside loop |
| pgrg_sql_1hop | 44.37 | 60.51 | 20 | seeds→entity_chunks→hop→re-rank chunks |
| age_sql_2hop | 64.55 | 68.12 | 20 | second self-join of the edge dump |
| pgrg_sql_2hop | 78.33 | 95.92 | 20 | |
| pgrg_api_local | 263.51 | 488.41 | — | shipped 2-hop mode, full API |

**Reading Tier 2 honestly.** The AGE arm WINS the 1-hop realistic pipeline
(9.5 vs 44.4 ms p50), and the reason is unit economics, not traversal: its
whole pipeline re-ranks a few hundred case rows against an 11,548-row
table, while the pg-raggraph statement seeds over 43,651 chunk vectors and
its neighborhood step fans out through `entity_chunks` (~240K provenance
links, ~5.5 entities/chunk) to *thousands* of candidate chunks, each getting
an exact 384-dim distance in the re-rank. That chunk granularity is exactly
what won Task A recall in the main benchmark (R@20 0.129 vs 0.074) — Tier 2
prices it: ~35 ms per query at 1 hop. At 2 hops the AGE edge-dump join
narrows the gap to near-parity (64.6 vs 78.3 ms). Two more honest notes:
the shipped API `naive_boost` (37 ms, embedding included) beats our own
hand-written 1-hop pipeline SQL — its boost re-scores retrieved chunks
without fetching the whole neighborhood, a smarter shape than the naive
pipeline pattern; and `local` mode's 263 ms wall is the shipped heavy
2-hop pipeline, consistent with the main Task A table. An obvious cheaper
pgrg variant (re-rank at case level, or cap neighborhood chunks) was NOT
run — no post-hoc tuning; what's measured is the straightforward
translation of the pattern in each engine.

## Tier 3 — composed analytical slice ("authoritative, recent cases about X")

Semantic top-60 seed → 2-hop CITES expansion → citation-authority
(in-degree of the expanded set) → structured filter (decision year ≥ 1960)
→ RRF(60) of semantic + authority ranks → top 10 with provenance.

| arm | p50 ms | p95 ms | rows | statements/query | timeouts |
|---|---|---|---|---|---|
| age_sql_1stmt (edge-dump machinery) | 65.53 | 67.69 | 10 | 1 | 0 |
| pgrg_sql | 245.56 | 402.77 | 10 | 1 | 0 |
| age_sql_2stmt (targeted VLE variant) | 713.26 | 1174.67 | 10 | 2 | 0 |

**Reading Tier 3 honestly.** Both engines express the entire slice in ONE
statement — the single-database composability thesis holds on both sides of
this comparison (statements/query = 1). On latency the AGE edge-dump
version wins (65.5 vs 245.6 ms p50): pg-raggraph's cost center is again the
`entity_chunks` fan-out — re-ranking every chunk linked to a ~1K-entity
2-hop neighborhood with exact vector distances — while the AGE statement
ranks ~1K case rows. Notably, pgrg's *authority* step is the cheap part
(indexed targeted in-degree on `relationships(dst_id, rel_type)`), whereas
AGE has no targeted in-degree and must GROUP BY over the full 48,877-edge
dump — its win comes despite that. The "targeted" 2-statement AGE variant
(string-built `[:REF*1..2]` VLE from the seed ids, since `cypher()` cannot
consume dynamic seeds from a CTE — that is the composability limit the
statements column measures) is the *worst* arm at 713 ms p50: dumping and
joining all 48.9K edges relationally beats AGE's own traversal for
set-seeded expansion. API mapping: no single pg-raggraph API call expresses
this slice today — `graph_join` needs a named anchor (this starts from an
embedding), and `query()` exposes no citation-authority re-scoring knob;
nearest is `mode="local"` + `metadata_filters`, which omits the authority
leg. Recorded as an API gap, not benchmarked as an arm.

## Disclosures (beyond RESULTS.md's caveats, which all apply)

1. Tiers 2–3 compare each engine's **native unit** (chunks vs cases) doing
   the same conceptual job over identical raw text — same asymmetry as the
   main benchmark, opposite sign of effect (granularity costs latency here,
   where it bought recall there).
2. Tier 2/3 pgrg SQL uses fixed-depth SET expansion (UNION hop joins), not
   the per-path recursive CTE — the pipeline wants a neighborhood set;
   per-path costs are Tier 1's subject.
3. The pgrg seed stage scans a 43,651-vector HNSW index vs AGE's
   11,548-vector index (≈3.8× more vectors — its corpus shape).
4. `entity_chunks` links a known entity to every chunk of every document
   that declared it (provenance design), which is what makes pgrg
   neighborhoods chunk-heavy in Tiers 2–3.
5. All arms single-connection, warm; no concurrent load; one machine.
