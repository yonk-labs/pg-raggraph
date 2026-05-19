-- Optional tenant isolation through PostgreSQL Row Level Security.
--
-- RLS is inert for superusers and roles with BYPASSRLS. The opt-in runtime
-- path therefore either connects directly as pgrg_app or drops each operation
-- to pgrg_app with SET LOCAL ROLE, then binds SET LOCAL app.tenant=<namespace>.
-- Without that role binding, the documented postgres superuser DSN fails open.
--
-- The policies intentionally become permissive when app.tenant is unset so
-- existing rls_enabled=false deployments keep their previous behavior.

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'pgrg_app') THEN
    CREATE ROLE pgrg_app NOSUPERUSER NOBYPASSRLS LOGIN;
  END IF;
END $$;

ALTER ROLE pgrg_app NOSUPERUSER NOBYPASSRLS LOGIN;

CREATE OR REPLACE FUNCTION pgrg_tenant() RETURNS text AS $$
  SELECT NULLIF(current_setting('app.tenant', true), '')
$$ LANGUAGE sql STABLE;

GRANT USAGE ON SCHEMA public TO pgrg_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON
  documents, chunks, entities, relationships,
  entity_chunks, relationship_chunks,
  pgrg_meta, pgrg_applied_migrations,
  document_versions, facts, fact_edges
TO pgrg_app;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM pgrg_app;
GRANT USAGE, SELECT ON SEQUENCE
  documents_id_seq,
  chunks_id_seq,
  entities_id_seq,
  relationships_id_seq,
  document_versions_id_seq,
  facts_id_seq,
  fact_edges_id_seq
TO pgrg_app;
GRANT EXECUTE ON FUNCTION pgrg_tenant() TO pgrg_app;
REVOKE ALL ON pgrg_llm_cache FROM pgrg_app;
GRANT pgrg_app TO CURRENT_USER;

ALTER TABLE documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE documents FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS ns_isolation ON documents;
CREATE POLICY ns_isolation ON documents
  USING (
    pgrg_tenant() IS NULL
    OR namespace = pgrg_tenant()
  );

ALTER TABLE entities ENABLE ROW LEVEL SECURITY;
ALTER TABLE entities FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS ns_isolation ON entities;
CREATE POLICY ns_isolation ON entities
  USING (
    pgrg_tenant() IS NULL
    OR namespace = pgrg_tenant()
  );

ALTER TABLE relationships ENABLE ROW LEVEL SECURITY;
ALTER TABLE relationships FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS ns_isolation ON relationships;
CREATE POLICY ns_isolation ON relationships
  USING (
    pgrg_tenant() IS NULL
    OR namespace = pgrg_tenant()
  );

ALTER TABLE document_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE document_versions FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS ns_isolation ON document_versions;
CREATE POLICY ns_isolation ON document_versions
  USING (
    pgrg_tenant() IS NULL
    OR namespace = pgrg_tenant()
  );

ALTER TABLE facts ENABLE ROW LEVEL SECURITY;
ALTER TABLE facts FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS ns_isolation ON facts;
CREATE POLICY ns_isolation ON facts
  USING (
    pgrg_tenant() IS NULL
    OR namespace = pgrg_tenant()
  );

ALTER TABLE chunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE chunks FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS ns_isolation ON chunks;
CREATE POLICY ns_isolation ON chunks
  USING (
    pgrg_tenant() IS NULL
    OR EXISTS (
      SELECT 1
      FROM documents d
      WHERE d.id = chunks.document_id
        AND d.namespace = pgrg_tenant()
    )
  );

ALTER TABLE entity_chunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE entity_chunks FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS ns_isolation ON entity_chunks;
CREATE POLICY ns_isolation ON entity_chunks
  USING (
    pgrg_tenant() IS NULL
    OR EXISTS (
      SELECT 1
      FROM chunks c
      JOIN documents d ON d.id = c.document_id
      WHERE c.id = entity_chunks.chunk_id
        AND d.namespace = pgrg_tenant()
    )
  );

ALTER TABLE relationship_chunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE relationship_chunks FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS ns_isolation ON relationship_chunks;
CREATE POLICY ns_isolation ON relationship_chunks
  USING (
    pgrg_tenant() IS NULL
    OR EXISTS (
      SELECT 1
      FROM chunks c
      JOIN documents d ON d.id = c.document_id
      WHERE c.id = relationship_chunks.chunk_id
        AND d.namespace = pgrg_tenant()
    )
  );

ALTER TABLE fact_edges ENABLE ROW LEVEL SECURITY;
ALTER TABLE fact_edges FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS ns_isolation ON fact_edges;
CREATE POLICY ns_isolation ON fact_edges
  USING (
    pgrg_tenant() IS NULL
    OR EXISTS (
      SELECT 1
      FROM facts src
      JOIN facts dst ON dst.id = fact_edges.dst_fact_id
      WHERE src.id = fact_edges.src_fact_id
        AND src.namespace = pgrg_tenant()
        AND dst.namespace = pgrg_tenant()
    )
  );
