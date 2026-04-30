# MuSiQue benchmark — results (2026-04-29)

> ⚠️ **All numbers below are bounded by `BAAI/bge-small-en-v1.5` (384-dim).** Our retrieval ceiling on MuSiQue is heavily embedder-dependent. NV-Embed-v2 (4096-dim) tops the public MuSiQue table at 44.8 F1 vector-only — bge-small lands meaningfully lower. **None of the multi-step accuracy improvements in this file (short_answer, rerank, smart routing, propositions, PPR) substitute for a stronger embedder.** They stack with one — they don't replace it. See `embedding_model` in [`docs/Config-Reference.md`](../../docs/Config-Reference.md).
>
> **Update — late session 2026-04-29.** Steps 1 and 2 from `docs/proposals/Accuracy-Improvements-Roadmap.md` shipped and were re-validated. The original v1 numbers below are kept for the v0 narrative; **the v2 (`short_answer`) and v3 (`short_answer + rerank`) sections at the end are the canonical results for current `main`.**

## v1 — Original run (2026-04-29 14:51)

EM and F1 below are **not directly comparable** to the published MuSiQue table. Our `rag.ask()` produced verbose generative answers; MuSiQue's gold answers are short factual strings. **27% of all (question, mode) pairs scored EM=0 but received FULLY_CORRECT (3/3) from both LLM judges.** Step 1 fixed this — see v2 section.

## Configuration

- **Dataset:** MuSiQue-Ans dev split (Trivedi et al. 2022), N = 100 stratified questions (33 / 33 / 34 across 2-hop / 3-hop / 4-hop). Seed `20260429`.
- **Pool corpus:** 1,700 unique paragraphs, dedup'd by `(title, paragraph_text)` from the supporting + distractor sets of all 100 sampled questions. Single namespace `bench_musique`.
- **Ingest:** 121 min wall clock end-to-end. Resulting graph: 1,706 chunks, 9,155 entities, 10,078 relationships (~5.4 entities/doc, ~5.9 rels/doc).
- **Modes tested:** `naive`, `naive_boost`, `hybrid`, `smart`.
- **Answer model:** local vLLM Qwen3-Coder-Next-int4-AutoRound at `192.168.1.193:8000`.
- **Judges:** local Qwen (free), OpenAI gpt-4o-mini (~$0.30 total).
- **Total runtime:** 64.8 min for 400 `rag.ask()` calls + 800 judge calls.
- **Failures:** 0 (one transient `Answer generation failed` warning was caught and scored 0).

Everything reproducible via `benchmarks/musique/{prepare,ingest,run}.py`. Raw rows at `benchmarks/musique/_results/results-20260429-145103.json`.

## Headline numbers (by mode)

| Mode | EM | F1 | Support recall | Qwen judge | OpenAI judge | p50 latency | p95 latency |
|---|---|---|---|---|---|---|---|
| naive | 0.0 % | 4.1 % | 59.3 % | 35.7 % | 39.3 % | 3,229 ms | 8,059 ms |
| naive_boost | 0.0 % | 3.8 % | 59.3 % | 39.7 % | 42.3 % | 2,912 ms | 9,586 ms |
| hybrid | 0.0 % | 4.4 % | 59.8 % | 39.7 % | 40.7 % | 3,084 ms | 9,095 ms |
| **smart** | 0.0 % | 4.0 % | 58.1 % | **41.3 %** | **46.7 %** | **2,800 ms** | 9,434 ms |

`smart` mode is the overall winner on both judges and the lowest p50 latency. `hybrid` wins F1 by a hair (4.4% vs 4.1%) but the F1 numbers are noise given the answer-format issue.

## The EM=0 / judge=3 paradox

108/400 rows (27.0%) scored EM=0 but received Qwen judge score 3 (FULLY_CORRECT). 104/400 (26.0%) the same on OpenAI judge.

Example row (naive mode, 4-hop question):

