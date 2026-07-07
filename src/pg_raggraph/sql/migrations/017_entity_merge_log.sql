-- Entity-merge audit log (AAT-004).
--
-- Fuzzy resolution (combined trgm+vector >= resolution_threshold) merges an
-- incoming entity into an existing row with no record and no undo — a false
-- merge ("PostgreSQL 14" absorbed into "PostgreSQL 15") silently corrupts
-- the graph and is unrecoverable short of full re-ingest. This table records
-- every fuzzy auto-merge (resolve_entity) and every manual merge
-- (rag.merge_entities), including the scores that triggered it and what the
-- absorbed entity looked like, so merges are auditable
-- (rag.entity_merges() / `pgrg merges`) and individually repairable
-- (rag.split_entity(log_id) recreates the absorbed entity).
--
-- Deliberately a table, not a properties JSONB array on the survivor: hub
-- entities merge often, and an unbounded array on the row is the same growth
-- bug PR-222 caps for descriptions. No FKs — the log must outlive the
-- entities and documents it describes.

CREATE TABLE IF NOT EXISTS entity_merge_log (
    id BIGSERIAL PRIMARY KEY,
    namespace TEXT NOT NULL,
    kept_id BIGINT NOT NULL,             -- surviving entities.id
    merged_entity_id BIGINT,             -- manual merges only; auto-merged
                                         -- candidates never got their own row
    merged_name TEXT NOT NULL,
    merged_type TEXT,
    merged_description TEXT,
    merged_properties JSONB NOT NULL DEFAULT '{}'::jsonb,
    trgm_score REAL,                     -- NULL for manual merges
    vec_score REAL,
    combined_score REAL,
    source TEXT NOT NULL DEFAULT 'auto', -- 'auto' | 'manual'
    document_id BIGINT,                  -- ingest provenance, when known
    merged_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_entity_merge_log_ns_at
    ON entity_merge_log (namespace, merged_at DESC);

-- --- RLS parity (migration 003/016 pattern) --------------------------------
-- resolve_entity writes this table during every ingest, so the app role
-- needs grants or RLS deployments break on the next fuzzy merge.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'pgrg_app') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON entity_merge_log TO pgrg_app;
        GRANT USAGE, SELECT ON SEQUENCE entity_merge_log_id_seq TO pgrg_app;
    END IF;
END $$;

ALTER TABLE entity_merge_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE entity_merge_log FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS ns_isolation ON entity_merge_log;
CREATE POLICY ns_isolation ON entity_merge_log
    USING (pgrg_tenant() IS NULL OR namespace = pgrg_tenant());
