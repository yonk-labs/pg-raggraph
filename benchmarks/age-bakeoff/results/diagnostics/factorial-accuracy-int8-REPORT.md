# Factorial End-to-End Accuracy Report (int8)

Generated: 2026-04-19T17:52:22  |  Model gen/judge: gpt-4.1-mini  |  Wall time: 3.0 min

Total cost: **$0.5793**

## TL;DR

Best cell: **C/bge-small** with **18/30** fully_correct (+8 vs pgrg/hybrid/gpt-4.1-mini baseline of 10/30).

Baseline (pgrg/hybrid/gpt-4.1-mini): 10 fully_correct, 7 partially_correct, 13 wrong (hybrid retrieval, same scotus corpus).

## 12-cell results (sorted by fully_correct)

| chunking | embedding | n_chunks | fully | partial | wrong | halluc | total |
|---|---|---|---|---|---|---|---|
| C | bge-small | 772 | 18 | 8 | 4 | 0 | 30 |
| C | nomic | 772 | 17 | 10 | 3 | 0 | 30 |
| C | bge-base | 772 | 17 | 9 | 4 | 0 | 30 |
| D | bge-base | 816 | 14 | 4 | 12 | 0 | 30 |
| A | bge-base | 816 | 13 | 4 | 13 | 0 | 30 |
| B | bge-small | 1107 | 13 | 3 | 14 | 0 | 30 |
| B | bge-base | 1107 | 13 | 3 | 14 | 0 | 30 |
| A | nomic | 816 | 12 | 8 | 10 | 0 | 30 |
| D | bge-small | 816 | 12 | 6 | 12 | 0 | 30 |
| B | nomic | 1107 | 11 | 6 | 13 | 0 | 30 |
| D | nomic | 816 | 10 | 7 | 13 | 0 | 30 |
| A | bge-small | 816 | 10 | 5 | 15 | 0 | 30 |

## Decision

Best cell C/bge-small: 18/30 fully_correct  (delta +8 vs hybrid baseline 10/30)

**DECISION: ADOPT_CELL=C/bge-small**

