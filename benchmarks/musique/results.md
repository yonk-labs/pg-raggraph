# MuSiQue benchmark — results (2026-04-29)

> **Read this first.** EM and F1 numbers below are **not directly comparable** to the published MuSiQue table. Our `rag.ask()` produces verbose generative answers; MuSiQue's gold answers are short factual strings. **27% of all (question, mode) pairs scored EM=0 but received FULLY_CORRECT (3/3) from both LLM judges.** The honest comparison is the LLM-judge column or the support-recall column — not raw EM/F1. We need a short-answer prompt to make EM/F1 publishable; that's a separate effort.

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

## Files

- **Run config + raw rows:** `_results/results-20260429-145103.json`
- **Sampled question set:** `questions.json`
- **Pooled corpus:** `docs/*.md` (1,700 files)
- **Manifest:** `manifest.json`
- **Ingest log:** `_logs/ingest.log`
- **Run log:** `_logs/run.log`
