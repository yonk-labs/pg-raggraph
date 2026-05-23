# Handover — lede Hint-Biased Summary Retrieval (2026-05-23)

> **Purpose:** Pick up the summary-retrieval work in a fresh session with zero prior context.
> Read this top-to-bottom, then run the **Validate current state** commands, then continue at **Next steps**.

---

## TL;DR

We added a deterministic, LLM-free **summary layer** to pg-raggraph: retrieve chunks → compress them with `lede` (extractive summarize + hint-biased `key_facts`) → send the small summary to the LLM instead of raw chunks. Three power features ride on top (expansion→retrieval, response-shape/result-cache, soft metadata filtering). All of that is **committed and green**.

We then benchmarked it on 3rd-party multi-hop QA (MHR / MuSiQue / 2Wiki) and learned the test regime was **too small to be meaningful** (~2.5K tokens of context — raw chunks are already cheap and have no fluff to remove). The **in-progress, uncommitted** work fixes that: a size **gate** (skip summarization below ~8K tokens), a **context-scaled budget** (ceiling raised 4K→64K chars, scales with retrieved size), adaptive fact count, a TOC option, a **semantic judge** ("does it answer the same question"), and a **new `grounding.py` harness** for larger-context experiments. That harness is **written but not yet run**.

**The single most important framing for the next session:** this is a **graph/multi-hop** system. The value of summarization shows up at **large context** (50K–500K tokens from 10/100/1000 chunks), not at 2.5K. Ground the work there before drawing conclusions — we may be chasing white whales at small sizes.

---

## Project context

**pg-raggraph** = PostgreSQL-native GraphRAG (pgvector + adjacency tables + recursive CTEs + BM25, no AGE). The summary feature is a query-time compression layer: it never changes retrieval scoring, it compresses the retrieved chunk set before the LLM sees it.

- **`lede`** (0.4.2) — deterministic extractive summarizer (Python+Rust, byte-identical). `summarize(text, max_length, hints, hint_focus, hint_mode, keep_headings, include_toc, pin)`, `extract.key_facts(text, max_facts, hints, ...)`, `extract.top_terms`, `extract.correlate_facts`, `extract.toc`. **Char-budgeted, extractive** (selects whole sentences; see open question on truncation).
- **`lede-spacy[synonyms]`** (0.4.2) — optional; `expand_hints(seeds, kinds, top_k, expand_weight)` for lemma/synonym/similar expansion. Needs `en_core_web_sm` (+ `en_core_web_md/lg` for the `similar` kind, not installed). nltk/WordNet pulled by `[synonyms]`.
- **chunkshop 0.5.0** — installed; its `summarize_hits` is `lede` underneath. **Decision (recorded in memory `chunkshop-hybrid-upcoming`): pg-raggraph stays independent** — our graph leg is ours alone. Don't refactor to call chunkshop's retrieval.

---

## Branch & git state

**Branch:** `feat/lede-hint-summary-retrieval` (NOT merged; ~19 commits ahead of `main`). `main` has the e2e benchmark harness base commit `507b4ae`.

### Committed and working (HEAD `7d49fe2`)
- **Summary mode**: `mode="summary"` runs a base substrate (`summary_base_mode`, default hybrid) → `summarize_chunks`; smart-mode tier-0 (ship summary, no LLM, when confidence high); `answer.py` no-LLM fallback now uses the lede summary.
- **lede 0.4.2 + `keep_headings`** (re-injects section headings; default on).
- **`summary_facts`** (HEAD): `summarize_chunks` appends hint-biased `lede.key_facts` (`summary_include_facts`, default on, `summary_max_facts=10`). This was the **bake-off winner**.
- **#1 Expansion→retrieval**: `expand_query_terms` (lexical via lede_spacy + `retrieval_alias_map`), wired into the BM25 `tsquery`; `retrieval_expansion` default **off**. Degrades gracefully when `lede` core absent.
- **#2 Response shape**: `QueryResult.result_id`, in-process LRU `ResultCache`, `GraphRAG.get_cached_result`, `adaptive_summary_length`, `ask()` escalation line for summary mode.
- **#3 Soft metadata filtering**: `metadata_filter.py` (`classify_filters` rejects hard-filtering non-structured fields; `metadata_filter_clauses` builds additive soft-score + structured-only hard WHERE, on the **`d`/document** alias since per-record metadata lands on `documents.metadata`); `prompt_derived_soft` (soft-only, currently a conservative `{}` stub). Wired into the naive builders only.
- **Benchmark harness**: `benchmarks/showcase/sweep.py` (3 arms × expansion × headings) and `benchmarks/showcase/experiments.py` (10-strategy bake-off). Committed results under `benchmarks/showcase/{results,experiments_results}/`.

