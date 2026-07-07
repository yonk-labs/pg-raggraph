# CAP gold v1 — preregistered methodology

**Status: PREREGISTERED.** This file is committed BEFORE any retrieval run
is executed. Any deviation forced by evidence during the run is appended to
the "Deviations" section at the bottom with a reason — the sections above it
are never edited after the first results exist. Results go to `RESULTS.md`.

This benchmark extends `benchmarks/age-bakeoff/horizondb-h2h/` (410 cases,
N=1 gold question — read its README first). It replaces the retracted
private-corpus claims as the project's headline retrieval number, so the
rules are absolute: metric preregistered here, every arm reported including
losses, no post-hoc question pruning, all numbers labeled single-machine.

## 1. Corpus (public domain, reproducible from clone)

- **Source:** Caselaw Access Project static files, `https://static.case.law/`
  (Harvard LIL; published U.S. court opinions, public domain — CAP lifted all
  access restrictions March 2024).
- **Selection rule (deterministic, no cherry-picking):** reporter `wash-2d`
  (Washington Reports 2d, Washington Supreme Court), **volumes 1–120
  inclusive**, every case in each volume whose lead opinion
  (`casebody.opinions[0].text`) is non-empty. Contiguous-from-volume-1 was
  chosen (before any download) to maximize in-corpus citation closure —
  later cases cite earlier ones. Expected size ~10–14K cases (spot-checked
  volume counts range 39–331/volume); the exact count is recorded in
  `data/manifest.json` and in RESULTS.md, whatever it turns out to be.
- **Per-case text, identical for both arms:**
  `name + opinions[0].text[:8000]` — the exact embedding-input shape
  Microsoft's accelerator uses (`data#>>'{name}' || LEFT(opinion, 8000)`),
  carried over unchanged from the h2h.
- **Citation edges:** `cites_to[].case_ids` filtered to in-corpus ids,
  deduplicated, self-loops dropped. Same rule as the h2h / the accelerator's
  `create_edges_from_citations`.
- **Data hygiene:** volume zips and all derived data land in `data/`
  (gitignored). `data/manifest.json` records the volume list, per-volume
  sha256 of the downloaded zips, and corpus counts. Nothing bulky is
  committed; the corpus is rebuilt from clone by `download_corpus.py`.

## 2. Gold set — citation-derived, deterministic, no human/LLM labels

### 2.1 Why this design

Microsoft's gold set is N=1 question (the binding constraint of the h2h).
Hand-labeling a bigger set injects our judgment; LLM-labeling injects a
model's. Instead the gold is **constructed from the citation graph itself**:

> For a target case T, the question is built from T's own opinion text
> (a part of it that is NOT in the ingested corpus), and
> **gold(T) = {T} ∪ {direct in-corpus citations of T}**.

This measures a real legal-research task — "given a description of a legal
analysis, retrieve the case and the authorities it relies on" — and is
reproducible by anyone from the same public data and seed.

**Honest framing of what this metric assumes (headline caveat):** it
presumes a case's cited authorities are relevant to a description of that
case's analysis. That is the same assumption behind Microsoft's
`gold-graph` labels and behind citation-based relevance in legal IR
generally, but it is an assumption. This benchmark measures
**citation-neighborhood retrieval**, not general relevance. A gold set
defined partly by graph edges is structurally friendlier to graph-aware
arms; the design counters this by (a) reporting the vector-only arms on
exactly the same footing, (b) reporting `recall_cited` (gold minus the
target) separately so the graph contribution is visible rather than
laundered, and (c) reporting the target-hit diagnostic (§2.5).

### 2.2 Eligibility pool (fixed BEFORE sampling; no post-hoc pruning)

A case T is eligible as a question target iff:

- **E1.** ≥ 4 distinct in-corpus outbound citations (so |gold| ≥ 5 and
  recall@5 is meaningful).
- **E2.** lead opinion length ≥ 9,500 chars — the question excerpt is drawn
  from `opinion[8500:]`, i.e. **beyond the 8,000-char ingest cut**, so the
  question text has zero verbatim overlap with any ingested chunk. (This is
  the anti-teaching-to-the-test mechanism: the question describes the same
  legal analysis but no arm can string-match it.)
- **E3.** question construction (§2.3) succeeds and passes validity filters
  (§2.4).