> **Q:** What is the abbreviated name of the exclusive platform of the video game named for the league with a halftime event just before the "publishers clearing house sweepstakes drawing"?
> **GOLD:** NES
> **OUR ANSWER:** "The video game named for the league with a halftime event just before the Publishers Clearing House sweepstakes drawing is NFL (since the Super Bowl halftime show precedes the PCH $10 million winner announcement, as noted in [Chunk 3]). The abbreviated name of the exclusive platform for this game is NES, the Nintendo Entertainment System..."
> **EM = 0** (string mismatch with "NES"), **F1 = 0.10** (low token overlap), **Qwen = 3, OpenAI = 3** (both fully correct)

The verbose explanatory answer contains the gold token but doesn't equal it as a string. SQuAD-style normalization can't fix that. The fix is on the answer side: a `rag.ask(short_answer=True)` mode that returns a few words, not a paragraph. Captured as a follow-up below.

## Per-hop breakdown

The interesting structure lives here, not in the headline.

**Qwen judge — accuracy by hop class:**

| mode | 2-hop | 3-hop | 4-hop |
|---|---|---|---|
| naive | 43.4 % | 40.4 % | 23.5 % |
| naive_boost | 43.4 % | 42.4 % | 33.3 % |
| hybrid | **54.5 %** | 39.4 % | 25.5 % |
| smart | 51.5 % | **42.4 %** | 30.4 % |

**OpenAI judge — accuracy by hop class:**

| mode | 2-hop | 3-hop | 4-hop |
|---|---|---|---|
| naive | 42.4 % | 49.5 % | 26.5 % |
| naive_boost | 44.4 % | 47.5 % | 35.3 % |
| hybrid | 51.5 % | 44.4 % | 26.5 % |
| smart | **52.5 %** | **51.5 %** | **36.3 %** |

**Support recall by hop class:**

| mode | 2-hop | 3-hop | 4-hop |
|---|---|---|---|
| naive | 68.2 % | 67.7 % | 42.6 % |
| naive_boost | 68.2 % | 67.7 % | 42.6 % |
| hybrid | 69.7 % | 66.7 % | 43.4 % |
| smart | 68.2 % | 64.7 % | 41.9 % |

### Reading

- **Graph helps unambiguously on 2-hop questions.** Both judges agree: `hybrid` and `smart` beat `naive` by ~9-11 pp on 2-hop.
- **3-hop is messier.** Qwen says `smart` and `naive_boost` tie best (42.4%). OpenAI says `smart` is best (51.5%) but `naive` is second (49.5%) — graph mode `hybrid` is third. Mixed signal.
- **4-hop heavily favors `naive_boost` and `smart`.** Both judges: graph re-ranking (`naive_boost` 33-35%) and routing (`smart` 30-36%) beat both pure naive (23-26%) AND full hybrid (25-26%). Full hybrid traversal *hurts* on 4-hop, likely because deep multi-hop expansion pulls in noise that confuses the answer LLM.
- **Support recall plateaus around 60% overall, drops to 42-43% on 4-hop.** The harder the chain, the worse retrieval gets at finding all supporting paragraphs. That's expected and matches HippoRAG's reported numbers.

The 4-hop asymmetry — `naive_boost` (1-hop graph re-rank) wins, `hybrid` (1-3 hop traversal) loses — is the most actionable finding. It says **the right amount of graph is "a little"**, not "a lot."

## Where this puts pgrg on the field's MuSiQue table

Comparison only meaningful via support recall and LLM-judge proxy, given the answer-format issue.

| System | F1 | Recall@5 | Notes |
|---|---|---|---|
| BM25 | low 30s | ~40 % | Sparse lexical baseline |
| ColBERTv2 | ~37 | ~65 % | Strong dense baseline |
| **pgrg `smart` (LLM-judge proxy)** | **~46.7 % (OpenAI judge)** | **58.1 %** | Multi-judge methodology; not direct F1 |
| NV-Embed-v2 | 44.8 | 69.7 % | SOTA pure-vector embedder |
| HippoRAG (v1) | ~46 | ~70 % | KG triples + PPR |
| RAPTOR | mid-40s | ~70 % | Hierarchical clustering |
| HippoRAG 2 | 51.9 | 74.7 % | KG + PPR + filtering |
| PropRAG | ~54 | 77.3 % | Propositions + beam-search PPR |

