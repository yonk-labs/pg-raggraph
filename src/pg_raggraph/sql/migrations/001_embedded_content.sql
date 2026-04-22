-- 001_embedded_content.sql
-- Add a second text field to chunks so the embedder / FTS can see one thing
-- (e.g., heading + body in hierarchy strategy, or glued neighbors when
-- neighbor_expand lands) while the raw body stays available in `content` for
-- audit, grep, and provenance.
--
-- Semantics after this migration:
--   content          = raw chunk body (what grep / audit / provenance sees)
--   embedded_content = what was embedded + indexed by FTS (may include
--                      heading prefix, glued neighbors, summary, etc.)
--
-- For existing rows we backfill `embedded_content := content`, which keeps the
-- FTS index bit-identical until re-ingested under the new chunker.

ALTER TABLE chunks ADD COLUMN IF NOT EXISTS embedded_content TEXT;

UPDATE chunks SET embedded_content = content WHERE embedded_content IS NULL;

-- Re-wire FTS to index embedded_content so heading text (hierarchy strategy)
-- is reachable by BM25 queries. The search_vector regenerates on the next
-- UPDATE to embedded_content on each row, which the backfill UPDATE above
-- already triggered.
CREATE OR REPLACE FUNCTION pgrg_update_search_vector() RETURNS trigger AS $$
BEGIN
    NEW.search_vector := to_tsvector('english', COALESCE(NEW.embedded_content, NEW.content));
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_chunk_search_vector ON chunks;
CREATE TRIGGER trg_chunk_search_vector
    BEFORE INSERT OR UPDATE OF content, embedded_content ON chunks
    FOR EACH ROW EXECUTE FUNCTION pgrg_update_search_vector();
