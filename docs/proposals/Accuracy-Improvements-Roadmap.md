# Proposal: Accuracy Improvements Roadmap

> **Status:** Draft (2026-04-29). Index of accuracy-improvement ideas + a step-by-step execution plan ranked by **accuracy-per-cost** under a hard constraint: **no substantial sacrifice in latency or per-query cost**. Some ideas in the inventory deliberately don't make the plan because they violate that constraint; they're documented anyway so future work can re-evaluate.

## TL;DR

Six ranked steps. Each ships independently and validates on the existing MuSiQue + NTSB + PG-docs benchmarks before the next starts. Total expected lift: from the current ~46.7 % LLM-judge / ~60 % support-recall on MuSiQue toward the ~50-54 zone (HippoRAG 2 / PropRAG territory). Total added p50 latency: ~100-150 ms. Zero added per-query LLM cost (everything new is CPU-only or ingest-time).

The plan in one line:

```
1. short_answer mode  →  2. cross-encoder reranker  →  3. PPR (Phase B)
                                ↓
4. smart routing tunes  →  5. propositions (Phase A)  →  6. PPR over propositions (Phase C)
```

Steps 1, 2, 3, 4 are the **performance-respecting accuracy core** (no schema change, no extra LLM at query time). Steps 5 and 6 are the **PropRAG roadmap** carried over from `docs/proposals/PropRAG-on-Postgres.md`.

## The constraint

We're optimizing **accuracy per (latency, cost)**, not raw accuracy. Specifically:

- **Per-query LLM cost: must not increase.** Today retrieval makes zero LLM calls; only `rag.ask()` does (one call for answer generation). Any idea that requires an LLM call at retrieval time is automatically Tier 3 — opt-in only, gated behind `smart` mode for hard questions, never default.
- **Per-query latency: ≤ +200 ms p50 over current.** Current `smart` is 2.8 s p50 on MuSiQue. Hard ceiling is ~3 s p50. CPU-only re-rankers and scipy linear algebra fit; LLM-in-the-loop retrieval doesn't.
- **Ingest cost: one-time, can grow modestly.** A second LLM call per chunk during ingest is acceptable if it produces a durable artifact (e.g., propositions). Multiple LLM calls per chunk during *every* query is not.
- **Storage: can grow modestly.** New tables OK. Materializing every clique as edges is not.

## Inventory of ideas (all of them)

Indexed across all session docs + items not yet captured anywhere. Each item: source, axis (what it changes), and cost profile.

### Already captured

| # | Idea | Source | Axis |
|---|---|---|---|
| I-01 | Propositions as a new extraction artifact | [PropRAG proposal](PropRAG-on-Postgres.md) Phase A | extraction + retrieval target |
| I-02 | Personalized PageRank over `relationships` | [PropRAG proposal](PropRAG-on-Postgres.md) Phase B | re-ranking |
| I-03 | PPR over proposition cliques | [PropRAG proposal](PropRAG-on-Postgres.md) Phase C | re-ranking |
| I-04 | Two-stage PPR damping (0.75 → 0.45) | [PropRAG proposal](PropRAG-on-Postgres.md) Phase B/C | re-ranking |
| I-05 | Beam search over proposition paths | [PropRAG proposal](PropRAG-on-Postgres.md) Phase D — *deferred* | re-ranking |
| I-06 | Embedder swap (bge-small → bge-large or NV-Embed-v2) | [PropRAG proposal](PropRAG-on-Postgres.md) Phase A-prime | embedding |
| I-07 | `short_answer=True` mode for `rag.ask()` | [MuSiQue results](../../benchmarks/musique/results.md) | answer-generation |
| I-08 | Single-merged vs split extraction prompts | [PropRAG proposal](PropRAG-on-Postgres.md) Phase A | extraction |
| I-09 | Per-corpus extraction prompts | [PropRAG proposal](PropRAG-on-Postgres.md) R5 | extraction |
| I-10 | Tier 1 evolution awareness for propositions | [PropRAG proposal](PropRAG-on-Postgres.md) Q4 | schema |

### Not yet captured anywhere (raised in conversation)

