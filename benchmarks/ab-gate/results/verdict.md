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
| Recall@10 | 0.8750 | 0.0417 | -83.33pp | NAIVE_WINS |
| MRR | 0.6229 | 0.0417 | -0.5813 | NAIVE_WINS |
| Judge win-rate | 0.9167 | 0.2083 | -0.7083 | NAIVE_WINS |

## Per-corpus breakdown

### bakeoff-ntsb-ab

| Metric | Naive | Graph | Delta | Label |
|---|---|---|---|---|
| Recall@10 | 1.0000 | 0.0833 | -91.67pp | NAIVE_WINS |
| MRR | 0.8403 | 0.0833 | -0.7569 | NAIVE_WINS |
| Judge win-rate | 1.0000 | 0.0833 | -0.9167 | NAIVE_WINS |

### bakeoff-scotus-ab

| Metric | Naive | Graph | Delta | Label |
|---|---|---|---|---|
| Recall@10 | 0.7500 | 0.0000 | -75.00pp | NAIVE_WINS |
| MRR | 0.4056 | 0.0000 | -0.4056 | NAIVE_WINS |
| Judge win-rate | 0.8333 | 0.3333 | -0.5000 | NAIVE_WINS |

## Verdict computation walkthrough

```
Recall@10 lift: -83.33pp → NAIVE_WINS
MRR delta: -0.5813 → NAIVE_WINS
Judge win-rate delta: -0.7083 → NAIVE_WINS
§3.3 combiner: NAIVE_WINS
```

## Final verdict

**NAIVE_WINS**
