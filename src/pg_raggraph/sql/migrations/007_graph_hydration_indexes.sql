-- Speed graph hydration after vector retrieval.
--
-- Retrieval fetches chunk IDs, then hydrates entities/relationships with
-- `entity_chunks WHERE chunk_id = ANY(...)`. The primary key is
-- `(entity_id, chunk_id)`, which does not serve that access pattern. Without
-- this index, large benchmark/production corpora can fall back to broad scans
-- during every graph-mode query.

CREATE INDEX IF NOT EXISTS idx_entity_chunks_chunk
    ON entity_chunks(chunk_id);
