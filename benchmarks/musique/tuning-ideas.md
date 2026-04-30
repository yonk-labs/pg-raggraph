# MuSiQue tuning ideas — pick up later

Honest parking-lot for what's left to try on MuSiQue when we cycle back. Ordered by expected accuracy-per-effort. Most of these are *not* worth pausing real-world workstreams (CRM, dev-rel content, public release) for — but they're real wins if/when MuSiQue is the active concern.

## What we've actually run

| Configuration | Best F1 (any mode) | Notes |
|---|---|---|
| v1 (verbose answers, no rerank) | 4.4 % (hybrid) | Misleading — verbose-answer format mismatch |
| v2 (Step 1: `short_answer`) | **33.0 %** (hybrid) | Publishable; in BM25 territory |
| v3 (Step 2: `+ rerank` w/ bge-reranker-base) | 31.2 % (naive) | Best on naive modes; latency too high |
| v4 (Step 2b: `+ rerank` w/ MiniLM-L-6) | 30.8 % (smart) | Right shipping default |

## Things we haven't tried — ranked

### 1. Chunkshop-driven chunkers (✅ partially answered 2026-04-30)

Ran `chunkshop bakeoff` with 3 chunkers × 3 embedders = 9 combos against the 1700-paragraph MuSiQue corpus. Reproducer + full leaderboard: [`docs/cookbook/samples/chunkshop-bakeoff-musique.yaml`](../../docs/cookbook/samples/chunkshop-bakeoff-musique.yaml), [`benchmarks/musique/_logs/bakeoff/report.md`](_logs/bakeoff/report.md).

**Bakeoff winner on MuSiQue**: `hierarchy` chunker + `Xenova/bge-base-en-v1.5-int8` embedder, **MRR 0.433** (r@1=0.40, r@3=0.50, r@5=0.50). All three top spots are `hierarchy` — it's the right chunker for paragraph-shaped Wikipedia content. The embedder change adds ~+0.05 MRR over `bge-small`.

What this answers from the original idea list:
- ✅ `chunk_strategy="hierarchy"`: best chunker on MuSiQue per bakeoff. Adopt as default if we re-ingest MuSiQue.
- ⬜ Chunkshop strategies that produce micro-chunks (sentence_aware, fixed_overlap): tried; both lose to hierarchy on MuSiQue. fixed_overlap wins on the *sales-CRM* corpus though — confirms chunker choice depends on corpus shape.
- ⬜ Chunkshop strategy that merges related paragraphs into one doc: not yet tested. Would need a custom framer step. Captured as a future test if MuSiQue becomes the active concern again.

Bakeoff measures retrieval recall, not full Q&A. To get F1/EM lift estimates, re-ingest the existing MuSiQue corpus with `chunk_strategy="chunkshop:hierarchy"` and `embedding_model="Xenova/bge-base-en-v1.5-int8"`, then re-run `benchmarks/musique/run.py --short-answer --judge both`. Pre-built — just hasn't been run as part of this session because the LLM-extraction cost of full re-ingest is meaningful.

Expected MuSiQue F1 lift from the bakeoff winner combo: probably +1-3 pp over current short_answer numbers (33% F1 on hybrid). Compounds with rerank, PPR, etc. Captured for the "next time MuSiQue is active" pickup list.

### 2. Swap the embedder (the elephant)

`BAAI/bge-small-en-v1.5` (384-dim, 33 MB) is the default. NV-Embed-v2 (4096-dim) is current MTEB SOTA. Public benchmarks suggest the gap is ~5-10 F1 on multi-hop QA. **Every accuracy tactic we've shipped so far stacks with this — none replaces it.**

Pre-ingest decision branch from `docs/proposals/Accuracy-Improvements-Roadmap.md` (Phase A-prime).

| Candidate | Expected F1 lift on MuSiQue | Cost / pain |
|---|---|---|
| BAAI/bge-base-en-v1.5 (768) | +2-4 | small ingest re-run, free, fastembed-supported |
| BAAI/bge-large-en-v1.5 (1024) | +5-8 | medium re-run, free, fastembed |
| NV-Embed-v2 (4096) | +8-10 | needs separate inference server, 16 GB |
| OpenAI text-embedding-3-small | +4-6 | per-token cost, not airgap-safe |

Recommended next: **bge-large-en-v1.5**. Free, fastembed-native, biggest cheap step.

### 3. Step 3 — PPR over `relationships`

Captured in `docs/proposals/PropRAG-on-Postgres.md` Phase B. scipy CSR adjacency, two-stage damping (0.75 → 0.45), opt-in `local_ppr` mode. Estimated +3-5 pp on multi-hop questions, +30-50 ms p50 latency, no per-query LLM cost.

Effort: 1 week. Independent of all other tactics.

### 4. Step 5 + 6 — Propositions + PPR over proposition cliques

Same proposal, Phases A and C. Adds a `propositions` table + `proposition_entities` junction. PPR runs on the entity adjacency *induced by* `proposition_entities`. Expected +5-10 pp combined.

Effort: 2 weeks (1 for propositions, 1 for proposition-PPR).

### 5. Smart mode tunes (Step 4 from roadmap)

