# fp32 vs int8 Factorial Comparison

Accuracy wall time: fp32 180.3s  |  int8 180.1s
LLM cost: fp32 $0.5828  |  int8 $0.5793

## TL;DR

Total fully_correct across all 12 cells: fp32 = **152**, int8 = **160**, delta = **+8** out of 360.

## Per-cell comparison (sorted by int8 fully_correct desc)

| chunking | embedding | fp32 fc | int8 fc | Δfc | fp32 partial | int8 partial | fp32 avg_rank | int8 avg_rank |
|---|---|---|---|---|---|---|---|---|
| C | bge-small | 15 | 18 | +3 | 10 | 8 | 1.3 | 1.0 |
| C | bge-base | 16 | 17 | +1 | 8 | 9 | 1.0 | 1.0 |
| C | nomic | 18 | 17 | -1 | 9 | 10 | 1.0 | 1.0 |
| D | bge-base | 11 | 14 | +3 | 8 | 4 | 1.0 | 1.0 |
| A | bge-base | 12 | 13 | +1 | 7 | 4 | 1.7 | 1.7 |
| B | bge-base | 11 | 13 | +2 | 5 | 3 | 1.0 | 1.0 |
| B | bge-small | 12 | 13 | +1 | 4 | 3 | 1.3 | 1.0 |
| A | nomic | 11 | 12 | +1 | 7 | 8 | 3.0 | 3.0 |
| D | bge-small | 12 | 12 | +0 | 5 | 6 | 5.0 | 3.3 |
| B | nomic | 12 | 11 | -1 | 5 | 6 | 1.0 | 1.3 |
| A | bge-small | 12 | 10 | -2 | 6 | 5 | 4.3 | 3.0 |
| D | nomic | 10 | 10 | +0 | 8 | 7 | 3.3 | 3.3 |

## Decision

- fp32 best: **C/nomic** (18/30 fully_correct)
- int8 best: **C/bge-small** (18/30 fully_correct)

**DECISION: INT8_SAFE_TO_SHIP  (int8 best >= fp32 best, Δ=+0)**

