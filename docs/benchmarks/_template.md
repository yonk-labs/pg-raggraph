# Benchmark: {Corpus Name}

> Standalone benchmark paper. Every section is required. Remove these blockquotes and the `{placeholders}` when authoring a real paper.

**Corpus:** `{corpus-id-used-in-bakeoff}`
**Status:** draft | published
**Run date:** YYYY-MM-DD
**Raw results:** `benchmarks/age-bakeoff/results/raw/{corpus-id}*.json`
**Judge results:** `benchmarks/age-bakeoff/results/judge/{corpus-id}*.json`
**Reproduced by:** one-line command from the Reproducibility section below

---

## TL;DR

> 2-3 sentences. The headline finding, the operating regime, the caveat. If a reader stops here they should know whether to keep reading.

## 1. Corpus

- **Source:** where the data came from (URL, paper, repo). License.
- **Shape:** document count, typical length, title convention, language, structural features (headings, tables, code, dialogue, etc.).
- **Domain:** medical / legal / literary / code / news / conversation / other.
- **Why this corpus:** what we thought this would tell us that the prior corpora didn't. One-paragraph hypothesis.

## 2. Prior Work

> What's already been published on this corpus? Cite the paper or leaderboard. Summarize their top result and methodology in 3-5 sentences.

- Paper(s) that introduced or popularized the corpus.
- Leaderboard if one exists (URL + snapshot date).
- Engines previously benchmarked and their headline numbers.
- Where our methodology overlaps and where it diverges (don't pretend to be exactly comparable if we're not).

## 3. Setup

### 3.1 Chunking × embedding cell

> From the Phase-0 factorial sweep. Winner of the 12-cell sweep on this corpus.

| | Used | Alternatives considered |
|---|---|---|
| Chunker | `{chunker}` | `{others-from-factorial}` |
| Embedder | `{model}` | `{others-from-factorial}` |
| Quantization | `int8` / `fp32` | |

Factorial raw results: `benchmarks/age-bakeoff/results/factorial/{corpus-id}.json`.

### 3.2 Retrieval modes tested

- pgrg: `naive`, `naive_boost`, `local`, `global`, `hybrid`, `smart`
- AGE: `hybrid`, `local`, `global` (mode parity caveat below)
- MS GraphRAG: `local`, `global`, `drift`, `basic` (its native modes)

### 3.3 Engines

- pg-raggraph: commit `{sha}`, `chunk_strategy={...}`, `top_k=10`.
- Apache AGE: `{docker image sha}`, Cypher patterns per `benchmarks/age-bakeoff/src/age_bakeoff/engines/age.py`.
- Microsoft GraphRAG: `graphrag=={version}`, `pip install graphrag`.

### 3.4 Answer + judge

- Answer model: `gpt-4.1-mini` via OpenAI API.
- Judge model: `gpt-4.1-mini`, majority-of-3 verdicts per question × engine × mode.
- Rubric: `fully_correct` / `partially_correct` / `wrong` / `hallucinated`. Same rubric as all other per-corpus papers in this series.

### 3.5 Question set

- Total in upstream corpus: `{N}`
- Subset used: 100 questions, stratified by question class, seed=42.
- Per-class breakdown: | class | n |
- Subset file: `benchmarks/age-bakeoff/questions/{corpus-id}.yaml`

## 4. Methodology

- How the sweep was run (one paragraph referring to `scripts/factorial-then-modes.sh` and any corpus-specific deviations).
- Fairness constraints: same chunks across engines where possible, shared embedder, shared answer model, shared judge model.
- Known asymmetries: document anything that violates perfect fairness (e.g., MS GraphRAG's native chunker differs; MS GraphRAG's indexing costs money the others don't).
- Seed stability: `seed=42` used for question subset, chunk ordering, any random-sampling step. Re-run produces byte-identical output.

## 5. Results

### 5.1 Overall accuracy — fully_correct / N

| engine | mode | fully_correct | partially | wrong | hallucinated |
|---|---|---|---|---|---|
| pgrg | naive | | | | |
| pgrg | naive_boost | | | | |
| pgrg | local | | | | |
| pgrg | global | | | | |
| pgrg | hybrid | | | | |
| pgrg | smart | | | | |
| age | hybrid | | | | |
| age | local | | | | |
| age | global | | | | |
| msgraph | basic | | | | |
| msgraph | local | | | | |
| msgraph | global | | | | |

### 5.2 By question class

One row per class, columns per engine × mode, fully_correct counts.

### 5.3 Latency

| engine | mode | p50 ms | p95 ms | p99 ms | mean ms | n |
|---|---|---|---|---|---|---|

### 5.4 Cost

| engine | ingest USD | answer USD | judge USD | total USD |
|---|---|---|---|---|

### 5.5 Hallucination rate

Any engine × mode where hallucinations > 10% on this corpus is flagged.

## 6. Discussion

- Does the headline result match or disagree with the corpus's prior work? Why?
- Does it match or disagree with the other papers in this series? Specifically: does T-G1 v1's "graph is noise when chunks are good" survive this corpus?
- Per-class nuance: any class where graph modes genuinely beat naive on this corpus?
- Engine-specific: any engine that wins or loses surprisingly here?

## 7. Limitations

- Corpus-specific licensing / redistribution constraints that affect reproducibility.
- Question-set biases (if the upstream authors had selection biases, note them).
- Cost choices made that might have affected results (e.g., if we ran pgrg extraction on a cheaper model for this corpus, flag).
- Anything that failed silently or that we couldn't test (e.g., MS GraphRAG failed to index pg-src — documented, not hidden).

## 8. Reproducibility

```bash
# One-command reproduction (assumes env vars + docker up)
cd benchmarks/age-bakeoff
./scripts/factorial-then-modes.sh {corpus-id}
```

**Requirements:**
- OpenAI API key in `.env`
- Docker compose stack up (`pgrg` on :5434, `age` on :5435)
- MS GraphRAG installed: `uv pip install graphrag`
- Local dependencies: `uv sync --all-extras --frozen`
- Total wall time: `{X}` min on `{CPU spec}`
- Total cost: `${Y}`

Raw result files shipped in-repo at the paths listed at the top.

## References

- {Original corpus paper}
- {Any engine paper — MS GraphRAG, LightRAG, etc.}
- Our prior work: `benchmarks/age-bakeoff/results/REPORT-VERDICT.md`, `docs/archive/graph-direction-decision.md`
