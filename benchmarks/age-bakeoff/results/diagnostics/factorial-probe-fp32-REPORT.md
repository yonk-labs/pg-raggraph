# Factorial Chunking × Embedding Probe Report

Generated: 2026-04-19T16:18:36

Corpus: scotus (772 docs ingested)


## 12-row table (sorted by avg rank of first gold across 3 failing probes)

| chunking | embedding | n_chunks | avg_rank_failing | q-004 rank | q-008 rank | q-025 rank | q-018 rank (control) |
|---|---|---|---|---|---|---|---|
| B | bge-base | 1107 | 1.0 | 1 | 1 | 1 | 1 |
| B | nomic | 1107 | 1.0 | 1 | 1 | 1 | 1 |
| C | bge-base | 772 | 1.0 | 1 | 1 | 1 | 1 |
| C | nomic | 772 | 1.0 | 1 | 1 | 1 | 1 |
| D | bge-base | 816 | 1.0 | 1 | 1 | 1 | 1 |
| B | bge-small | 1107 | 1.3 | 1 | 1 | 2 | 1 |
| C | bge-small | 772 | 1.3 | 1 | 1 | 2 | 1 |
| A | bge-base | 816 | 1.7 | 1 | 3 | 1 | 1 |
| A | nomic | 816 | 3.0 | 7 | 1 | 1 | 1 |
| D | nomic | 816 | 3.3 | 8 | 1 | 1 | 1 |
| A | bge-small | 816 | 4.3 | 10 | 1 | 2 | 1 |
| D | bge-small | 816 | 5.0 | 11 | 1 | 3 | 1 |

## Decision

Baseline (A/bge-small) required_facts_matched across failing probes: **6**
Best cell (B/bge-base) matched: **8**  (delta=+2)

DECISION: ADOPT_CELL=B/bge-base
