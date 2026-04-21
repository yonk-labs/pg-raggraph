# Return to the bake-off — session handoff #3 (2026-04-21)

**Continuation of the 7-corpus × 3-engine benchmark expansion.** Prior handoffs: [RETURN-TO-BAKEOFF.md](RETURN-TO-BAKEOFF.md) and [RETURN-TO-BAKEOFF-2.md](RETURN-TO-BAKEOFF-2.md) (hierarchy chunker story, T-G1 v1 decision).

This handoff covers the **Phase 0 infrastructure + Phase 1 first run (GraphRAG-Bench medical)** — 16 commits landed in one long session, ended with a real architectural realization about summarization that blocks the Phase 1 re-run.

---

## TL;DR

Phase 1 medical produced one real headline (**pgrg/hybrid 73/100 vs age/hybrid 66/100**, first corpus in the series where pgrg cleanly beats AGE) plus two methodology discoveries that stopped the full matrix:

1. **Local Qwen-Coder-Next is inadequate for clinical answer generation** (17-25/100 vs gpt-5-mini's 73). Confirmed by cross-validation — not a judge artifact.
2. **Chunk truncation destroyed gpt-5-mini's answers** on non-hybrid modes (7/100 vs 73/100 expected). The hierarchy chunker's 134KB "bladder cancer" single chunk is a **feature** for the graph layer (topic coherence = relationship signal), but cripples answer-time context.

The unblock **isn't smaller chunks** — it's adding a summarizer layer between ingest and answer-time so the 134KB chunk stays intact for graph purposes but compresses to ~2KB summary for LLM context. Spec in §"The right answer" below.

---

## What shipped (16 commits today)

| SHA | What |
|---|---|
| `bd232ca` | fix(bakeoff): empty-string `BAKEOFF_*_BASE_URL` forces default endpoint (pydantic-settings re-load bug) |
| `f5f6a36` | **Phase 1 graphrag-bench-medical results paper** — pgrg/hybrid 73 vs age/hybrid 66 |
| `ee88659` | fix(bakeoff): chunk-truncation + local-model pricing + 90min step cap |
| `d81d034` | feat(bakeoff): route answer/judge/extraction through BAKEOFF_*_BASE_URL |
| `065f0d6` | feat(bakeoff): --engines filter for pgrg-only / age-only runs |
| `737c364` | fix(bakeoff): harden runner — progress log, incremental flush, concurrent engines |
| `0ffe54f` | feat(bakeoff): GraphRAG-Bench medical wire-up + GPT-5 temp fix + schema |
| `0f7a43a` | feat(bakeoff): sweep driver + question materializer + first materialized set |
| `c349521` | feat(bakeoff): MS GraphRAG engine adapter + tests (live-validated) |
| `23b8b50` | feat(bakeoff): external corpus loaders for Phase 0 of multi-corpus run |
| `54a3b6f` | docs(benchmarks): paper template + index for 7-corpus expansion |
| `6f62b2d` | docs(T-07+T-08): chunkshop stays sibling — integration doc + lineage |
| `1ee1aad` | docs(T-G1): graph-approach direction decision v1 |
| `846d8d4` | chore(repo): PR-101 + PR-102 — public-repo release blockers |
| `5091f34` | chore(repo): public-release prep — CI frozen, community scaffolding |
| `edb6cc3` | feat(hierarchy): integration tests, user docs, close acme smart row |

---

## Phase 1 state — GraphRAG-Bench medical

### What's complete

- **Extraction cache**: `corpora/external-extractions/graphrag-bench-medical.json` (22 chunks → 261 entities, 277 relationships, cost $0.05 on gpt-5-nano).
- **Hybrid gold anchor run**: `results/raw/graphrag-bench-medical__hybrid.json` (200 records, 0 errors, $6.11 on gpt-5-mini, both engines × 100 Q).
- **Hybrid judged**: 8 judge files exist but only hybrid is trustworthy under current methodology.
- **Cross-validation on hybrid + naive**: Qwen-judge vs gpt-5-mini-judge 8-9/10 agreement — judge is reliable.
- **Paper draft published**: `docs/benchmarks/graphrag-bench-medical.md` with the real 73 vs 66 headline, per-class breakdown, discussion, limitations. Labeled "results complete; paper draft."

### What's INVALID and needs to be re-run

The 7 non-hybrid medical raw files (`__naive`, `__naive_boost`, `__local`, `__global`, `__smart`, `__age_local`, `__age_global`). They were run against local Qwen-Coder-Next as answer model, which is inadequate for clinical reasoning (scores 17-25/100 vs 73 for hybrid). Then attempted re-run with gpt-5-mini but had chunk truncation active, which also cratered quality (7/100 on naive).

**These 7 raw JSONs and their judge counterparts should be treated as data to delete, not numbers to cite.** The `graphrag-bench-medical__hybrid.json` is the only clean file.

### Uncommitted state at handoff

```
 M benchmarks/age-bakeoff/questions/graphrag-bench-medical.yaml   # still 100Q, no functional change
 M benchmarks/age-bakeoff/results/cost-judge.json                 # judge tally through hybrid
 M benchmarks/age-bakeoff/results/cost-run.json                   # $6.11 hybrid + wasted mini attempts
 M benchmarks/age-bakeoff/scripts/launch-gb-medical-mini-rerun.sh # last-edit added BAKEOFF_ANSWER_CHUNK_CHARS=0
?? benchmarks/age-bakeoff/corpora/                                # extraction caches (external corpora)
?? benchmarks/age-bakeoff/results/judge/graphrag-bench-medical__hybrid.json  # hybrid's 3-vote verdicts
```

The hybrid judge file is the only uncommitted judge output worth keeping.

---

## The architectural realization that blocks next-phase work

User's observation that unlocked it:

> "The whole purpose here would be to take the 134K chunk on bladder cancer and say these are all related."

**Interpretation:** keeping the 134KB "bladder cancer" topic as ONE chunk is what makes the graph layer useful — all bladder-cancer entities link to the same chunk, so the graph can surface topic coherence as a retrieval signal. Breaking it into smaller chunks fragments that relationship.

**What I got wrong:** I tried to fix answer-time slowness by truncating chunks down to 2KB. That works for Qwen-speed but destroys the retrieved context gpt-5-mini needs to generate accurate clinical answers. The 7/100 naive/mini result is the smoking gun.

**The right answer** (drafted in my response, pending user sign-off):

```
topic-doc (134KB)
  → [summarizer] → summary (~2KB)
                    ├─ embedded → summary_embeddings (retrieval)
                    ├─ LLM entity extraction → doc-level graph edges
                    └─ passed as context at answer time (instead of full chunk)
topic-doc chunks stay stored as-is for drill-in fallback.
```

Three sizes of fix offered in the conversation:

**(a) Minimum viable** — summary-at-ingest only. ~2-4h. Add `_summarize_doc` to `extract_external_corpus.py` (sumy by default, configurable). Store summaries as separate chunks with `doc_summary=True` metadata. At answer time, swap full-chunk for summary when chunk > N KB. No schema changes.

**(b) Full two-level** — ~1-2 days. Summaries table in pg-raggraph, summary-level retrieval ranking, summary-level entity extraction, etc.

**(c) Proper chunkshop DocFramer + Summarizer plugin** — ~3-5 days. Full architectural version.

**User-preferred summarizers per earlier discussion:** `sumy`, `skimr`, `skimr-neural` (last two are sibling yonk-labs projects at `/home/yonk/yonk-tools/skimr-neural/`). `_Pending:_ user should point at skimr-neural's entry point when ready._`

My recommendation was **(a)**. User said "let's take a break" before confirming — treat as pending decision.

---

## Infrastructure ready for next session

### Loaders (all live-tested)

`benchmarks/age-bakeoff/src/age_bakeoff/extraction/external_corpora.py`:
- `graphrag-bench-medical` ✅ (22 docs, split on "About X")
- `graphrag-bench-novel` ⚠️ (20 docs, **no paragraph structure**, hierarchy chunker produces single 450KB chunks → extraction timeout. Sentence_aware produces 1500+ chunks but still hangs. Needs incremental-save retrofit to extractor or approach change.)
- `ms-hotpotqa` ✅ (5482 docs + 5491 Q, gold answers auto-fetched from HotPotQA 2018 upstream — 100% coverage)
- `ms-kevin-scott` ⚠️ (sensemaking questions, **no gold answers** — pairwise judge needed)
- `ms-msft-{single,multi}` ⚠️ (same — no gold answers)
- `pg-src` (existing) — Task 20

### Engines

- `engines/pgrg.py`, `engines/age.py`: existing, hardened this session
- `engines/msgraph.py`: new, live-validated on 6-doc fixture × 4 modes (basic/local/global/drift). Uses text-embedding-3-small + gpt-5-mini by default. **Still pending Phase 4** — not wired into `_load_corpora()` / `_get_engines()`.

### Sweep driver

`scripts/bench-corpus.sh` — the canonical per-corpus workflow. Currently calls tools (`materialize_questions`, `pick_factorial_winner`, `msgraph_index`, `msgraph_run`, `emit_paper`) some of which don't exist yet. Phase 1 used `launch-gb-medical-mini-rerun.sh` — a simpler per-corpus launcher. Can follow that pattern per-corpus for Phase 2-4 until `bench-corpus.sh` is fully plumbed.

### Model routing

`src/age_bakeoff/llm_clients.py` — 3-role factory. Honors `BAKEOFF_{ANSWER,JUDGE,EXTRACTION}_{BASE_URL,MODEL}`. Empty-string base_url now falls through to OpenAI default (the pydantic-settings re-load trap is closed).

Current `.env` has all three routes pointing at local Qwen. For mini-answer runs, the launcher overrides `BAKEOFF_ANSWER_BASE_URL=""` + `BAKEOFF_ANSWER_MODEL=gpt-5-mini`.

### Cost tracker

`src/age_bakeoff/cost.py` — knows full GPT-5 pricing. Local models (Intel/, Qwen/, ollama/, local/ prefixes + qwen/llama/mistral/phi substrings) record $0.

---

## Budget state

- **Spent**: ~$6.20 (hybrid run $6.11 + extractions + cross-validation)
- **Remaining on home_key**: ~$58
- **Work_key available** as fallback (`/home/yonk/yonk-tools/.openai`)
- **Local Qwen** at `192.168.1.193:8000` — fast (5 parallel ~0.6s on small prompts), free, **inadequate for clinical reasoning answer-gen**, fine for judge (8-9/10 agreement with gpt-5-mini) and possibly for extraction (structured output is its strength; novel extraction broke on malformed dict responses, now handled defensively).

---

## Open methodology questions

1. **Summarizer choice**: sumy (vanilla), skimr, or skimr-neural. Skimr entry points unexplored. **User sign-off pending.**
2. **Pairwise judge for no-gold corpora** (Kevin Scott, MSFT): BenchmarkQED-style comprehensiveness/diversity/empowerment judging not yet implemented. Blocks Phase 2 for those corpora.
3. **Chunker × embedder factorial** per corpus: spec'd in mission brief, not yet run on any new corpus (SCOTUS's hierarchy + bge-small-int8 carried forward as informed default).
4. **T-G1 v1 conclusion "graph is noise when chunks are good"**: medical's 73 vs 66 pushes back on that. v2 needs the full 7-corpus matrix to settle.

