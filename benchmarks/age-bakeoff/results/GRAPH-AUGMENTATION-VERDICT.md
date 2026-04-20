# Graph augmentation: does pg-raggraph's graph layer add signal under good chunks?

**Dataset:** SCOTUS, 30 gold-labeled questions × 3 runs = 90 Q-runs per engine per mode.
**Embedder:** BAAI/bge-small-en-v1.5 (512-token context, same across all rows).
**Answer model / Judge model:** gpt-5-mini (answer), gpt-5-mini (judge), majority-of-3 verdict.
**Run date:** 2026-04-19.

## The 8-row table

| # | engine | chunker         | retrieval                      | fully_correct / 30 | source                         |
|---|--------|-----------------|--------------------------------|--------------------|--------------------------------|
| 1 | pgrg   | sentence_aware  | hybrid (pgrg baseline)         | **10 / 30**        | `results/judge/scotus.json`    |
| 2 | pgrg   | sentence_aware  | pure pgvector (factorial A/bge-small) | **12 / 30** | `factorial-accuracy-fp32.json` (cell `a_bge_small`) |
| 3 | pgrg   | hierarchy       | pure pgvector (factorial C/bge-small) | **15 / 30** | `factorial-accuracy-fp32.json` (cell `c_bge_small`) |
| 4 | pgrg   | hierarchy       | **hybrid**                     | **18 / 30**        | `results/judge/scotus__hier_hybrid.json` |
| 5 | pgrg   | hierarchy       | **smart**                      | **17 / 30**        | `results/judge/scotus__hier_smart.json` |
| 6 | pgrg   | hierarchy       | **local**                      | **18 / 30**        | `results/judge/scotus__hier_local.json` |
| 7 | pgrg   | hierarchy       | **global**                     | **18 / 30**        | `results/judge/scotus__hier_global.json` |
| 8 | pgrg   | hierarchy       | **naive_boost**                | **17 / 30**        | `results/judge/scotus__hier_naive_boost.json` |

Plus a complementary row from the same sweep, relevant to the verdict:

| bonus | pgrg | hierarchy | **naive (pure pgrg vector, no graph)** | **18 / 30** | `results/judge/scotus__hier_naive.json` |

(Row 2 and row 3 use `bge-small` to keep the embedder consistent with the bake-off. The handoff mentions the 18/30 figure — that comes from factorial `c_nomic`, a stronger embedder. Under the bake-off's fixed `bge-small`, the pure-pgvector hierarchy ceiling is `c_bge_small` = 15/30.)

## What the numbers say

**Hierarchy chunking clears DC-003 by 2.5×.** Every hierarchy row lifts pgrg's fully-correct count from 10/30 to 17 or 18/30 — +7 to +8 questions, versus the +3-question (+10 pp) DC-003 threshold. The chunker, not the retrieval engine, is the lever that actually moved accuracy.

**Graph augmentation adds ZERO signal on top of good chunks.** Compare rows 4–8 to the bonus row:

- `pgrg / hierarchy / hybrid` (vector + graph + BM25): **18 / 30**
- `pgrg / hierarchy / local` (entity graph expansion):  **18 / 30**
- `pgrg / hierarchy / global` (community summaries):    **18 / 30**
- `pgrg / hierarchy / naive` (pure pgvector, no graph): **18 / 30**
- `pgrg / hierarchy / smart`, `naive_boost`:            **17 / 30**

The fanciest retrieval (hybrid, global) ties the simplest (naive). The confidence-triggered smart router and the 1-hop-boost `naive_boost` actually *underperformed* pure vector by 1 question. Within the ±1 noise band typical of a 30-Q eval, every mode is a tie.

**Graph augmentation was, however, worth +3 over pure pgvector SQL.** Row 3 (`c_bge_small` = 15/30) used raw `ORDER BY embedding <=> query LIMIT 10` against the same hierarchy-chunked data. pgrg/naive/hier scored 18/30 on the same embedder. That +3 delta is not from the graph layer (naive doesn't use it); it's from pgrg's answer-generation plumbing — chunk deduplication, context assembly, the answer-only-from-context prompt discipline. That's a library benefit, not a graph benefit.

## The honest one-line verdict

> **Good chunks neutralize the graph layer's value on this dataset.** Hierarchy chunking makes the retrieval-mode choice a coin toss. pgrg's graph features (local, global, hybrid, smart, naive_boost) are not a retrieval advantage when the chunker already surfaces the right passage — they're expensive ways to tie pure vector.

## Implications for the product

1. **Ship hierarchy as the pgrg default chunker for prose.** Every use case in the SCOTUS test suite benefits; zero regressions.
2. **Demote graph modes from "core feature" to "advanced option."** Document them as useful when chunks are weak (short messages, adversarial document structure, multi-doc bridging questions where the answer is in no single chunk) — not as the default path.
3. **`smart` mode needs revisiting.** Its confidence-based routing is supposed to beat naive by escalating only when needed; instead it underperforms naive by 1 question. Either the confidence heuristic is miscalibrated at the 18/30 operating point, or the escalation path adds friction. Neither is a reason to keep it as default.
4. **Stop benchmarking retrieval in isolation.** The factorial probe (`c_bge_small` = 15/30) understated the same-chunker-same-embedder ceiling by 3 questions because it skipped pgrg's answer-generation pipeline. Always measure end-to-end accuracy, not just top-k-contains-gold-chunk retrieval rank.

## Caveats

- **Single dataset.** SCOTUS is 772 short legal cases with explicit case names in the title. The hierarchy chunker's title-prefix fallback is tailor-made for this shape. On document corpora with no useful title (raw PDF extractions, log dumps, scraped HTML without `<title>`), hierarchy buys nothing and graph augmentation might resurface. Need a second-corpus replication before calling this universal.
- **Question class mix matters.** These 30 questions include single-hop factual, semantic, and multi-hop bridging classes. If the sample skewed toward questions whose answers live in a single chunk, naive retrieval would naturally dominate. Per-class breakdown is in `results/REPORT.md`.
- **bge-small caps at 512 tokens.** 41 / 772 SCOTUS docs are >3000 chars (>~750 tokens) and get silently truncated at embed time. A bigger-context embedder (nomic) lifted factorial pure-vector from 15 to 18/30 on the same chunks. The ceiling under hierarchy isn't 18/30 — it's probably higher with a better embedder. The graph layer's marginal value might re-appear if the pure-vector ceiling rises.

## What this doesn't answer

- Whether graph augmentation adds signal on **multi-hop bridging** questions specifically (the SCOTUS set has ≥8 by design; per-class breakdown in REPORT.md would show if graph modes beat naive on that slice).
- Whether AGE's Cypher graph produces qualitatively different entity/relationship extractions than pgrg's extraction pipeline (Task 24 scope).
- Whether a different chunker — semantic, LLM-proposed, or late-chunking — would push the ceiling past 18/30 on bge-small.

## Decision

**Graph is noise when chunks are good.** Hierarchy-chunk pure pgvector retrieval (pgrg/naive/hier) is the simplest, fastest, cheapest path and ties every graph-augmented mode on SCOTUS. Ship that as the default and keep graph features as an escape hatch for the cases where naive genuinely underperforms.
