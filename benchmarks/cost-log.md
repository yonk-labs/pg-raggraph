# pg-raggraph cost log — Tier 1 real-bench + tutorial effort

Mission brief: `skill-output/mission-brief/Mission-Brief-tier1-real-bench-tutorial.md`
Cost cap (SC-009): **$25.00 USD**

| Phase | Date | Activity | Model | Tokens (in/out) | Cost USD | Cumulative |
|-------|------|----------|-------|-----------------|----------|------------|
| 1 | 2026-04-27 | pytest sanity (175p+1xf, 3:04 wall) — pivoted from accuracy regression, no LLM calls | n/a | n/a | $0.00 | $0.00 |
| 1 | 2026-04-27 | post-merge pytest on main (175p+1xf, 2:50 wall) | n/a | n/a | $0.00 | $0.00 |
| 2 | 2026-04-27 | python-versioned-docs ingest (1364 chunks, ~45min wall, some extraction retries) | gpt-4o-mini (extraction) | est. ~6M/~600K | ~$1.50 | ~$1.50 |
| 2 | 2026-04-27 | path A runner (15 Qs, naive_boost retrieval only — no LLM in answer path) | n/a | n/a | $0.00 | ~$1.50 |
| 3 | 2026-04-27 | medical-hrt download via NCBI eutils (56 abstracts, 252K) | n/a | n/a | $0.00 | ~$1.50 |
| 3 | 2026-04-27 | medical-hrt ingest (48 abstracts → ~120 chunks, some extraction retries) | gpt-4o-mini (extraction) | est. ~600K/~60K | ~$0.20 | ~$1.70 |
| 3 | 2026-04-27 | path B runner (15 Qs, naive_boost retrieval only — no LLM in answer path) | n/a | n/a | $0.00 | ~$1.70 |

**Running total: ~$1.70 / $25.00**
