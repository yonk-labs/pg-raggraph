-- 002_evolution_tracking.sql
-- Evolving-knowledge-RAG foundational DDL. Adds three new tables and four
-- columns on documents. All new signals are optional (nullable / default
-- false) so existing Tier 0 / Tier-off installations see no behavior change.
--
-- Tier 1 populates: documents.{effective_from, effective_to, retracted,
--   version_label, supersedes_document_id via document_versions}.
-- Tier 2 populates: facts (via skimr+spaCy).
-- Tier 3 populates: fact_edges (via async LLM slow path).
--
-- All three fact_* tables land at Tier 1 but stay empty until Tier 2/3 are
-- enabled — this avoids a second schema change when tiers ramp up.

ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS effective_from TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS effective_to   TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS retracted      BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS version_label  TEXT;

CREATE INDEX IF NOT EXISTS idx_doc_effective_from ON documents(effective_from);
CREATE INDEX IF NOT EXISTS idx_doc_retracted ON documents(retracted) WHERE retracted;
CREATE INDEX IF NOT EXISTS idx_doc_version_label ON documents(version_label)
    WHERE version_label IS NOT NULL;

CREATE TABLE IF NOT EXISTS document_versions (
    id                       BIGSERIAL PRIMARY KEY,
    document_id              BIGINT REFERENCES documents(id) ON DELETE CASCADE,
    version_label            TEXT,
    effective_from           TIMESTAMPTZ,
    effective_to             TIMESTAMPTZ,
    supersedes_document_id   BIGINT REFERENCES documents(id) ON DELETE SET NULL,
    retracted                BOOLEAN DEFAULT FALSE,
    retracted_at             TIMESTAMPTZ,
    retraction_reason        TEXT,
    metadata                 JSONB DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_docver_document ON document_versions(document_id);
CREATE INDEX IF NOT EXISTS idx_docver_supersedes ON document_versions(supersedes_document_id);

CREATE TABLE IF NOT EXISTS facts (
    id                 BIGSERIAL PRIMARY KEY,
    namespace          TEXT NOT NULL,
    source_chunk_id    BIGINT REFERENCES chunks(id) ON DELETE CASCADE,
    subject            TEXT NOT NULL,
    subject_entity_id  BIGINT REFERENCES entities(id) ON DELETE SET NULL,
    predicate          TEXT NOT NULL,
    object             TEXT NOT NULL,
    object_entity_id   BIGINT REFERENCES entities(id) ON DELETE SET NULL,
    support_span       TEXT NOT NULL,
    confidence         FLOAT DEFAULT 1.0,
    effective_from     TIMESTAMPTZ,
    effective_to       TIMESTAMPTZ,
    retracted          BOOLEAN DEFAULT FALSE,
    retracted_at       TIMESTAMPTZ,
    retraction_reason  TEXT,
    extractor          TEXT NOT NULL DEFAULT 'unknown',
    properties         JSONB DEFAULT '{}',
    created_at         TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_facts_ns_source ON facts(namespace, source_chunk_id);
CREATE INDEX IF NOT EXISTS idx_facts_subject_entity ON facts(subject_entity_id);
CREATE INDEX IF NOT EXISTS idx_facts_object_entity ON facts(object_entity_id);
CREATE INDEX IF NOT EXISTS idx_facts_effective ON facts(effective_from);
CREATE INDEX IF NOT EXISTS idx_facts_retracted ON facts(retracted) WHERE retracted;

-- Note: facts.embedding is added in Tier 2 migration (003); at Tier 1 we
-- don't embed facts yet. Keeping the Tier 1 migration vector-free avoids a
-- pgvector dimension coupling.

CREATE TABLE IF NOT EXISTS fact_edges (
    id            BIGSERIAL PRIMARY KEY,
    src_fact_id   BIGINT REFERENCES facts(id) ON DELETE CASCADE,
    dst_fact_id   BIGINT REFERENCES facts(id) ON DELETE CASCADE,
    edge_type     TEXT NOT NULL,
    confidence    FLOAT DEFAULT 1.0,
    inferred_by   TEXT NOT NULL,
    created_at    TIMESTAMPTZ DEFAULT now(),
    UNIQUE (src_fact_id, dst_fact_id, edge_type)
);

CREATE INDEX IF NOT EXISTS idx_fact_edges_src ON fact_edges(src_fact_id, edge_type);
CREATE INDEX IF NOT EXISTS idx_fact_edges_dst ON fact_edges(dst_fact_id, edge_type);