Reading this honestly:

- **Our retrieval (support recall 58-60% across modes) is in the same band as BM25/ColBERTv2 but below NV-Embed-v2 / HippoRAG / RAPTOR.** The likely cause is the embedder — we run `bge-small-en-v1.5` (384-dim), the field's stronger numbers use NV-Embed-v2 (4096-dim) or similar. Embedder swap is a pre-Phase-A consideration in `docs/proposals/PropRAG-on-Postgres.md`.
- **Our LLM-judge accuracy (~46.7% best mode) is in NV-Embed-v2 / HippoRAG-v1 territory** — but this is a soft proxy. Don't quote without the methodology disclosure.
- **The gap to PropRAG (~54)** is real and aligns with what the proposal predicts: propositions + PPR are the missing pieces.

## Per-mode variance and noise

p99 latency is alarming for `naive_boost` (120s) and `hybrid` (120s). p50 is fine (~3s). The tail comes from one or two pathological queries that triggered very long graph traversal. Worth investigating if those are timing out vs actually computing — but not a blocker.

LLM judge agreement: Qwen and OpenAI agree on the overall mode ordering (`smart` best, `naive` worst-or-tied) but disagree at the per-hop level. OpenAI is consistently higher than Qwen (~5 pp). Same finding as in NTSB earlier this week — judge variance is in the 5-7 pp range, on top of GPU-non-determinism in Qwen.

## What the result implies for next steps

**Immediate (before publishing this number to outsiders):** add a `short_answer` mode to `rag.ask()` that returns just the answer (constrained to ≤10 tokens, prompt-tuned for factoid-style QA). Re-run MuSiQue. **Expected outcome:** EM/F1 jumps from ~4% to roughly 30-40% range — making us comparable to BM25/ColBERTv2 on the published table. That's the headline number people expect to see.

**Phase A pre-check (per `docs/proposals/PropRAG-on-Postgres.md`):** even with corrected answer format, our `naive` is likely below NV-Embed-v2's 44.8 because of the embedder gap. Phase A-prime (try a stronger fastembed-supported embedder, e.g. `BAAI/bge-large-en-v1.5` 1024-dim) should run before PropRAG mechanics so we know which lever is actually the bottleneck.

**Confirms the proposal direction:** the per-hop pattern (graph helps on 2-hop, hurts on 4-hop with full traversal but helps with 1-hop boost) is exactly the shape PropRAG's two-stage damping is designed to exploit. Phase B+C remain the right next bets.

**Doesn't confirm:** that we should chase Phase D (beam search) — the gap to ~54 F1 may close enough with embedder + propositions + PPR alone.

## What's true today

- Retrieval works: 58-60% support recall on a 1,700-paragraph corpus with multi-hop questions.
- Graph mode helps on 2-hop questions by ~9-11 pp (both judges).
- Graph mode (full hybrid) hurts on 4-hop questions by ~4-10 pp; 1-hop boost (`naive_boost`) helps on 4-hop.
- `smart` mode is the best overall pick — top judge scores AND lowest p50 latency.
- The 4% F1 headline is misleading; 27% of "wrong" answers are actually correct per both LLM judges.
- The corpus and benchmark are **reproducible** end-to-end via `prepare.py` → `ingest.py` → `run.py`.

## What's not yet true

- We can't directly compare F1 to the published table without a short-answer mode.
- Embedder choice is suspected as the dominant retrieval ceiling, but unproven — Phase A-prime would settle it.
- Propositions + PPR (per the proposal) are the most credible path to closing the gap to PropRAG's ~54.