302 unit tests pass. Only suite failures are environmental: `fastapi` server extra not installed (`test_server.py`, `test_error_paths.py` server/auth/mcp tests) + one HNSW EXPLAIN scale test — all confirmed unrelated to this work.

### UNCOMMITTED / in-progress (validated: imports clean, 24 summary unit tests pass — but NOT committed)
These directly address the 2026-05-23 feedback. **Decide whether to keep, then commit.**

- **`src/pg_raggraph/config.py`** (modified):
  - Gate: `summary_skip_small_contexts=True`, `summary_min_context_tokens=8000`.
  - Context-scaled budget: `summary_target_compression_ratio=0.18`, `summary_max_length_ceiling` **4000 → 64000**.
  - Adaptive facts: `summary_max_facts_ceiling=60`, `summary_fact_tokens_per_extra=4000`.
  - `summary_include_toc=False`.
- **`src/pg_raggraph/summary.py`** (modified): new helpers `chunks_text`, `context_token_count`, `should_summarize_context` (the gate), `adaptive_fact_count`; `adaptive_summary_length` now takes `context_tokens` and scales via compression ratio; `summarize_chunks` now (a) **returns raw chunks unchanged when context < gate**, (b) scales budget by context tokens, (c) passes `include_toc`, (d) scales fact count. Imports `token_count` from `chunking`.
- **`benchmarks/showcase/sweep.py`** (modified): **judge prompt changed** to semantic "does the candidate answer the same question" (NOT "all the same facts") — per the feedback. `experiments.py` still uses the old `_JUDGE_PROMPT` import from sweep, so this change propagates.
- **`tests/unit/test_summary_hints.py`, `test_summary_response_shape.py`** (modified): updated for gate/adaptive behavior.
- **`benchmarks/showcase/grounding.py`** (NEW, untracked, **not yet run**): the larger-context grounding harness implementing the a–f experiment ideas. Arms include no-context, full/query-docs direct, raw chunks at top_k 10/20/30, and full-doc summary+facts(+toc)(+hints) prepended to chunks. Tracks `source_tokens` vs `context_tokens` and a `skipped` flag (for the gate). Has its own results writer.
- New subset files (`mhr-30`, `musique-30`, `twowiki-30`, etc.) and `.llm_cache/`, `*.log` — benchmark byproducts (cache + logs should stay gitignored; `.llm_cache/` already is).

---

## Benchmark findings so far (small-context regime — treat as PRELIMINARY)

n=30/dataset, gpt-5-mini gen+judge, ±~9pp noise. **All on small contexts (~2.5K tokens) — the wrong regime, per the feedback.**

- **Token reduction is real**: summary arms cut context ~67–80%.
- **10-strategy bake-off winner: `summary_facts`** (summarize + appended hint-biased key_facts): 50% vs raw-chunks 53% (within noise) at 67% reduction. **Ties chunks on MHR, beats on 2Wiki.** Now shipped as default.
- **Length alone doesn't help** (`summary_long` = 46%, same as plain summary). **Facts close the gap, not budget.**
- **Option A beats Option B**: concat-then-summarize (46%) >> per-chunk-summarize-then-concat (30%). Settled.
- **`correlate_facts` is worst** (22%) and often *increases* tokens. Avoid.
- **Extractive summaries can't abstain** → `summary_only` scores 0 on every "insufficient information" gold (much of MHR). summary→LLM is the right floor.
- **MuSiQue stays hard** — raw chunks best there; multi-hop synthesis resists extractive compression.

**Caveat the next session MUST respect:** these conclusions are at 2.5K tokens. They may invert at 50K–500K. Re-validate at scale before trusting.

---

## Open questions from the 2026-05-23 feedback (the live agenda)

