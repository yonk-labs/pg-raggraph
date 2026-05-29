# A/B Gate Verdict

> Computed per chunkshop emission contract §3 (combiner) + §3.4 (asymmetry guard).

## Inputs

| Corpus | Modes seen |
|---|---|
| bakeoff-ntsb-ab | naive_vector, graph_leg |
| bakeoff-scotus-ab | naive_vector, graph_leg |

## Per-metric deltas

| Metric | Naive | Graph | Delta | Label |
|---|---|---|---|---|
| Recall@10 | 0.8750 | 0.7500 | -12.50pp | NAIVE_WINS |
| MRR | 0.6229 | 0.5104 | -0.1125 | NAIVE_WINS |
| Judge win-rate | 0.9167 | 0.8750 | -0.0417 | TIE |

## Per-corpus breakdown

### bakeoff-ntsb-ab

| Metric | Naive | Graph | Delta | Label |
|---|---|---|---|---|
| Recall@10 | 1.0000 | 0.9167 | -8.33pp | NAIVE_WINS |
| MRR | 0.8403 | 0.7153 | -0.1250 | NAIVE_WINS |
| Judge win-rate | 1.0000 | 0.9167 | -0.0833 | TIE |

### bakeoff-scotus-ab

| Metric | Naive | Graph | Delta | Label |
|---|---|---|---|---|
| Recall@10 | 0.7500 | 0.5833 | -16.67pp | NAIVE_WINS |
| MRR | 0.4056 | 0.3056 | -0.1000 | NAIVE_WINS |
| Judge win-rate | 0.8333 | 0.8333 | +0.0000 | TIE |

## Verdict computation walkthrough

```
Recall@10 lift: -12.50pp → NAIVE_WINS
MRR delta: -0.1125 → NAIVE_WINS
Judge win-rate delta: -0.0417 → TIE
§3.3 combiner: NAIVE_WINS
```

## Final verdict

**NAIVE_WINS**