The pool is computed over the whole corpus before any sampling; ineligible
cases are excluded by these rules only. Once sampled, no question is
dropped for scoring reasons.

### 2.3 Question construction (deterministic)

1. Excerpt: from `opinion[8500:]`, snap to the first full sentence
   boundary, then take whole sentences until ≥ 400 chars, hard cap 900.
2. Scrub, in order:
   - reporter citation strings (regex over Wn./Wash./P.2d/U.S./S.Ct./F./
     A.L.R./Am.Jur./C.J.S./L.Ed. + volume/page numbers) → ` [citation] `;
   - case captions (`… v. …` patterns, `In re …`, `State ex rel. …`) →
     ` [case] `;
   - `, supra` / `, infra` references; docket numbers;
   - the target's own party tokens (from its `name_abbreviation`, tokens
     > 3 chars) → `[party]`;
   - parenthetical fragments left dangling by the scrubs; whitespace
     collapse.
3. Template frame, rotated deterministically by `hash(case_id) % 5`, purely
   as phrasing (e.g. "Which Washington precedents govern this situation:
   {excerpt}"). Templates contain no case-identifying content.

The question NEVER contains the target's case id, caption, party names, or
official citation. Pilot inspection (3 examples from volume 100, before any
retrieval was run) drove the scrub list above; examples and known residual
leakage are documented in §7.

### 2.4 Validity filters (part of eligibility, applied pre-sampling)

- **V1.** post-scrub length ≥ 200 chars;
- **V2.** no token (> 3 chars) of the target's `name_abbreviation` survives
  in the question;
- **V3.** the excerpt window produced at least 2 complete sentences.

### 2.5 Known residual leakage (accepted, documented)

Party-name **fragments of cited authorities** can survive scrubbing (e.g.
"Farm Mut. Auto. Ins. Co." after the caption regex removes the "X v." part).
This leaks lexical signal that helps the **vector-only** arms find cited
gold — i.e. it biases AGAINST the graph arms' measured advantage. Accepted
as conservative. Diagnostic reported per arm: `target_hit@5` (how often the
target case itself is in the top 5) — if it is ≈1.0 for every arm while
`recall_cited` ≈ 0 for every arm, the task degenerated into self-lookup and
the design iterates (per §8, documented, not silently).

### 2.6 Sampling and seeds

- Seeds: **41, 42, 43** (fixed here, before any run).
- Per seed: `random.Random(seed).sample(sorted(pool), 50)` → 50 target
  cases → 50 questions. Sampling is over the deterministically ordered
  pool, so the question sets are reproducible from clone.
- Reported: per-arm mean across the 3 seeds ± min/max range (3 seeds is a
  range, not a confidence interval — labeled as such).

## 3. Tasks and arms

### Task A — issue-description retrieval (headline task)

Question: scrubbed excerpt (§2.3). Gold: `{T} ∪ cites(T)`; secondary gold:
`cites(T)` only (`recall_cited`).

pg-raggraph arms (pg-raggraph 0.8.0, PG16 + pgvector + pg_trgm on port
5434, database `pg_raggraph_capgold`, `PGRG_LLM_BASE_URL=""` — no LLM
anywhere):

| arm | call |
| --- | --- |
| `pgrg_naive` | `query(mode="naive", fusion="linear")` |
| `pgrg_naive_rrf` | `query(mode="naive", fusion="rrf")` |
| `pgrg_naive_boost` | `query(mode="naive_boost")` — the 1-hop graph boost, closest analog of Microsoft's Pattern 1 |
| `pgrg_local` | `query(mode="local")` |
| `pgrg_hybrid` | `query(mode="hybrid", fusion="linear")` |
| `pgrg_hybrid_rrf` | `query(mode="hybrid", fusion="rrf")` |

All pg-raggraph Task A queries: `top_k=200` chunks, `profile="raw"`,
chunk hits deduplicated to parent cases in rank order (case-level recall,
same unit as the AGE arm). 200 chunks ≈ 40–60 distinct cases at ~4–6
chunks/case; if any arm yields < 20 distinct cases for a question that is
recorded, not patched.

AGE arms (Apache AGE 1.5.0 + pgvector, PG16, the h2h container
`horizondb-h2h-age` on port 5440, new database `capgold_age`):

| arm | what |
| --- | --- |
| `age_vector_baseline` | h2h `sql/vector_baseline.sql` — Microsoft's Stage-1 vector query. **Adaptation: the `court_id = 9029` filter is dropped** — this corpus is single-court (wash-2d = WA Supreme Court), the filter is a no-op at best; documented here rather than silently kept. LIMIT 60. |
| `age_pattern1` | h2h `sql/pattern1_authority_boost.sql` — Microsoft HorizonDB doc Pattern 1 (vector top-60 CTE + `cypher()` citation-authority CTE + RRF), verbatim structure. Note: its authority signal is **global in-degree**, reranking the same 60 vector candidates — carried over unchanged. |

Excluded arms, with reasons (preregistered, not post-hoc):

- `pgrg_global` — built for LLM-generated community summaries; none exist
  in a no-LLM benchmark. The h2h measured it at 0.00 across the board for
  exactly this reason. Running it again adds noise, not information.
- `pgrg_smart` — a confidence router over the included modes; its recall is
  a mixture of theirs and its latency is bimodal. Out of scope for arm-level
  comparison.
- `accelerator_norerank` — the h2h ran it; on this corpus it adds nothing
  over pattern1 for the question "does the published pattern beat vector
  baseline", and its rerank stage can't be replicated locally anyway.

### Task B — citation lookup (the #95 / graph-primitive class)

The issue-description class has **no named anchor**, so the #95
`graph_join` API does not map to Task A — that is the honest answer to
"does a question class map to graph_join naturally?". The class that DOES
map is citation lookup:

Question: `"Which precedents does {name_abbreviation}, {official_cite}
({year}), rely on?"` — here the caption IS given, because the task is
lookup, not discovery. Gold: `cites(T)` only. **The anchor case itself is
removed from every arm's ranked list before scoring** (it is the question's
subject, not an answer).