| # | Idea | Axis |
|---|---|---|
| I-11 | Cross-encoder reranking (`bge-reranker-base` or similar, CPU) | re-ranking |
| I-12 | HyDE-style query expansion (LLM generates hypothetical answer, embed it) | query rewriting |
| I-13 | Entity-anchored query rewriting (no LLM — graph-driven alias expansion) | query rewriting |
| I-14 | Multi-query retrieval with RRF fusion | query rewriting |
| I-15 | `smart` mode routing tunes (question-shape detection for multi-hop) | routing |
| I-16 | Better answer prompts in `rag.ask()` independent of `short_answer` | answer-generation |

## Cost-tier ranking

Filter every idea against the constraint. Rank by accuracy-per-cost.

### Tier 1 — pure wins (no per-query cost, ≤ +100 ms p50)

| # | Idea | Expected lift | Latency hit | Notes |
|---|---|---|---|---|
| I-07 | `short_answer` mode | unlocks publishable F1 (~+25 EM points by removing format mismatch) | 0 ms | Prompt change only. Doesn't change correctness — fixes measurement. |
| I-15 | Smart routing tunes | +3-5 pp on multi-hop | 0 ms | Existing router, smarter heuristics. MuSiQue finding: avoid `hybrid` on 4-hop, prefer `naive_boost`. |
| I-13 | Entity-anchored query rewriting (no LLM) | +2-4 pp | <5 ms | One SQL pull from `entities` for known aliases; expand query string. |
| I-09 | Per-corpus extraction prompts | +3-7 pp on domain corpora | 0 ms (config) | Tunes ingest, not query. |
| I-11 | Cross-encoder reranker (`bge-reranker-base`) | +3-7 pp | +50-80 ms | CPU-only via fastembed/onnx. Well-documented technique. |
| I-02 | PPR over `relationships` (Phase B) | +3-5 pp on multi-hop | +30-50 ms | scipy sparse matvec. No LLM. |
| I-04 | Two-stage PPR damping | +1-2 pp on top of I-02 | minimal | Implementation detail of I-02. |
| I-16 | Better answer prompts | +2-4 pp on judge scores | 0 ms | Tunes existing LLM call. |

### Tier 2 — ingest-cost only (one-time, durable artifact)

| # | Idea | Expected lift | Ingest cost | Query cost |
|---|---|---|---|---|
| I-01 | Propositions (Phase A) | +3-5 pp standalone, +5-10 pp with PPR | +1 LLM call per chunk | 0 |
| I-03 | PPR over proposition cliques (Phase C) | +5-8 pp combined | depends on I-01 | +30-50 ms |
| I-08 | Single-merged extraction prompt | reduces ingest cost vs split | -50% LLM calls vs split | 0 |
| I-10 | Tier 1 awareness for propositions | unlocks evolution-aware multi-hop | minor schema growth | 0 |

### Tier 3 — per-query LLM cost (opt-in, never default)

| # | Idea | Expected lift | Per-query cost |
|---|---|---|---|
| I-12 | HyDE | +5-10 pp on hard questions | 1 extra LLM call (~$0.0003 + 500 ms) |
| I-14 | Multi-query retrieval | +3-5 pp | N extra LLM calls (~N × $0.0003 + N × 500 ms) |

These violate the constraint as defaults. Acceptable as `smart`-mode escalations *only* — only fire if confidence is below a threshold. Defer until Tier 1+2 are exhausted.

### Tier 4 — uncertain or contingent

