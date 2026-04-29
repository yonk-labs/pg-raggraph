# Factorial Chunking × Embedding Experiment — Retrieval Root Cause

**Date:** 2026-04-19
**Purpose:** Identify why ~44% of required gold facts never appear in top-K retrieved chunks on the scotus bake-off corpus. The phase-2 mode sweep (naive / naive_boost / local / global / smart / hybrid) moved `fully_correct` by ≤ +3.3 pp on any cell, so the ceiling is upstream of ranking.
**Mission Brief anchor:** SC-002 (DC-003 threshold is +10 pp). Prior sweeps produced ≤ +3.3 pp. This experiment tests whether chunking / embedding changes can lift the retrieval coverage floor.
**Spend budget:** $0. Pure local vector-search + BM25. No LLM calls.
**Expected runtime:** ~45-60 minutes (3 chunking re-ingests × 3 embedding models = 9 local indexes).

## Status
- Plan written: 2026-04-19
- Probe questions selected: ✅
- Implementation: not started

## Hypotheses under test

| ID | Hypothesis |
|---|---|
| H1 | BGE-small (384-dim) is too weak for scotus legal vocabulary. BGE-base (768) and Nomic-embed (768, different family) surface more gold chunks. |
| H2 | Sentence-aware chunking cuts section-level context mid-idea. Overlapping or hierarchy-aware chunking preserves more. |
| H3 | Retrieval-time neighbor expansion (pull seq±1 same-doc chunks for every top-K hit) recovers facts that live in paragraphs adjacent to matched ones. |
| H4 | The ceiling is **not** chunking+embedding — it's entity-extraction coverage or gold-fact paraphrasing. If all 12 factorial cells show the same pattern, we need a different fix. |

## Design

### Chunking variants (4)

| ID | Strategy | Notes |
|---|---|---|
| A | Current (auto-detect, sentence-aware) | Baseline; no change to pg-raggraph |
| B | Fixed-size + 50% overlap | Preserves cross-boundary context |
| C | Hierarchy-aware (section → paragraph, with parent metadata) | Each chunk carries its section header as context |
| D | Current + retrieval-time neighbor expansion (±1 same-doc chunks) | **Reuses A's index** — retrieval-layer toggle only, no reindex |

### Embedding variants (3)

| ID | Model | Dim | Family |
|---|---|---|---|
| 1 | `BAAI/bge-small-en-v1.5` | 384 | BGE (current default) |
| 2 | `BAAI/bge-base-en-v1.5` | 768 | BGE (same family, scaled) |
| 3 | `nomic-ai/nomic-embed-text-v1.5` | 768 | Nomic (different family — catches cases where BGE has systemic blind spots) |

All three run locally via fastembed.

### Probe questions (4)

| # | QID | Class | Status in Phase 2 | Role |
|---|---|---|---|---|
| 1 | `scotus-q-018` | semantic | ✅ fully_correct (both engines) | Control — validates the test harness on a known-good case |
| 2 | `scotus-q-004` | factual | ⚠ partially_correct | Fact-list question ("legal issues in Bostock v. Clayton County") where some gold facts were recovered, others were not |
| 3 | `scotus-q-008` | single_hop | ⚠ partially_correct | Simple factoid ("justices who dissented in Apple v. Pepper") that still fails |
| 4 | `scotus-q-025` | multi_hop_bridging | ✗ wrong (both engines) | The thesis case — cross-case bridging ("justices who voted majority in Bostock AND dissented in Espinoza") |

### Cell matrix (4 × 3 = 12)

|  | E1 bge-small | E2 bge-base | E3 nomic |
|---|---|---|---|
| **A** current | A1 | A2 | A3 |
| **B** overlap | B1 | B2 | B3 |
| **C** hierarchy | C1 | C2 | C3 |
| **D** current + neighbor expand | D1 | D2 | D3 |

D reuses A's index → **real reindexes needed: 9** (3 chunkings × 3 embeddings).

### Per-cell measurements

For each (probe, cell) pair, report:

1. **Rank of first gold-containing chunk** in `ORDER BY chunks.embedding <=> query_vec` (lower is better; 1-N where N = total chunks).
2. **Top-10 hit / miss** — any gold fact's chunk in top-10?
3. **Top-50 hit / miss** — any gold fact's chunk in top-50?
4. **Per-fact recall @10** — fraction of the probe's `required_facts` whose chunk is in top-10.