---

## v2 — Step 1 (`short_answer` mode), 2026-04-29 20:55

Single line of code: a new system prompt that asks the answer LLM to emit a short factoid answer instead of a paragraph. Captured in [`Accuracy-Improvements-Roadmap.md`](../../docs/proposals/Accuracy-Improvements-Roadmap.md) as Step 1.

### Headline (by mode)

| Mode | EM | F1 | Support recall | Qwen judge | OpenAI judge | p50 latency |
|---|---|---|---|---|---|---|
| naive | 18.0 % | 24.4 % | 59.3 % | 38.0 % | 29.0 % | 990 ms |
| naive_boost | 19.0 % | 25.7 % | 59.3 % | 38.0 % | 30.0 % | 312 ms |
| **hybrid** | **27.0 %** | **33.0 %** | 59.8 % | 43.3 % | 38.0 % | 1,838 ms |
| smart | 26.0 % | 31.9 % | 58.1 % | 41.0 % | 36.0 % | 368 ms |

### Reading

**EM and F1 are now publishable.** Step 1 DoD (>25 % EM, >30 % F1 on at least one mode) is met by `hybrid` and `smart`. p50 latency dropped 7.6× on `smart` because the LLM emits ~10 tokens instead of ~200.

**Honest sub-finding:** the OpenAI judge dropped ~10 pp under `short_answer` (verbose `smart` 46.7 % → short `smart` 36.0 %). When forced to a short factoid, the LLM commits to one answer — sometimes the wrong one, even when retrieval found the right context. Verbose mode was getting partial credit for "right context buried in a ramble." `short_answer` reveals the real factoid-extraction hardness. **Both judges still rank `hybrid` and `smart` above `naive` — graph still helps.**

**Where pgrg now lands on the public MuSiQue table:**

| System | F1 | Recall@5 |
|---|---|---|
| BM25 | low 30s | ~40 % |
| **pgrg `hybrid` (short_answer)** | **33.0 %** | **59.8 %** |
| ColBERTv2 | ~37 | ~65 % |
| NV-Embed-v2 | 44.8 | 69.7 % |
| HippoRAG (v1) | ~46 | ~70 % |
| HippoRAG 2 | 51.9 | 74.7 % |
| PropRAG | ~54 | 77.3 % |

We're now in BM25 territory on F1 and below NV-Embed-v2 on retrieval. The retrieval gap is the same embedder story (`bge-small-en-v1.5` vs NV-Embed-v2's 4096-dim model).

Cost: zero added per-query LLM cost, latency *dropped*.

---

## v3 — Step 2 (`short_answer + rerank`), 2026-04-29 23:08

Cross-encoder reranking via `BAAI/bge-reranker-base` on CPU. Retrieval fetches `top_k * rerank_factor` (10 × 4 = 40) candidates; the reranker rescores each (question, chunk) pair and trims to `top_k`.

### Headline (by mode)

| Mode | EM | F1 | Support recall | Qwen judge | OpenAI judge | p50 latency |
|---|---|---|---|---|---|---|
| **naive** | **23.0 %** | **31.2 %** | **67.3 %** | **44.0 %** | 35.3 % | 3,754 ms |
| naive_boost | 23.0 % | 30.0 % | 67.3 % | 43.0 % | 35.7 % | 3,677 ms |
| hybrid | 23.0 % | 29.7 % | 64.0 % | 43.7 % | 38.7 % | 3,253 ms |
| smart | 24.0 % | 30.1 % | 61.3 % | **45.0 %** | 37.0 % | 3,141 ms |

### Deltas vs Step 1 (short_answer alone)

