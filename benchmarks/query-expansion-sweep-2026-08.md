# query_expansion sweep — default flipped to "off" (#89, 2026-08-29)

Question (#89): `query_expansion` shipped defaulting to `"moderate"`
(lemma + WordNet synonyms via the `lede-spacy[synonyms]` extra) with no
in-repo validation. stele's cross-domain sweep found hint expansion
neutral-to-marginal; does it earn its cost on our corpora?

## Method

- Harness: `benchmarks/e2e/run.py`, mode `L0_summary` (the only rung where
  `query_expansion` participates — it steers `build_hints` for lede's
  summary packing; `retrieval_expansion` is a separate knob, already off).
- Corpora: the 2026-05-20 bench snapshot (bge-large-en-v1.5/1024, real
  extracted graphs) restored to `postgres-bench`; MHR (609 docs) and
  MuSiQue (1,847 docs); 100 queries each, seed 42, `--skip-ingest
  --judge none`.
- Arms: `PGRG_QUERY_EXPANSION` ∈ {off, lemma, moderate} (aggressive needs
  en_core_web_md — not installed, degrades to moderate, skipped). Tier
  liveness verified out-of-band: the three tiers produce 4/5/16 hints on a
  sample query, so a silent lede-spacy fallback is excluded.
- Metric: span_recall / hit@1 / mrr on the summary output (deterministic,
  judge-free — the same layer the w_rare calibration used). Raw results:
  `benchmarks/e2e/results/qexp-{off,lemma,moderate}/` (gitignored dir;
  numbers below are the record).

## Results (n=100 per cell)

| tier | MHR span | MuSiQue span | MHR hit@1/mrr | MuSiQue hit@1/mrr |
|---|---|---|---|---|
| off | 0.690 | 0.600 | 0.490 / 0.548 | 0.230 / 0.344 |
| lemma | 0.690 | 0.600 | 0.490 / 0.548 | 0.230 / 0.344 |
| moderate | 0.700 | 0.600 | 0.490 / 0.550 | 0.230 / 0.344 |

Per-query deltas, off vs moderate: **1 of 200 queries changed** (MHR, +1
better, 0 worse; MuSiQue zero deltas). off ≡ lemma byte-identical. The
knob was live (the one delta proves env propagation); the effect is noise.

## Cost of "moderate" (microbench, warm process)

- ~1.2 s cold start (spaCy model + WordNet corpus load) on the first
  summary query; ~4.5 ms per query warm (lemma pays the same).
- Hint pollution: WordNet expands function-adjacent words —
  "behind" → {arse, ass, buttocks, …} — 16 hints from 4 seeds on a sample
  multi-hop question.
- Dependency weight on the default path: `lede-spacy[synonyms]` + nltk.

## Verdict

**Default flipped `moderate` → `off`.** Quality-neutral on both corpora,
real per-query and cold-start cost, noisy hints. All tiers remain opt-in
(`PGRG_QUERY_EXPANSION` / `query_expansion=`); `aggressive` still degrades
to `moderate` without a vector model. Consistent with stele's cross-domain
finding ("hints don't matter — none ≈ query ≈ expanded, within noise").

Re-run this sweep before changing the default again; the drift guard is
`tests/unit/test_summary_hints.py::test_query_expansion_default_is_off`.
