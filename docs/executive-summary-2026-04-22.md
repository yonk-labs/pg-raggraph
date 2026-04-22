# pg-raggraph — Executive Summary

**Date:** 2026-04-22
**Scope:** single-day session covering chunker bug fix, medical benchmark v2 + v1 retraction, and evolving-knowledge-RAG design spec.

## Headline

Found and fixed a silent chunker bug that invalidated our flagship medical benchmark. Shipped the corrected result (no clean winner — both engines tie at 66/100), and landed a strategic design spec for **evolving-knowledge RAG** — a product direction with few competitors and broad applicability (medical, software docs, legal, compliance, agent memory).

## What happened

**Bug.** The `hierarchy` chunker emitted raw section bodies up to 134 KB. fastembed silently truncates at 512 tokens (~2 KB) — so 98% of each topic's content was invisible to vector retrieval. Compounding this, our local Qwen judge was ~10 pp more lenient than gpt-5-mini. The v1 headline "pg-raggraph/hybrid 73 vs AGE/hybrid 66" was the product of these two defects.

**Fix.** Both pg-raggraph and the bakeoff chunkers now cap at `chunk_max_tokens`. Added a dual content primitive (raw body for audit, decorated body for the embedder/FTS) as foundation for future enhancements. 216 tests green across both repos.

**Re-run.** Full 8-mode × engine × 100-question matrix on gpt-5-mini end-to-end. $27-28 spend, 6h52m wall time. Result: pgrg modes 59-66, AGE modes 63-66, **both top out at 66.** pg-raggraph's hybrid mode (63) underperforms its own simpler modes (64-66) — weight calibration needs work.

**Pivot.** User reframed MAGMA (ACL 2026) from "agent memory" to "any evolving knowledge base." Current RAG treats knowledge as static, but real KBs evolve — medical retractions, software version drift, legal precedent overturning, policy revisions. Shipped a 4,600-word design spec for fact-level graph extension with temporal decay, supersession, retraction handling, and contradiction detection. Four-tier cost/capability model ($0 metadata-only through full LLM-inferred fact graph); 10-12 week phased plan with shippable Tier 1 alpha in ~4 weeks.

## Outcomes (3 commits on main)

| SHA | What |
|---|---|
| `db41a74` | Evolving-knowledge RAG design spec |
| `58d8c1d` | Chunker cap + dual content primitive |
| `a935555` | Medical v2 matrix + v1 retraction |

Two confidence-tightening runs still executing in background; ~$3-4 marginal cost, done by ~19:30 today.

## Key decisions

- **Retracted** the v1 benchmark headline. Honest > marketable.
- **Evolving-knowledge** is a pg-raggraph core upgrade, not a sibling library. Every real KB evolves.
- **4-tier model** for graceful cost/capability tradeoffs. $0 tier exists for metadata-rich callers (PubMed, CMS effective dates, `package.json` versions).
- **Zero-breaking-change API.** Facts ride as sidecar on chunks; existing callers keep working.
- **Tier 1 alpha ships in ~4 weeks.** Tier 2/3 are additive.

## Risks & open items

- **Hybrid mode loses to naive_boost on medical.** Hybrid weight defaults were tuned on SCOTUS. A `tune_scoring_weights()` utility is on the Tier 1 plan.
- **Single-run confidence bands (±3 pp).** Background n=3 re-runs address the headline comparisons.
- **chunkshop (sibling) parallel fix in flight.** Alignment verification due when their session lands.

## Forward look

| Horizon | What |
|---|---|
| **This week** | Finish n=3 tightening; update paper; start Phase 1 implementation plan. |
| **~4 weeks** | Tier 1 alpha: schema + metadata contract + SQL scoring + `as_of` / `version_filter` kwargs + weight-tuning utility. Ships medical-retraction, software-versioning, and policy-compliance use cases at zero LLM cost. |
| **~12 weeks** | Tier 3 beta: LLM-inferred fact edges, contradiction detection, full auto-inference path. Unlocks scientific-consensus and agent-memory use cases. |

## Positioning

No other open-source RAG library tracks temporal validity, retraction, or supersession as first-class primitives. LightRAG, GraphRAG, HippoRAG all assume static corpora. This is a defensible differentiator for pg-raggraph if shipped carefully. The reframe from "agent memory" to "evolving knowledge" broadens the addressable market from "long-horizon agents" to "any serious enterprise KB" — medical, legal, compliance, developer tooling, research.

## Artifacts

- Design spec: `docs/superpowers/specs/2026-04-22-evolving-knowledge-rag-design.md`
- Medical benchmark v2 paper (with v1 retraction): `docs/benchmarks/graphrag-bench-medical.md`
- Chunker fix commit: `58d8c1d`
- V1 broken-chunker artifacts preserved as `*__hybrid.v1_broken_chunker.json` across raw / judge / extraction cache