Encode the MuSiQue per-hop finding ("the right amount of graph is 'a little'") into the `smart` router. Today the router decides on retrieval-confidence. Add lightweight question-shape heuristics (count of "of" prepositions, named-entity count) to bias multi-hop-shaped questions toward `naive_boost` (1-hop) instead of `hybrid` (1-3 hop). Expected +1-3 pp on multi-hop, free.

Effort: 2-3 days.

### 6. Cross-encoder model tuning we haven't tried

We tested two reranker models: `bge-reranker-base` (1 GB) and `MiniLM-L-6-v2` (80 MB). Untried:

- `Xenova/ms-marco-MiniLM-L-12-v2` (120 MB) — middle ground; should be ~15-20% slower than L-6 but ~1-2 pp more accurate.
- `BAAI/bge-reranker-v2-m3` (~600 MB, multilingual) — newer than bge-reranker-base; might be faster per inference.
- `rerank_factor` sweep: we tested 4 (Step 2) and 2 (Step 2b). Try 3 and 6 to see the candidate-pool elbow.
- **Per-mode rerank flag.** Current `rerank=True` applies to every mode. Step 2/2b showed reranking *regresses* hybrid. A `rerank_modes={"naive", "naive_boost"}` config would let us rerank where it helps and skip it where it hurts.

Effort: 0.5 day per variant.

### 7. HyDE-style query expansion (`smart`-only)

LLM generates a hypothetical answer for low-confidence queries, embed *that*, search by the hypothetical's embedding. Already captured as a Tier 3 idea in `docs/proposals/Accuracy-Improvements-Roadmap.md` — opt-in only, never default, gated to `smart`-mode escalations.

Expected +5-10 pp on hard queries. Cost: 1 LLM call per low-confidence query (~$0.0003 + 500-2000 ms). Acceptable as a `smart`-mode last resort.

Effort: 1-2 days.

### 8. Multi-query retrieval with RRF fusion

LLM paraphrases the query N times, retrieve from each, reciprocal-rank-fuse the results. Standard recipe; +3-5 F1 typical.

Cost: N LLM calls per query. **Violates the no-added-LLM-cost-by-default rule** unless gated. Defer until #7 is shipped — both have the same opt-in pattern.

Effort: 2-3 days.

### 9. Per-question metadata routing

We have rich metadata on each MuSiQue question: `hop_class` (2hop/3hop/4hop), `gold_aliases`, `decomposition`. The benchmark runner currently treats every question identically. A test run that **routes by hop_class** — naive_boost for 2-hop, full hybrid for 3-hop, smart for 4-hop — would tell us the per-config ceiling more honestly than picking a single mode.

This is *benchmark-side* tuning, not pg-raggraph-side. But the finding ("which mode wins per hop") would inform the smart-router heuristics in #5.

Effort: 1 day.

### 10. Beam search over proposition paths (Phase D)

PropRAG's algorithmic detail beyond PPR. Expected marginal gain over Phase A+B+C. Captured as deferred.

## Things we found and *should* propagate elsewhere

These are real findings from the MuSiQue runs that should bias the rest of the project:

1. **The 4-hop asymmetry.** `naive_boost` (1-hop graph re-rank) wins on 4-hop questions; `hybrid` (1-3 hop) hurts. Already documented in [`results.md`](results.md). Implication for smart-mode tuning (item #5).
2. **Reranker regresses `hybrid`.** Same shape under both bge-reranker-base AND MiniLM-L-6. Implication for the per-mode rerank flag (item #6).
3. **Verbose-answer format mismatch is a real measurement gotcha.** 27% of EM=0 rows scored FULLY_CORRECT under judges. Solved with `short_answer=True`. Worth a brief in any future `gen-rag-blog` content — most public benchmark numbers are vulnerable to this.
4. **The embedder is the dominant lever.** Every step we ship stacks with it; none replaces it. Already plumbed into the documentation caveats; needs to remain prominent.

## What probably *doesn't* matter

- Sweeping similarity thresholds — at the bge-small ceiling we've already hit, sub-threshold tuning won't move the needle.
- Adding more questions (n>100) — error bars shrink but the per-mode ordering is already stable across runs.
- Trying proprietary embedders other than OpenAI — Anthropic, Cohere, Google bring marginal differentiation at higher cost than NV-Embed-v2 self-hosted.
- Re-doing the v1 (verbose-answer) baseline — we know why it was wrong; no need to re-prove.

## Pickup priority when MuSiQue is the active concern

1. **Try chunkshop strategies** (item #1) — biggest credibility gap; our own sibling library is unused on this corpus.
2. **Embedder swap** (item #2) — single biggest known accuracy lever.
3. **Per-mode rerank flag + L-12 model variant** (item #6) — small, surgical, lifts the Pareto frontier we already have.
4. **Step 3: PPR over relationships** (item #3) — big enough to justify, low risk, on the canonical PropRAG path.
5. Later: propositions, beam search, multi-query.

If the goal is dev-rel content rather than benchmark-leadership, items 1-2 alone produce a publishable update. Items 3-6 are the engineering case for shipping a v0.4.
