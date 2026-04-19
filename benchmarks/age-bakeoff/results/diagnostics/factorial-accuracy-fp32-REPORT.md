# Factorial End-to-End Accuracy Report (fp32)

Generated: 2026-04-19T16:26:50  |  Model gen/judge: gpt-4.1-mini  |  Wall time: 3.0 min

Total cost: **$0.5828**

## TL;DR

Best cell: **C/nomic** with **18/30** fully_correct (+8 vs pgrg/hybrid/gpt-4.1-mini baseline of 10/30).

Baseline (pgrg/hybrid/gpt-4.1-mini): 10 fully_correct, 7 partially_correct, 13 wrong (hybrid retrieval, same scotus corpus).

## 12-cell results (sorted by fully_correct)

| chunking | embedding | n_chunks | fully | partial | wrong | halluc | total |
|---|---|---|---|---|---|---|---|
| C | nomic | 772 | 18 | 9 | 3 | 0 | 30 |
| C | bge-base | 772 | 16 | 8 | 6 | 0 | 30 |
| C | bge-small | 772 | 15 | 10 | 5 | 0 | 30 |
| A | bge-base | 816 | 12 | 7 | 11 | 0 | 30 |
| A | bge-small | 816 | 12 | 6 | 12 | 0 | 30 |
| B | nomic | 1107 | 12 | 5 | 13 | 0 | 30 |
| D | bge-small | 816 | 12 | 5 | 13 | 0 | 30 |
| B | bge-small | 1107 | 12 | 4 | 14 | 0 | 30 |
| D | bge-base | 816 | 11 | 8 | 11 | 0 | 30 |
| A | nomic | 816 | 11 | 7 | 12 | 0 | 30 |
| B | bge-base | 1107 | 11 | 5 | 14 | 0 | 30 |
| D | nomic | 816 | 10 | 8 | 12 | 0 | 30 |

## Decision

Best cell C/nomic: 18/30 fully_correct  (delta +8 vs hybrid baseline 10/30)

**DECISION: ADOPT_CELL=C/nomic**