Eligibility: Task A pool ∩ cases whose `name_abbreviation` is unique in the
corpus (anchor-resolution ambiguity excluded by rule — this task measures
traversal, not caption disambiguation; the exclusion count is reported).
Sampling: same rule and seeds as Task A, independent draw of 50 per seed.

| arm | what |
| --- | --- |
| `pgrg_naive` / `pgrg_naive_boost` | vector controls, same settings as Task A |
| `pgrg_typed_traverse` | `find_entities(caption)` → best match → `traverse([id], rel_types=["CITES"], direction="out", max_hops=1)` → cited case ids in returned order. This is the #95 primitive family. `graph_join` proper (bind + intersect) has no natural analog in a single-edge-type citation schema; noted as unbenchmarked. |
| `age_vector_baseline` / `age_pattern1` | same SQL as Task A |
| `age_cypher_traverse` | anchor id via `data#>>'{name_abbreviation}' =` caption, then `cypher('case_graph', MATCH (s:case {case_id: …})-[:REF]->(n) RETURN n.case_id)` |

Preregistered expectation, stated so a flattering result can't be
retro-fitted: the traversal arms should approach the ceiling set by
ingest-surviving edges (≈1.0), and the interesting numbers are (a) the
vector arms' gap on the same task and (b) traversal failure modes (anchor
resolution misses, entity merges). If traversal comes back ≈1.0 that is a
**task-structure result, not a model achievement** — it will be framed as
such.

## 4. Metrics (locked)

- **recall@k**, k ∈ {5, 10, 20}: `|top_k ∩ gold| / |gold|`, macro-averaged
  over the 50 questions of a seed; report mean ± min/max range over seeds
  41/42/43. Note |gold| may exceed k (recall@5 then caps < 1.0); the cap is
  identical across arms.
- **recall_cited@k** (Task A secondary): same, gold = citations only.
- **target_hit@5** (Task A diagnostic): fraction of questions whose target
  case is in the top 5.
- **Latency**: p50/p95 wall ms per arm over seed-42's 50 questions,
  1 warmup pass + 3 timed repeats each (150 timed samples/arm).
  - **Embeddings are computed INSIDE every arm's timed loop** — the timed
    unit everywhere is *question text in → ranked cases out*. (AGE arms:
    fastembed single-string embed + SQL execute + fetch; pg-raggraph:
    `GraphRAG.query()` wall, which embeds internally.) Same embedder
    everywhere: fastembed `BAAI/bge-small-en-v1.5`, 384-dim.
  - pg-raggraph latency is reported for **`profile="raw"`** (the number
    comparable to raw SQL — no context packing) and separately for
    **`profile="balanced"`** (labeled: includes the default profile's
    context-packing cost, per `benchmarks/regressions/query_latency_profile.py`).
    `QueryResult.latency_ms` (internal retrieval timer) is also reported.
  - Recall is computed from the `profile="raw"` runs; ranking equality
    raw-vs-balanced is asserted on 5 questions; if they differ, both are
    reported.