1. **Multi-hop is the point.** Don't dismiss MuSiQue/MHR as "stubborn" — graph RAG exists to do multi-hop. Optimize for it, don't route around it.
2. **Ceiling was too low** (fixed-4K). Addressed in uncommitted work (scales with context; 64K ceiling). **Validate the scaling is sane at 10/100/1000 chunks.**
3. **Truncation behavior — UNCONFIRMED.** Does `lede.summarize` hard-truncate at `max_length` or select whole sentences? Best understanding: it's **extractive sentence selection within the char budget** (no mid-sentence cut), and **facts + pinned headings are appended additively so the final string can exceed `max_length`**. **Confirm empirically** — `lede.summarize(long_text, max_length=N).summary` and check whether the tail is a clean sentence and whether facts push it over N. If it truncates mid-content, that could be silently dropping answers.
4. **The size gate** (skip summarization when small). Implemented (`summary_min_context_tokens=8000`). **Tune the threshold with real data** — 8000 is a guess.
5. **Baseline clarity.** Current baseline = **raw retrieved chunks**. The feedback wants more baselines (see experiment suite). `grounding.py` adds: no-context, full-doc, chunks@10/20/30.
6. **Judge = semantic answer-equivalence** (done in `sweep.py`), not fact-matching. Make sure `experiments.py`/`grounding.py` use the same.
7. **LARGER docs.** Current corpora are small wiki paragraphs (MHR is the largest, tech-news articles ~5K tok/doc). **Need genuinely large documents** to show the summarization value. Either find a large-doc benchmark or construct one (concatenate, or use a long-form corpus). This is the crux — without it, the whole comparison stays in the uninteresting regime.
8. **Prestaging / precompute (option C).** Background-process summaries and fact extraction at **ingest time**, store them, reuse at query time. Currently everything is query-time. This is a real architecture direction — likely a schema column or sidecar table for per-doc/per-chunk summary + facts. (Out of scope of the current branch's brief; would be its own mission.)

---

## Next steps (recommended order)

1. **Validate + commit the in-progress work.** Run the summary unit + integration tests (below). If green, commit the gate / context-scaled budget / adaptive facts / TOC / judge change as 2–3 focused commits. (They're currently a lump of uncommitted edits.)
2. **Confirm the truncation behavior** (open question #3) with a 3-line lede script. Document the answer. If it truncates badly, that's a bug to fix before more benchmarking.
3. **Run `grounding.py`** on the largest available corpus (start `--dataset mhr --subset 5` to smoke, then scale). Read the no-context and full-doc baselines first — they tell you whether the LLM already knows the answer (white-whale check) and the ceiling of "send everything."
4. **Get larger docs** (#7). Without them, stop optimizing — the small-context numbers are noise. Decide: find a long-doc benchmark, or synthesize one from the existing corpora.
5. **Re-run the bake-off / sweep at the large-context regime** with the gate active. Re-evaluate whether `summary_facts` / headings / expansion still win.
6. **Then** decide on prestaging (#8) as a follow-on mission, and on finishing the branch (it's large — likely a PR or a 3-way split: summary-mode / power-features / benchmark).

Use a **mission brief** (`/mission-brief`) before #4–6 if the scope feels >4 steps — the existing brief at `skill-output/mission-brief/Mission-Brief-summary-retrieval-power-features.md` covers features #1–3, not the large-context benchmarking.

---

## How to run things

```bash
# Tests
uv run pytest tests/unit/ -q                          # 302 pass, no DB needed
uv run pytest tests/integration/test_summary_mode.py tests/integration/test_summary_response_it.py -q   # needs Postgres :5434
uv run ruff check . && uv run ruff format --check .

# Bench DB: 3rd-party data is ALREADY LOADED on postgres-bench (port 5437,
# db pg_raggraph_bench, namespaces bench_{mhr,musique,twowiki}_lede_spacy,
# embeddings bge-large dim 1024). Snapshot: benchmarks/e2e/snapshots/2026-05-20-bench.pgcustom
docker compose ps                                     # postgres (5434) + postgres-bench (5437)

# OpenAI key lives in ../.openai (multiple keys; scripts grab the FIRST sk- via re.search).
# DO NOT do `OPENAI_API_KEY=$(grep -oE 'sk-...' ../.openai)` — it slurps ALL keys.
# Instead run with `env -u OPENAI_API_KEY` and let the script's _api_key() read the file.

# Showcase sweep (3 arms × expansion × headings)
env -u OPENAI_API_KEY uv run python -m benchmarks.showcase.sweep --dataset all --subset 30

# 10-strategy bake-off
env -u OPENAI_API_KEY uv run python -m benchmarks.showcase.experiments --dataset all --subset 30

# Larger-context grounding (NEW, run this next)
env -u OPENAI_API_KEY uv run python -m benchmarks.showcase.grounding --dataset mhr --subset 5
```

LLM calls are disk-cached in `benchmarks/showcase/.llm_cache/` (keyed on model+prompt), so re-runs are nearly free. Judge + gen both default to `gpt-5-mini` (override via `PGRG_SHOWCASE_GEN_MODEL` / `PGRG_SHOWCASE_JUDGE_MODEL`). Local Qwen alt: `192.168.1.193:8000` / `PGRG_BENCH_LOCAL_LLM_BASE`.

---

## Key files

| Path | What |
|---|---|
| `src/pg_raggraph/summary.py` | hint pipeline, `expand_query_terms`, gate, adaptive length/facts, `summarize_chunks` |
| `src/pg_raggraph/config.py` | all `summary_*` / `retrieval_*` / `*_metadata_*` knobs (lines ~384–430) |
| `src/pg_raggraph/retrieval.py` | `mode="summary"` dispatch, `_summary_query`, smart tier-0, `_to_or_tsquery(extra_terms)`, metadata-filter splice |
| `src/pg_raggraph/result_cache.py` | in-process LRU `ResultCache` |
| `src/pg_raggraph/metadata_filter.py` | `classify_filters`, `metadata_filter_clauses`, `prompt_derived_soft` |
| `src/pg_raggraph/answer.py` | `generate_answer` ships summary / lede fallback |
| `benchmarks/showcase/sweep.py` | summary-vs-chunks sweep + (updated) semantic judge |
| `benchmarks/showcase/experiments.py` | 10-strategy bake-off |
| `benchmarks/showcase/grounding.py` | **NEW** larger-context harness (a–f) — run next |
| `docs/superpowers/plans/2026-05-22-*.md` | the two implementation plans (summary mode; power features) |
| `skill-output/mission-brief/Mission-Brief-summary-retrieval-power-features.md` | brief for features #1–3 |

Memory worth reading: `chunkshop-hybrid-upcoming` (stay-independent decision), `lede-hint-summary-retrieval`, benchmark-philosophy ("at low absolute accuracy, pp lifts are noise; root-cause the pipeline before optimizing ranking").

---

## Paste-ready new-session prompt

```
Continue the lede summary-retrieval work on branch feat/lede-hint-summary-retrieval
in /home/yonk/yonk-tools/pg-raggraph. Read docs/superpowers/HANDOVER-2026-05-23-summary-retrieval.md
first — it has the full state.

Context: pg-raggraph is a Postgres GraphRAG lib. We added a query-time summary layer
(retrieve chunks → lede extractive summary + hint-biased key_facts → send to LLM
instead of raw chunks) plus 3 power features (expansion→retrieval, response-shape/
result-cache, soft metadata filtering). All committed + green (302 unit tests).

There is UNCOMMITTED in-progress work (summary.py, config.py, sweep.py, two test files)
that adds: a size GATE (skip summarization below summary_min_context_tokens=8000),
a context-scaled summary budget (ceiling 4K→64K, summary_target_compression_ratio),
adaptive fact count, a TOC option, and a semantic "answers the same question" judge.
Plus a new untracked harness benchmarks/showcase/grounding.py (larger-context
experiments) that has NOT been run yet. Imports are clean and 24 summary unit tests pass.

Do this, in order:
1. Run `uv run pytest tests/unit/ -q` and the summary integration tests (Postgres on
   :5434). If green, commit the in-progress gate/scaling/judge work as focused commits.
2. Confirm lede's truncation behavior: does summarize() hard-truncate at max_length or
   select whole sentences, and do appended facts/headings push the result over max_length?
   (3-line script.) Document it; fix if it's silently dropping content.
3. Run grounding.py (start: --dataset mhr --subset 5) and read the no-context and
   full-doc baselines FIRST — they tell us if the LLM already knows the answers
   (white-whale check) and the ceiling of "send everything."
4. CRITICAL: our benchmark corpora are too SMALL (~2.5K-token contexts) to show
   summarization value. This is a graph/MULTI-HOP system and summaries matter at
   50K–500K-token contexts (10/100/1000 chunks). Get genuinely large docs (find a
   long-doc benchmark or synthesize one) before drawing more conclusions. The small-
   context findings (summary_facts wins, headings help, expansion hurts) are PRELIMINARY
   and may invert at scale.
5. Then re-run the sweeps with the gate active at the large-context regime, and
   consider prestaging (ingest-time background summaries + fact extraction stored for
   reuse) as a follow-on mission.

Use the bench DB already loaded on port 5437 (db pg_raggraph_bench, namespaces
bench_{mhr,musique,twowiki}_lede_spacy, bge-large dim 1024). OpenAI key is in ../.openai
(multiple keys — let scripts' _api_key() read the first; run with `env -u OPENAI_API_KEY`).
Don't merge the branch without asking; it's large and may want a 3-way split.
```
