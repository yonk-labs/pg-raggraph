-- Per-fact temporal columns on `relationships`.
--
-- Mirrors the document-level evolution-tracking columns from migration 002
-- (effective_from / effective_to / retracted / retracted_at on `documents`),
-- but applied at the fact granularity. Pattern M's chunkshop SP-A bridge
-- emits typed SPO triples with `effective_from`, `effective_to`,
-- `retracted`, `retracted_at` per fact — pre-#6, those fields were stashed
-- in the chunk's JSONB metadata only (queryable but not ranking-active).
-- This migration gives them a typed home on the relationship row.
--
-- All columns nullable. Existing relationships (extracted-default chunkshop,
-- LLM-extraction without temporal info, manual known_relationships) keep
-- NULL across the board and behave identically to pre-#6.
--
-- See docs/cookbook/chunkshop-integration.md → Pattern M.

ALTER TABLE relationships
    ADD COLUMN IF NOT EXISTS effective_from TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS effective_to   TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS retracted      BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS retracted_at   TIMESTAMPTZ;

-- Helpful index for retraction-filter queries — narrow to the small set
-- of rows that have it set, since most relationships won't be retracted.
CREATE INDEX IF NOT EXISTS idx_relationships_retracted
    ON relationships(namespace)
    WHERE retracted = TRUE;

-- Helpful index for as_of-style temporal-window scans.
CREATE INDEX IF NOT EXISTS idx_relationships_effective
    ON relationships(effective_from, effective_to)
    WHERE effective_from IS NOT NULL;