- **No LLM judge, no human grading** — set intersection on case ids only.

## 5. Ingest (no LLM anywhere)

pg-raggraph: `ingest_records` with `skip_llm=True` per record +
`skip_extraction=True` on the instance; one `case` entity per case;
citations as deterministic `CITES` known_relationships (mirrors the h2h).
Duplicate `name_abbreviation`s get an ` (id)` suffix on the entity name
(h2h convention). Known scale risk, preregistered handling: pg_trgm fuzzy
resolution may merge near-identical captions. The `entity_merge_log` count
is reported in RESULTS. The numeric-token version guard
(`entity_version_guard_pattern`) refuses merges between names differing
only by the id suffix. **Fallback rule:** if fuzzy merges exceed 1% of
entities, re-ingest with ALL entity names id-suffixed and report both merge
counts; otherwise ship as-is (shipped behavior, documented).

AGE arm: mirrors the h2h `load_age.py` — `cases_updated(id, data,
description_vector)` + HNSW index, AGE graph `case_graph` with one `:case`
node per case and bulk-inserted `REF` edges (Microsoft's own bulk-load
approach, including the stock-AGE `->> '"case_id"'::agtype` fix).

Ingest wall time for both arms is recorded and reported (this corpus is
also an ingest data point), but ingest speed is NOT a claim of this
benchmark.

## 6. Environment

- Single machine: Apple M5 Max, 128 GB RAM, macOS; both DBs in Docker.
  **Every number is single-machine and labeled as such.**
- pg-raggraph arm: `pg-raggraph` 0.8.0 (this commit), PG 16 + pgvector +
  pg_trgm (container `pg-raggraph-postgres-1`, port 5434), database
  `pg_raggraph_capgold`.
- AGE arm: container `horizondb-h2h-age` (AGE 1.5.0 + pgvector 0.8.0,
  PG 16.14, port 5440 — reused from the h2h; recreate via its
  `docker-compose.yml` if absent), database `capgold_age`.
- `uv sync --extra dev -p 3.12`; `PGRG_LLM_BASE_URL=""` forced in every
  script.
- Exact versions (PG, extensions, python packages) recorded in RESULTS.md.

## 7. Pre-registration pilot (what was looked at before this commit)

To fix the scrub rules, THREE example questions were generated from volume
100 and eyeballed (no retrieval, no database, no recall computed). Findings
that shaped §2.3–§2.5: caption regex misses multi-word corporate names
(hence the `supra`/parenthetical cleanup rules and §2.5's residual-leakage
note); duplicate captions occur even within one volume (hence the entity
suffix rule and Task B's uniqueness requirement); 64/81 vol-100 cases pass
the ≥9,500-char rule (pool will be ample). `head_matter` was evaluated as a
paraphrase source and **rejected**: CAP redacts publisher headnotes in this
reporter (copyright), leaving only caption + attorney lists — exactly the
fields the question must not contain.

## 8. Iteration policy

If the generated questions turn out degenerate (per §2.5's diagnostic, or
questions that are plainly garbage on inspection of seed-42's set BEFORE
recall is computed), the generator iterates and EVERY iteration is
documented in the Deviations section — including what the discarded variant
would have measured. No flattering-variant selection: the degeneracy
criteria are the ones written here, not post-hoc ones.

## 9. Outputs

- `data/` (gitignored): volume zips, `corpus.jsonl`, `manifest.json`,
  `gold_taskA_seed{41,42,43}.json`, `gold_taskB_seed{41,42,43}.json`.
- `results/` (gitignored): raw per-arm JSON.
- `RESULTS.md` (committed): full table — every arm, every metric, every
  seed's range, ingest wall times, entity-merge count, every caveat, and a
  from-clone reproduction section that has actually been executed.

## Deviations

(none yet — appended here if and when evidence forces a change)
