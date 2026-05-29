# MuSiQue benchmark

**Goal:** Test whether pgrg's graph modes beat naive vector retrieval on a corpus *constructed* to require multi-hop reasoning. If hybrid/naive_boost don't win here, the "graph earns its keep on multi-doc entity chains" claim is in trouble.

## Dataset

- **MuSiQue-Ans** dev split (Trivedi et al. 2022) — 2,417 answerable 2-4 hop questions, each with 20 paragraphs (gold supporting chain + distractors) and a labeled answer.
- Source: `https://huggingface.co/datasets/dgslibisey/MuSiQue` (mirror of the [official release](https://github.com/StonyBrookNLP/musique))
- License per the original release.

## Sampling

- N = **100** questions, stratified 33/33/34 across 2-hop / 3-hop / 4-hop.
- Seed: 20260429 (set in `prepare.py`).
- Pool-mode corpus: union of all paragraphs across the 100 sampled questions, dedup'd by `(title, paragraph_text)` → ~1,700 unique paragraph docs.
- Each paragraph is written as `# Title\n\n<text>` markdown so retrieval has a meaningful title boundary.

This shape lets graph mode actually engage: retrieval has to find the right 2-4 paragraphs out of ~1,700, and entity chains across paragraphs are the natural way to do it. (Per-question 20-paragraph mini-corpora wouldn't test graph at all.)

## How to reproduce

```bash
# 1. Download the dev split (~30 MB)
mkdir -p benchmarks/musique/raw
curl -L -o benchmarks/musique/raw/musique_ans_v1.0_dev.jsonl \
  https://huggingface.co/datasets/dgslibisey/MuSiQue/resolve/main/musique_ans_v1.0_dev.jsonl

# 2. Sample 100 questions and write the pooled paragraph corpus
python3 benchmarks/musique/prepare.py

# 3. Ingest (~60-100 min depending on LLM throughput)
uv run python benchmarks/musique/ingest.py

# 4. Run eval (4 modes × 100 questions, both judges)
uv run python benchmarks/musique/run.py --judge both
```

## Graph-vs-vector — the corrected verdict (2026-05-29)

The decisive graph-vs-vector run. It adds the **pure recursive-traversal** modes
(`local` = entity-neighborhood walk via `WITH RECURSIVE … max_hops=2`; `global`)
that earlier runs omitted, and grades with **two** judges to separate signal
from judge noise. `run.py` now decouples the judge endpoint from the
answer-generation endpoint, so a different model can grade:

```bash
# Graph: bench_musique on port 5434 (384-dim bge-small), an LLM-extracted KG
#        (9,809 typed edges). Built by ingest.py above.
export PGRG_DSN="postgresql://postgres:postgres@localhost:5434/pg_raggraph"
# Answer generation — local Qwen:
export PGRG_TEST_LLM_URL="http://192.168.1.193:8000/v1"
export PGRG_TEST_LLM_MODEL="Intel/Qwen3-Coder-Next-int4-AutoRound"
# Judge A — local gemma (free), decoupled from the answer model:
export PGRG_JUDGE_LLM_URL="http://192.168.1.133:8000/v1"
export PGRG_JUDGE_LLM_MODEL="cyankiwi/gemma-4-26B-A4B-it-AWQ-4bit"
# Judge B — gpt-5-mini (small cost). NB: never default to gpt-4x.
export OPENAI_API_KEY="…"        # work key
export OPENAI_JUDGE_MODEL="gpt-5-mini"

uv run python benchmarks/musique/run.py \
  --modes naive,naive_boost,local,global,hybrid,smart \
  --judge both \
  --out-tag full-6mode-dual-judge
```

**Headline:** `local` (recursive traversal) beats `naive` (pure vector) by
**~4-5pp** end-to-end — judge gemma 45.3 vs 40.3, gpt-5-mini 44.0 vs 39.0 —
stable across two independent answer-gen runs and both judges (82% agreement).
On a real graph with real traversal, **graph wins on multi-hop QA.** Caveats:
retrieval recall is flat (the lift is answer-context, not recall); per-hop n≈33
splits are noisy (3-hop is the consistent winner; 4-hop magnitude is unreliable);
only `local` is judge-robust. Full write-up:
[`docs/blogs/04-graph-vs-vector-the-empty-graph.md`](../../docs/blogs/04-graph-vs-vector-the-empty-graph.md).
Artifacts: `_results/results-full-6mode-dual-judge.json`.

## Modes tested

`naive` (baseline vector + BM25), `naive_boost` (1-hop graph re-rank), `local`
(recursive entity-neighborhood traversal, `max_hops=2`), `global` (global graph),
`hybrid` (full local + global + vector + FTS), `smart` (confidence-routed).

## Metrics

- **EM / F1** — official MuSiQue metrics, SQuAD-style normalization (lowercase, strip punctuation/articles, token overlap). MuSiQue ships ground-truth answers with aliases.
- **Support recall** — fraction of gold supporting paragraphs whose title appears in the top-5 retrieved chunks. Pure-retrieval signal independent of LLM.
- **Qwen judge** (local Qwen3-Coder-Next-int4) — 0-3 rubric, free.
- **OpenAI judge** (gpt-4o-mini) — same rubric, ~$0.30 cost on n=100.
- **Per-hop breakdown** — EM/F1/judge scores split across 2hop / 3hop / 4hop. If graph mode helps, the lift should be larger on 3-4 hop than on 2-hop.

## Files

- `prepare.py` — sample + pool the corpus.
- `ingest.py` — ingest the pooled corpus.
- `run.py` — run the eval (answer generation + scoring + judging).
- `questions.json` — sampled questions with gold answers, aliases, supporting docs.
- `manifest.json` — what was sampled and from where.
- `docs/` — pooled paragraph markdown files (1 file per unique paragraph).
- `_results/` — timestamped JSON results from `run.py`.
- `results.md` — written by hand after the run, summarizing the verdict.
