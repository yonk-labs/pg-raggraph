# docs/archive/

Dated session reports, internal strategy decisions, design specs, and implementation plans that are kept here for **audit-trail** purposes — not as user-facing documentation.

If you want to understand a current feature or API, start in [`../user-guide.md`](../user-guide.md) or [`../USE-CASES.md`](../USE-CASES.md). Documents in this folder are time-stamped and reflect the state of the project at the time they were written; they may reference code paths or behaviors that have since changed.

## What's here and why

### Project meta
- `PROJECT.md` — Original one-liner + core values vision doc.
- `TODO.md` — Cross-session handoff log (last update 2026-04-20). The current backlog lives in commit history + the post-audit closure narrative in `CHANGELOG.md`.

### Dated session reports / decisions
- `executive-summary-2026-04-22.md` — Single-day session covering chunker bug fix + medical benchmark v2.
- `graph-direction-decision.md` — 2026-04-20 strategy decision (T-G1) on whether to keep the graph approach. Outcome: keep tables, demote graph-augmented retrieval modes in positioning. Already reflected in current docs.
- `smart-mode-plan.md` — Implementation plan for `smart` retrieval mode + `pgrg devmem`. Both shipped in 0.3.0a0.
- `chunkshop-integration.md` — 2026-04-20 note documenting that pg-raggraph does not depend on the chunkshop sibling library at runtime; chunkshop is experimentation surface only.

### Implementation plans (`superpowers/plans/`)
- `2026-04-14-age-bakeoff-benchmark.md`
- `2026-04-17-bakeoff-followup.md`
- `2026-04-19-chunkshop-ingestion-tool.md`
- `2026-04-19-factorial-chunking-embedding.md`
- `2026-04-23-evolving-knowledge-rag-phase1-tier1.md`
- `2026-04-27-tier1-real-bench-tutorial.md`

### Design specs (`superpowers/specs/`)
- `2026-04-22-evolving-knowledge-rag-design.md` — Tier-1 / Tier-2 / Tier-3 evolution-tracking architecture spec. Tier-1 shipped in 0.3.0a0; Tier-2 / Tier-3 remain on the roadmap.

## Why a separate folder

The main `docs/` tree is for documentation a current user actually needs. These files are useful when you're answering "how did we end up here?" — not "how do I use this?" Splitting them out keeps the live docs clean and the audit trail intact.