---

## Immediate next-session plan (if user confirms fix (a))

1. **Park novel** — deferred until summary pipeline stabilizes or an incremental-save retrofit to `extract_external_corpus.py` lands.
2. **Implement summarizer** in `tools/extract_external_corpus.py`:
   - Add `--summarizer {sumy,skimr,skimr-neural,none}` flag (default sumy)
   - Add `--summary-max-chars 2000` flag
   - For each doc, call summarizer, store alongside chunks
3. **Modify `openai_answerer.py`** so when a retrieved chunk has a `summary_chunk=True` flag, use that; otherwise pass full chunk.
4. **Re-ingest medical** with summary layer enabled (~$0.50, 2 min).
5. **Re-run 7 medical modes** on gpt-5-mini (no truncation, summaries as context): ETA 2-3 hours, expected ~$5-10 total.
6. **Judge with Qwen** ($0).
7. **Update medical paper §5** with the real retrieval-mode matrix.
8. **Then Phase 2**: ms-hotpotqa (gold answers, straightforward), ms-kevin-scott (pairwise judge needed).

---

## Resume prompt for next session

```
Read benchmarks/age-bakeoff/RETURN-TO-BAKEOFF-3.md. The hybrid gold anchor
result (pgrg 73 vs age 66 on GraphRAG-Bench medical) is real and paper'd.
The 7 non-hybrid medical raw files are invalid (Qwen-answer quality failure
+ chunk-truncation harm). Next step pending user sign-off: implement
summarizer-at-ingest (option a from the architectural fix in §"The right
answer") so the 134KB topic chunks stay intact for graph coherence but
compress to ~2KB summaries for answer-time context. User may want to
point at /home/yonk/yonk-tools/skimr-neural/ as the summarizer. Then
re-run medical cleanly, continue to Phase 2 corpora.
```