| # | Idea | Why not now |
|---|---|---|
| I-06 | Embedder swap | bge-large is ~3-5× slower CPU inference. Only do if Tier 1+2 confirm embedder is the bottleneck (current MuSiQue support recall 60% vs field's 70-77% suggests it might be). |
| I-05 | Beam search (Phase D) | High implementation complexity. Only if Tier 1+2+3 leave us short of ~50 F1. |

## The step-by-step plan

Six steps. Each has an explicit measurement and a definition of done. Stop after any step if MuSiQue lands at a target the user accepts.

### Step 1 — `short_answer` mode (1-2 days)

**Goal:** Make EM/F1 publishable by removing the verbose-answer format mismatch.

**Tasks:**
- Add `short_answer: bool = False` parameter to `rag.ask()`.
- When True, set the LLM prompt to: "Answer in ≤10 tokens. Factoid only. No explanation."
- Add `--short-answer` flag to `pgrg ask` and the MuSiQue runner.
- Re-run MuSiQue with `--short-answer --judge both`.

**Definition of done:**
- MuSiQue EM jumps from 0% to >25% on at least one mode (BM25 baseline territory).
- F1 jumps from ~4% to >30%.
- LLM-judge scores within ±3 pp of current run (i.e., we didn't break correctness).

**Cost:** zero (prompt change only).

### Step 2 — Cross-encoder reranker (3-5 days)

**Goal:** +3-7 pp on retrieval-dependent metrics across all corpora. Single highest-ROI Tier 1 idea after Step 1.

**Tasks:**
- Add `bge-reranker-base` via fastembed or onnxruntime (CPU, ~50ms for 10 pairs).
- New optional config: `rerank_model: str | None = None` and `rerank_top_k: int = 5`.
- After existing top-k retrieval, score each chunk against the question with the cross-encoder and re-rank.
- New retrieval mode `naive_rerank` (or just enable with `rerank=True` flag).
- Measure on MuSiQue, NTSB, PG-docs, pg-agents corpora.

**Definition of done:**
- p50 latency increase ≤ 80 ms.
- LLM-judge accuracy on MuSiQue smart mode goes from ~46.7% to ≥50%.
- No regression on NTSB or PG-docs.

**Cost:** zero per-query LLM cost. CPU-only.

### Step 3 — PPR over `relationships` (1 week, Phase B from PropRAG proposal)

**Goal:** Replace `naive_boost`'s 1-hop graph re-rank with a principled global score. +3-5 pp on multi-hop questions.

**Tasks:**
- scipy CSR adjacency cache per namespace, invalidated on `ingest`/`delete`.
- `_ppr_score()` core loop in `retrieval.py`.
- New retrieval mode `local_ppr` (or augment existing `local`/`naive_boost` with a flag).
- Two-stage damping variant.
- Re-run MuSiQue.

**Definition of done:**
- p50 latency increase ≤ 50 ms.
- MuSiQue 4-hop accuracy ≥ +3 pp over `naive_boost` (current best on 4-hop).
- No regression on 2-hop where `hybrid` currently wins.

**Cost:** zero per-query LLM cost. scipy CPU-only.

### Step 4 — Smart routing tunes (✅ partially shipped 2026-04-30)

**Goal:** Encode question-shape signals into the `smart` router so it reaches modes (`global`, `hybrid`) it previously couldn't.

**Shipped — aggregation/synthesis pre-check (`src/pg_raggraph/retrieval.py:_question_shape`):**

The CRM `compare_modes.py` run on 2026-04-30 surfaced a real router gap. The original `smart` only routed between `naive → naive_boost → local` based on naive's confidence. **It never picked `global` or `hybrid`** — even when those were clearly the right answer. On aggregation-shaped questions ("most common", "across all"), `global` scored 3/3 while `smart` (without shape detection) only matched on 3/5.

Fix: cheap lexical pre-check classifies the question as **aggregation**, **synthesis**, or **lookup** before naive runs.

- aggregation cues ("most often", "most common", "how many", "across all", "patterns", "trends", "in total", "every customer/deal/product/account") → `mode="global"`
- synthesis cues ("compare", "contrast", "alongside", "common themes/threads/reasons") → `mode="hybrid"`
- lookup (default) → falls through to existing confidence-based routing (naive → boost → local)

Validation on the CRM 5-question set:

| Configuration | smart avg score | smart wins | smart avg latency |
|---|---|---|---|
| Pre-fix | 2.60 | 3/5 | 3,417 ms |
| **Post-fix** | **3.00** | **5/5** ⭐ | **2,931 ms** |

Smart now matches `global` (which also went 5/5 at 3,359 ms avg latency) at *lower* average latency. Effective modes routed correctly: Q1/Q4/Q5 → `smart[global]`, Q3 → `smart[hybrid]`, Q2 (the only true lookup) → `smart[boosted]`.

**Still open — MuSiQue multi-hop heuristic:**

The shape pre-check covers aggregation/synthesis. The MuSiQue 4-hop finding ("the right amount of graph is 'a little'") needs separate handling: detect chained-entity questions ("X of the Y of Z") and bias toward `naive_boost` over full `hybrid`. Captured in [`benchmarks/musique/tuning-ideas.md`](../../benchmarks/musique/tuning-ideas.md) item #5.

**Definition of done:**
- ✅ CRM aggregation/synthesis questions auto-route correctly (`smart` ties `global` at 5/5 wins).
- ⬜ MuSiQue chained-entity questions route to `naive_boost` instead of full `hybrid`.

**Cost:** zero. Routing math, no LLM call, no DB round-trip added.

### Step 5 — Propositions (1 week, Phase A from PropRAG proposal)

**Goal:** Add context-rich propositions as a new retrieval target. +3-5 pp standalone; bigger when combined with PPR in Step 6.

**Tasks per existing PropRAG-on-Postgres proposal Phase A.** Schema migration `005_propositions.sql`, extraction-prompt addition, resolution path, new retrieval mode `prop`.

**Definition of done:**
- 1700 MuSiQue paragraphs ingested with propositions (one-time).
- `prop` mode F1 ≥ baseline + 3 pp.
- No regression on existing modes.

**Cost:** +1 LLM call per chunk at ingest (one-time). Zero per-query LLM cost.

### Step 6 — PPR over proposition cliques (1 week, Phase C from PropRAG proposal)

**Goal:** Combine Step 3 + Step 5. PPR adjacency derived from `proposition_entities` cliques. +5-10 pp combined lift.

**Tasks per existing PropRAG-on-Postgres proposal Phase C.** New mode `prop_ppr` using proposition-derived adjacency. Two-stage damping enabled by default.

**Definition of done:**
- MuSiQue ≥ 50 F1 (target) / ≥ 52 F1 (stretch) under `short_answer` mode from Step 1.
- p50 latency ≤ 3.0 s.
- `prop_ppr` becomes recommended mode for multi-hop in user-guide.

**Cost:** zero per-query LLM cost (depends on Step 5's ingest cost).

## Decision branches

After Step 3, evaluate the embedder hypothesis:

- **If support recall hasn't moved much (~60-65%)** → I-06 (embedder swap) becomes Step 3.5. We're hitting the embedder ceiling, not a graph-mechanics ceiling.
- **If support recall jumped to 70-75%** → no embedder swap needed; continue to Step 4.

After Step 6, decide if Tier 3/4 is worth it:

- **If MuSiQue ≥ 50 F1** → ship and write the blog post. Done.
- **If 45-50 F1** → consider I-12 (HyDE) as a `smart`-mode escalation for hard questions only. Or I-14 (multi-query) as an opt-in mode.
- **If still < 45 F1** → embedder is almost certainly the cap (return to I-06) before contemplating I-05 (beam search).

## What we deliberately don't do (at all, or not yet)

| # | Idea | Why not |
|---|---|---|
| I-12 | HyDE as default | Adds 1 LLM call per query — violates cost constraint as default. Acceptable only as `smart`-mode escalation later. |
| I-14 | Multi-query retrieval as default | N× LLM calls per query — violates cost constraint. Same logic as I-12. |
| I-05 | Beam search (Phase D) | High complexity, marginal lift over PPR alone per the PropRAG paper itself. Defer until Steps 1-6 measured. |
| — | Replace pgvector with another backend | Not on the table. The whole thesis is "pgvector is enough." |
| — | Add Apache AGE / Neo4j | Same. Confirmed unnecessary by every benchmark we have. |
| — | Replace bge-small with a 7B-param embedder served via API | Cost violation. Local fastembed is the floor. |
| — | Build a fine-tuned domain reranker | Premature. Off-the-shelf bge-reranker-base first. |

## Tracking

This roadmap is the index. Substance for each step lives in:

- **PropRAG mechanics (Steps 5, 6, decision-branch I-05 and I-06):** [`PropRAG-on-Postgres.md`](PropRAG-on-Postgres.md)
- **MuSiQue findings driving Steps 1, 4:** [`benchmarks/musique/results.md`](../../benchmarks/musique/results.md)
- **Cross-corpus calibration:** [`benchmarks/FINAL_RESULTS.md`](../../benchmarks/FINAL_RESULTS.md)
- **Active-work entry:** [`TODO.md`](../../TODO.md) (P1 entries)

Open the issue tracker (or add P1 entries to TODO.md) when starting each step. Validate on at least MuSiQue + NTSB + PG-docs before merging — those three corpora cover the three corpus shapes (multi-hop, self-contained, dense-graph) and a regression in any of them gates the next step.