| Mode | EM Δ | F1 Δ | Support Δ | Qwen Δ | OpenAI Δ | Latency Δ |
|---|---|---|---|---|---|---|
| naive | **+5.0** | **+6.8** | **+8.0** | **+6.0** | **+6.3** | +2,764 ms |
| naive_boost | +4.0 | +4.3 | **+8.0** | +5.0 | +5.7 | +3,365 ms |
| hybrid | **−4.0** | **−3.3** | +4.2 | +0.4 | +0.7 | +1,415 ms |
| smart | −2.0 | −1.8 | +3.2 | +4.0 | +1.0 | +2,773 ms |

### Reading — three real findings

1. **Reranker shines on `naive` and `naive_boost`.** F1 +4-7 pp, support recall +8 pp, both judges +5-6 pp. The cross-encoder is fetching a wider candidate pool (40 candidates) and reordering it more accurately than vector cosine alone. Exactly what cross-encoder reranking is supposed to do.
2. **Reranker regresses `hybrid` slightly.** -4 EM, -3.3 F1. Hybrid already does its own merge of `local` + `global` candidates; reranking on top of that picks differently than hybrid's existing scoring. The reranker is "winning" on the candidate bag but losing on the specific top-k that hybrid was assembling. **Recommendation: don't enable rerank for `hybrid` mode by default.**
3. **`smart` is roughly neutral on EM/F1 but Qwen judge +4 pp.** Mixed signals. Qwen judge agrees the top retrieved chunks are higher-quality; EM disagrees because the answer LLM picked a different (sometimes wrong) factoid from the reranked context.

### DoD: partial pass

| DoD criterion | Target | Actual | Result |
|---|---|---|---|
| LLM-judge accuracy on `smart` | ≥ 50 % | 45.0 % Qwen / 37.0 % OpenAI | ❌ improved (+4 pp) but absolute target missed |
| p50 latency increase ≤ 80 ms | ≤ +80 ms | +1,415 to +3,365 ms | ❌ **17-42× over target** |
| Support recall lift | (implicit) | +3-8 pp across modes | ✅ clear retrieval-quality win |

### Why latency overshot

`BAAI/bge-reranker-base` is 1 GB and runs ~10-20 ms per (question, chunk) pair on CPU. With `rerank_factor=4` and `top_k=10`, that's 40 pairs = 400-800 ms cross-encoder time per call, plus larger candidate-fetch cost from the SQL layer. We got 1.4-3.4 s real wall-clock — 2-4× our model-cost estimate, likely a combination of the cross-encoder being slower than nominal under contention with the local Qwen vLLM and Python on shared CPU.

**Two surgical mitigations** (captured for follow-up, not yet shipped):

- **Swap the default reranker model to `Xenova/ms-marco-MiniLM-L-6-v2`** (80 MB, ~5× faster, < 2 pp accuracy loss per published benchmarks). Should bring p50 increase under +400 ms.
- **Drop `rerank_factor` from 4 to 2.** Halves cross-encoder cost; small accuracy tradeoff on retrieval-bound corpora.
- Combined: ~+150-200 ms total cost, much closer to the +80 ms DoD.

### Recommendation

Step 2 is shipped but **`rerank=False` should remain the default**. Users opt in with `rag.query(rerank=True)` or `rag.ask(rerank=True)` when they care about retrieval quality more than latency.

For benchmarks that are retrieval-bound (e.g., MuSiQue, HotpotQA), `rerank=True` is the right call for `naive` and `naive_boost` modes. For low-latency interactive uses, leave it off — Step 1's `short_answer` already buys most of the publishable F1 win at zero latency cost.

---

## Files

- **v1 raw rows:** `_results/results-20260429-145103.json`
- **v2 (Step 1) raw rows:** `_results/results-short_answer-20260429-205512.json`
- **v3 (Step 2) raw rows:** `_results/results-rerank-20260429-221301.json`
- **Sampled question set:** `questions.json`
- **Pooled corpus:** `docs/*.md` (1,700 files, gitignored)
- **Manifest:** `manifest.json`
- **Logs:** `_logs/ingest.log`, `_logs/run.log`, `_logs/run-short_answer.log`, `_logs/run-rerank.log`