Aggregate into a 12×4 matrix. Also aggregate "best cell per probe" and "best cell overall."

## Implementation outline

### Step 1: Shared scaffolding

- Script: `benchmarks/age-bakeoff/scripts/factorial-probe.py` (new)
- Reads `questions/scotus.yaml` to get the 4 probes + their `required_facts`.
- Reads raw scotus corpus from `corpora/scotus/input/*.md`.
- Provides: `chunk_corpus(strategy) -> list[Chunk]`, `embed_chunks(chunks, model) -> np.ndarray`, `search(chunks, embeddings, query, model, k, expand_neighbors=False) -> list[ChunkID]`.
- Writes output to `results/diagnostics/factorial-probe.json`.

### Step 2: Chunking strategies

- A: reuse `pg_raggraph.chunking.chunk_text()` as-is.
- B: simple `split-by-word, step = window // 2` implementation. Token count via `len(text.split())`, targeting 300-word windows with 150-word step.
- C: markdown-aware `split-by-header`; attach parent section title to each chunk's content before embedding.
- D: query-time only — after ranking, for each top-K chunk, also fetch `seq_num - 1` and `seq_num + 1` from the same `document_id`, merge, re-rank.

### Step 3: Embedding models

- Via `fastembed.TextEmbedding(model_name)` with a process-level cache per model. No pgvector reindex needed for the probe — we can hold all embeddings in memory (823 chunks × 1024 dim × 4 bytes ≈ 3 MB).
- Each chunking variant × embedding = one `np.ndarray` of shape `(n_chunks, dim)` + a list of chunk IDs.

### Step 4: Probe execution

- For each (chunking, embedding) cell: embed chunks once, embed the 4 probe questions once, compute cosine similarity, get full rank ordering.
- For each probe: find the lowest-rank chunk that contains any `required_fact` as substring (case-insensitive). Record rank + whether it's ≤10 and ≤50.
- D-variant: for probe × (A, e), take the rank list and re-expand via seq±1 from each top-50 before re-checking hit/miss.

### Step 5: Output

`results/diagnostics/factorial-probe.json`:

```json
{
  "probes": [...],
  "variants": [
    {
      "chunking": "A",
      "embedding": "bge-small",
      "n_chunks": 823,
      "embed_dim": 384,
      "per_probe": {
        "scotus-q-018": {
          "rank_of_first_gold_chunk": 3,
          "top10_hit": true,
          "top50_hit": true,
          "per_fact_recall_at_10": 1.0,
          "required_facts_matched": ["Rucho v. Common Cause", "partisan gerrymandering"],
          "required_facts_missed": ["political questions"]
        },
        ...
      }
    },
    ...
  ]
}
```

Plus a concise markdown report at `results/diagnostics/factorial-probe-REPORT.md`:
- 12-row table sorted by average rank across the 3 failing probes
- "Best cell per probe" summary
- Conclusion sentence (one of: "embedding change recovers N pp", "chunking change recovers N pp", "neither — move to entity extraction")

## Success criteria (acceptance for this experiment)

- Per-probe rank-of-first-gold computed for all 12 cells (48 observations).
- `factorial-probe-REPORT.md` contains the 12-row table.
- Conclusion identifies the next investigation target: (a) adopt the winning cell and rerun the full sweep, or (b) move to entity-extraction-coverage investigation if no cell lifts coverage meaningfully.

## Out of scope

- Re-running the full bake-off (`age-bakeoff run`) with the winning variant — that's a follow-up task if the probe finds a meaningful lift.
- Entity extraction changes — pure vector+BM25 probe only.
- Judge changes.
- AGE-side testing (AGE uses the same chunking; changes would apply symmetrically later).
- Community / subgraph-aware retrieval (queued for after we know chunking/embedding is not the bottleneck).

## Next step after this experiment

- If ≥1 cell lifts `required_facts_matched` on the 3 failing probes by ≥30% → adopt, rerun full bake-off sweep on scotus with that config, re-check DC-003.
- If no cell lifts meaningfully → the ceiling is entity extraction coverage or gold-fact mismatch. Design a second forensic drill: for each missed fact, confirm the fact literally appears in the corpus, then check whether an entity was extracted that represents it.
