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
| 4 | 2026-04-27 | USE-CASES.md + 3-part dev-rel blog series (no LLM calls) | n/a | n/a | $0.00 | ~$1.70 |

**Running total: ~$1.70 / $25.00 — DC-FINAL CLEARED 2026-04-27**

## DC-FINAL evidence summary (2026-04-27)

| SC | Evidence | Status |
|----|----------|--------|
| SC-001 | benchmarks/regressions/results/2026-04-27-regression.md (175p+1xf, 3:04 wall) | PASS |
| SC-002 | v0.3.0a0 tag reachable from main; merge commit c4dc4ab | PASS |
| SC-003 | tests/integration/test_python_versioned_docs.py (2/2 passed) | PASS |
| SC-004 | benchmarks/python-versioned-docs/results.md — 13/13 filter purity, 14/15 overall | PASS |
| SC-005 | tests/integration/test_medical_hrt.py (2/2 passed; synthetic fixture untouched) | PASS |
| SC-006 | benchmarks/medical-hrt/results.md — 5/5 retraction + 5/5 time-travel, 15/15 perfect | PASS |
| SC-007 | docs/USE-CASES.md + cross-links from README + user-guide | PASS |
| SC-008 | docs/blog/{01,02,03}-*.md, zero placeholders, reproducibility verified | PASS |
| SC-009 | ~$1.70 cumulative cost (32× under cap) | PASS |
