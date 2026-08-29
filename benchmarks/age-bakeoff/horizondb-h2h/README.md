# HorizonDB head-to-head: Microsoft's AGE GraphRAG pattern vs pg-raggraph

A reproducible, local comparison of Microsoft's published AGE-based
graph-augmented RAG pattern against pg-raggraph's recursive-CTE adjacency
graph — **on Microsoft's own corpus, question, and gold labels.**

Everything here is **single-seed, single-machine, preliminary**. See
`RESULTS-PRELIMINARY.md` for numbers and every caveat.

## What Microsoft published

- Doc: [Graph-Augmented RAG Patterns with Azure HorizonDB](https://learn.microsoft.com/en-us/azure/horizondb/ai/graph-rag)
  (ms.date 2026-06-02) — four SQL patterns composing `ag_catalog.cypher()`
  with pgvector in single statements; claims 40% recall (vector-only) → 70%
  (graph-augmented) on "the U.S. Case Law dataset (500K cases)".
- Accelerator: [Azure-Samples/graphrag-legalcases-postgres](https://github.com/Azure-Samples/graphrag-legalcases-postgres)
  (MIT) — the Legal Research Copilot behind that claim.

### What the accelerator actually ships (recon findings)

| Fact | Finding |
| --- | --- |
| Corpus in repo | `data/cases_final.csv` — **410 cases** (279 Washington Supreme Court, 131 WA Court of Appeals), with precomputed 1536-dim `text-embedding-3-small` vectors and `cites_to` citation metadata. The 500K figure refers to the full U.S. Case Law dataset; it is *not* shipped and no download script for it exists in-repo (their `Data_ingestion/` notebooks fetch from `https://static.case.law/`). |
| Data source / license | Caselaw Access Project (Harvard LIL, static.case.law): published U.S. court opinions — **public domain**; CAP lifted all remaining access restrictions in March 2024. Accelerator code is MIT. |
| Question set | Effectively **one** gold-labeled question: `"Water leaking into the apartment from the floor above."` `sample_qa_data/` holds saved GPT-4 answer JSONs for two variants of it, not a QA benchmark. |
| Gold labels | A hand-labeled 38-row `gold_dataset` table hard-coded in `setup_postgres_legal_seeddata.py` (labels: `gold`, `gold-graph`, `gold-semantic`, `gold-vector`, `orig*`, `maybe*`, `no`). 36 of 38 ids exist in the 410-case corpus. |
| Their recall math | **Not in the repo.** No script computes the published 40%/70%; the numbers are not reproducible from published assets. |
| Retrieval SQL | `get_vector_semantic_graphrag_optimized` (plpgsql): pgvector CTE (top-60, court filter) → `azure_ml.invoke()` cross-encoder rerank → `ag_catalog.cypher()` citation edge dump joined relationally, weighted by ref-embedding cosine → RRF(60/60). |

Worth noting honestly in both directions: their `cypher()` stage is a **full
edge-list enumeration** (`MATCH (s)-[r:REF]->(n) RETURN ...` with no property
filter or variable-length path) — the actual traversal logic lives in plain
SQL joins around it. The composability is real; the Cypher is doing very
little of the graph work.

## The AAT-002 fact

Our repo claims (CLAUDE.md, research/apache-age-evaluation.md) that "AGE
Cypher and pgvector cannot combine in a single query." **That claim is
falsified by this harness**: `run_age.py` executes Microsoft's exact
composition — an `ag_catalog.cypher(...) AS (case_id TEXT, ref_id TEXT)` CTE
joined with a pgvector `<=>`-ordered CTE in ONE statement — on stock Apache
AGE 1.5.0 + pgvector 0.8.0 (PG16), and it runs and joins correctly. See
`composability_probe` in `data/results_age.json`.

One portability wrinkle found on the way: their *seed* SQL
(`properties ->> 'case_id'`) errors on stock AGE 1.5.0
(`Expected agtype value`) and needs `->> '"case_id"'::agtype`; their managed
Azure AGE build evidently accepts the plain-text form. Recorded in
`load_age.py`.

## Design

### Corpus — no slicing, by construction

We use the **entire 410-case corpus Microsoft ships**, because that is the
corpus their gold labels are defined against. No slice selection = no
slice-selection bias to defend. (The original plan was to carve a 5-20K-case
slice from the 500K corpus; that corpus isn't shipped, and inventing gold
labels for a bigger slice would be our labels, not theirs.)

Both arms get **identical raw text** per case: `name + opinion[:8000]` —
exactly the input Microsoft's embedding stage uses
(`data#>>'{name}' || LEFT(opinion, 8000)` in `Data_ingestion/embedding.sql`).

### Identical embedder, both arms

fastembed `BAAI/bge-small-en-v1.5` (384-dim), pg-raggraph's default local
embedder. No OpenAI dependency, identical vectors given identical text.
(Microsoft used `text-embedding-3-small`, 1536-dim — an absolute-recall
caveat, but symmetric between arms.)

### Arms

AGE arm (docker `horizondb-h2h-age`, port 5440, AGE 1.5.0 + pgvector 0.8.0):

| Arm | What it is |
| --- | --- |
| `vector_baseline` | Their Stage-1 vector query verbatim (incl. court-9029 filter) — their "40 percent" reference. |
| `pattern1` | HorizonDB doc **Pattern 1: Authority boosting** (vector CTE + cypher citation CTE + RRF), verbatim structure; see header of `sql/pattern1_authority_boost.sql` for the mechanical adaptations. |
| `accelerator_norerank` | Their production function as one statement, with the `azure_ml` rerank stage removed (identity rerank) — see `sql/accelerator_graphrag_norerank.sql`. |

pg-raggraph arm (dev PG 16 + pgvector on port 5434, database
`pg_raggraph_h2h`): each case ingested via `ingest_records` with
`skip_llm=True`, one `case` entity per case (19 duplicate case names
disambiguated with an `(id)` suffix), citations as deterministic
`CITES` known_relationships — mirroring their citation graph without any LLM.
Modes: `naive` (vector-only control), `naive_boost`, `local`, `global`,
`hybrid`. Chunk hits are deduped to parent cases in rank order so recall is
case-level in both arms.

### Grading

`recall@k` (k ∈ 5, 10, 20, 30, 60) against two gold sets derived from their
labels: `gold_strict` (labels starting `gold`, n=20 in corpus) and
`gold_plus` (adds `orig*`/`maybe*`, n=26). Their own strict/plus split isn't
published, so we report both. Grading is deterministic (set intersection on
case ids) — no LLM judge.

Latency: gold question (3 warmups, 15 timed repeats) plus 15 same-style
legal questions (`questions.yaml`, 1 warmup + 5 repeats each, latency only —
no gold labels exist for them). p50/p95 reported.

## Asymmetries and honesty notes (read before quoting numbers)

1. **N=1 gold-labeled question.** That is all Microsoft published. Every
   recall number is one question on 410 documents. Directional at best.
2. **Reranker skipped in both arms.** Their full pipeline uses an
   `azure_ai`/`azure_ml` cross-encoder stage that doesn't exist locally.
   Symmetric skip, but the AGE arm here is NOT Microsoft's full pipeline —
   don't compare these numbers to their published 70%.
3. **Different embedder than theirs** (bge-small 384-dim vs
   text-embedding-3-small 1536-dim). Symmetric across arms, not comparable to
   their absolute numbers.
4. **Retrieval granularity differs by design.** AGE arm: one embedding per
   case (their shape). pg-raggraph: ~4 chunks per case (its shape). Same raw
   text; each system runs its intended design.
5. **Latency measurement**: AGE arm times raw SQL client-side, with the
   question embeddings precomputed *outside* the timed loop; pg-raggraph
   times `GraphRAG.query()` wall time, which includes computing the query
   embedding per call (~2 ms warm — inside its internal timer too) and,
   dominantly, packing answer context for the default `"balanced"` retrieval
   profile: LLM-free lede summarization of the top-10 retrieved documents,
   profiled at ~105 ms of the ~120 ms wall-vs-internal gap on this corpus
   (`benchmarks/regressions/query_latency_profile.py`). Use
   `QueryResult.latency_ms` ("int" in RESULTS) as the number comparable to
   the AGE arm's SQL wall; a `profile="raw"` query (classic chunk context,
   no packing) walls at ~24 ms on this corpus. As reported, this favors the
   AGE arm.
6. **410 cases is tiny.** Latency differences at this scale say nothing
   about 500K-case behavior — no HNSW pressure, no planner stress, whole
   dataset fits in cache.
7. **pg-raggraph entity resolution merged 3 case entities** (407 entities /
   1043 CITES edges vs 410/1048 in the AGE graph) — its pg_trgm fuzzy dedup
   treats near-identical disambiguated names as one entity. Left as-is: it's
   the system behaving as shipped.
8. Their published corpus row for court filter: the accelerator's function
   filters `court_id = 9029` (all 26 in-corpus gold cases are court 9029, so
   the filter doesn't exclude gold; kept verbatim).

## Reproduce

```bash
# 0. deps (from repo root): uv sync --extra dev -p 3.12
# 1. clone Microsoft's accelerator anywhere OUTSIDE the repo
git clone https://github.com/Azure-Samples/graphrag-legalcases-postgres /tmp/glp

# 2. build corpus + gold + embeddings (writes ./data/, gitignored)
uv run --no-sync python benchmarks/age-bakeoff/horizondb-h2h/prepare_corpus.py \
    --accelerator-repo /tmp/glp

# 3. AGE arm (port 5440)
docker compose -f benchmarks/age-bakeoff/horizondb-h2h/docker-compose.yml up -d
uv run --no-sync python benchmarks/age-bakeoff/horizondb-h2h/load_age.py
uv run --no-sync python benchmarks/age-bakeoff/horizondb-h2h/run_age.py

# 4. pg-raggraph arm (dev PG on 5434; creates database pg_raggraph_h2h)
uv run --no-sync python benchmarks/age-bakeoff/horizondb-h2h/load_pgrg.py
uv run --no-sync python benchmarks/age-bakeoff/horizondb-h2h/run_pgrg.py
```

Raw per-arm outputs land in `data/results_age.json` / `data/results_pgrg.json`
(gitignored; numbers are transcribed with provenance into
`RESULTS-PRELIMINARY.md`). No large data files are committed — scripts +
manifests only, matching age-bakeoff conventions.

## What a publishable run would need

- A real question set with gold labels (tens to hundreds of questions), not
  their single demo question — e.g. hand-labeling against a larger CAP slice,
  or an independent legal-retrieval benchmark.
- The full (or a large sampled) CAP corpus from static.case.law, so latency
  and recall are measured under realistic index pressure.
- Their reranker stage replicated locally (any cross-encoder) so the full
  published pipeline is represented.
- Multiple seeds/orderings, confidence intervals, and a second machine.
