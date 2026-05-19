-- Recreate HNSW indexes with explicit pgvector defaults.
--
-- Operators can tune query-time search breadth with PGRG_HNSW_EF_SEARCH.
-- Build-time m/ef_construction remain database DDL concerns; this migration
-- records the default values explicitly. For non-default build params, run a
-- measured REINDEX/CREATE INDEX CONCURRENTLY maintenance window.

DROP INDEX CONCURRENTLY IF EXISTS idx_chunk_embed;
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_chunk_embed
  ON chunks USING hnsw (embedding vector_cosine_ops)
  WITH (m = {hnsw_m}, ef_construction = {hnsw_ef_construction});

DROP INDEX CONCURRENTLY IF EXISTS idx_entity_embed;
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_entity_embed
  ON entities USING hnsw (embedding vector_cosine_ops)
  WITH (m = {hnsw_m}, ef_construction = {hnsw_ef_construction});
