# Factorial Chunking × Embedding Probe Report

Generated: 2026-04-19T17:49:08

Corpus: scotus (772 docs ingested)


## 12-row table (sorted by avg rank of first gold across 3 failing probes)

| chunking | embedding | n_chunks | avg_rank_failing | q-004 rank | q-008 rank | q-025 rank | q-018 rank (control) |
|---|---|---|---|---|---|---|---|
| B | bge-small | 1107 | 1.0 | 1 | 1 | 1 | 1 |
| B | bge-base | 1107 | 1.0 | 1 | 1 | 1 | 1 |
| C | bge-small | 772 | 1.0 | 1 | 1 | 1 | 1 |
| C | bge-base | 772 | 1.0 | 1 | 1 | 1 | 1 |
| C | nomic | 772 | 1.0 | 1 | 1 | 1 | 1 |
| D | bge-base | 816 | 1.0 | 1 | 1 | 1 | 1 |
| B | nomic | 1107 | 1.3 | 1 | 1 | 2 | 1 |
| A | bge-base | 816 | 1.7 | 1 | 3 | 1 | 1 |
| A | bge-small | 816 | 3.0 | 5 | 1 | 3 | 1 |
| A | nomic | 816 | 3.0 | 6 | 1 | 2 | 1 |
| D | bge-small | 816 | 3.3 | 6 | 1 | 3 | 1 |
| D | nomic | 816 | 3.3 | 7 | 1 | 2 | 1 |

## Decision

Baseline (A/bge-small) required_facts_matched across failing probes: **6**
Best cell (B/bge-small) matched: **7**  (delta=+1)

DECISION: NO_LIFT_NEXT=ENTITY_DRILL
