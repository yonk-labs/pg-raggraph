-- Prevents duplicate edges in `relationships`.
--
-- Why now: the background-extraction work (migration 012 + backfill.py)
-- introduces a code path where a 'processing' doc can be re-claimed and
-- re-extracted under a crash-recovery scenario. Without a unique constraint
-- on (namespace, src_id, dst_id, rel_type), re-extraction would silently
-- duplicate relationship rows — and graph-traversal scoring would
-- double-count those edges.
--
-- Pre-existing rows are de-duplicated first (keep the lowest id per
-- (namespace, src_id, dst_id, rel_type) group). relationship_chunks links
-- pointing at duplicates are redirected to the keeper via
-- INSERT…SELECT…ON CONFLICT DO NOTHING so the PK on
-- (relationship_id, chunk_id) isn't violated when both the dup and the
-- keeper already linked to the same chunk. The duplicate rows are then
-- dropped, which cascades the now-stale chunk links via the existing
-- ON DELETE CASCADE on relationship_chunks → relationships.
--
-- After this migration:
--   * `_ingest_one_content` and `_extract_one` use
--     `ON CONFLICT (namespace, src_id, dst_id, rel_type) DO UPDATE
--      SET weight = GREATEST(...)`, so concurrent / repeat extraction
--     is idempotent at the edge level.
--   * The remaining "duplicate edges silently" risk identified in
--     prod-ready GAP-014 is closed.

-- Step 1: redirect chunk links from duplicate rels to the keeper. Both the
-- keeper and the dup may already have a row for the same chunk_id — that's
-- the PK collision the ON CONFLICT clause guards against.
INSERT INTO relationship_chunks (relationship_id, chunk_id, confidence, provenance)
SELECT d.keep_id, rc.chunk_id, rc.confidence, rc.provenance
FROM relationship_chunks rc
JOIN (
    SELECT
        id,
        min(id) OVER (PARTITION BY namespace, src_id, dst_id, rel_type) AS keep_id
    FROM relationships
) d ON d.id = rc.relationship_id
WHERE d.id <> d.keep_id
ON CONFLICT (relationship_id, chunk_id) DO NOTHING;

-- Step 2: delete the duplicate relationships. ON DELETE CASCADE on
-- relationship_chunks.relationship_id cleans the leftover chunk links.
DELETE FROM relationships r
USING (
    SELECT
        id,
        min(id) OVER (PARTITION BY namespace, src_id, dst_id, rel_type) AS keep_id
    FROM relationships
) d
WHERE r.id = d.id AND d.id <> d.keep_id;

-- Step 3: prevent future duplicates. ON CONFLICT in application INSERTs
-- needs this constraint to exist by name or column list.
ALTER TABLE relationships
    ADD CONSTRAINT relationships_ns_edge_unique
    UNIQUE (namespace, src_id, dst_id, rel_type);
