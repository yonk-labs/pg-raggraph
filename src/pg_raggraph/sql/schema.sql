-- pg-raggraph schema v1
-- Extensions must be created before this runs (see init.sql)

-- Meta table for schema versioning and config
CREATE TABLE IF NOT EXISTS pgrg_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- Track which migration files have been applied (prevents double-apply and
-- handles the case where two files share the same version number prefix).
-- Created here so existing installs get it via the bootstrap check in db.py.
CREATE TABLE IF NOT EXISTS pgrg_applied_migrations (
    filename TEXT PRIMARY KEY,
    version  INTEGER NOT NULL,
    applied_at TIMESTAMPTZ DEFAULT now()
);

-- Documents: source tracking + lifecycle
CREATE TABLE IF NOT EXISTS documents (
    id BIGSERIAL PRIMARY KEY,
    namespace TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    source_path TEXT,
    metadata JSONB DEFAULT '{}',
    effective_from TIMESTAMPTZ,
    effective_to   TIMESTAMPTZ,
    retracted      BOOLEAN DEFAULT FALSE,
    version_label  TEXT,
    created_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(namespace, content_hash)
);

-- Chunks: preserve source text + embeddings.
-- content          = raw chunk body (audit / grep / provenance).
-- embedded_content = what the embedder + FTS see — may include heading prefix
--                    (hierarchy strategy), glued neighbors, summary, etc.
--                    Equals content on auto strategy. See migration 001.
CREATE TABLE IF NOT EXISTS chunks (
    id BIGSERIAL PRIMARY KEY,
    document_id BIGINT REFERENCES documents(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    embedded_content TEXT,
    embedding vector({dim}),
    search_vector tsvector,
    token_count INTEGER DEFAULT 0,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Entities: graph nodes with embeddings
CREATE TABLE IF NOT EXISTS entities (
    id BIGSERIAL PRIMARY KEY,
    namespace TEXT NOT NULL,
    name TEXT NOT NULL,
    entity_type TEXT NOT NULL DEFAULT 'unknown',
    description TEXT DEFAULT '',
    embedding vector({dim}),
    community_id INTEGER,
    properties JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(namespace, name)
);

-- Relationships: graph edges (directed)
CREATE TABLE IF NOT EXISTS relationships (
    id BIGSERIAL PRIMARY KEY,
    namespace TEXT NOT NULL,
    src_id BIGINT REFERENCES entities(id) ON DELETE CASCADE,
    dst_id BIGINT REFERENCES entities(id) ON DELETE CASCADE,
    rel_type TEXT NOT NULL,
    weight FLOAT DEFAULT 1.0,
    description TEXT DEFAULT '',
    properties JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT now(),
    -- Per-fact temporal columns (migration 006). Mirror the document-
    -- level fields on `documents` for fact-level evolution / retraction.
    -- Nullable: relationships from non-temporal sources (LLM extraction,
    -- known_relationships without temporal info) keep NULL across the
    -- board and behave identically to pre-temporal.
    effective_from TIMESTAMPTZ,
    effective_to   TIMESTAMPTZ,
    retracted      BOOLEAN DEFAULT FALSE,
    retracted_at   TIMESTAMPTZ
);

-- Provenance: entity <-> chunk
CREATE TABLE IF NOT EXISTS entity_chunks (
    entity_id BIGINT REFERENCES entities(id) ON DELETE CASCADE,
    chunk_id BIGINT REFERENCES chunks(id) ON DELETE CASCADE,
    confidence FLOAT DEFAULT 1.0,
    provenance TEXT DEFAULT 'extracted',
    PRIMARY KEY (entity_id, chunk_id)
);

-- Provenance: relationship <-> chunk
CREATE TABLE IF NOT EXISTS relationship_chunks (
    relationship_id BIGINT REFERENCES relationships(id) ON DELETE CASCADE,
    chunk_id BIGINT REFERENCES chunks(id) ON DELETE CASCADE,
    confidence FLOAT DEFAULT 1.0,
    provenance TEXT DEFAULT 'extracted',
    PRIMARY KEY (relationship_id, chunk_id)
);

-- LLM response cache
CREATE TABLE IF NOT EXISTS pgrg_llm_cache (
    key TEXT PRIMARY KEY,
    response JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Indexes for graph traversal
CREATE INDEX IF NOT EXISTS idx_rel_src ON relationships(src_id);
CREATE INDEX IF NOT EXISTS idx_rel_dst ON relationships(dst_id);
CREATE INDEX IF NOT EXISTS idx_rel_ns ON relationships(namespace);
CREATE INDEX IF NOT EXISTS idx_rel_src_type ON relationships(src_id, rel_type);
CREATE INDEX IF NOT EXISTS idx_rel_dst_type ON relationships(dst_id, rel_type);

-- Indexes for entity lookup
CREATE INDEX IF NOT EXISTS idx_entity_ns_name ON entities(namespace, name);
CREATE INDEX IF NOT EXISTS idx_entity_type ON entities(entity_type);
CREATE INDEX IF NOT EXISTS idx_entity_community ON entities(community_id);

-- Indexes for document/chunk lookup
CREATE INDEX IF NOT EXISTS idx_chunk_doc ON chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_doc_ns_hash ON documents(namespace, content_hash);
CREATE INDEX IF NOT EXISTS idx_doc_ns ON documents(namespace);

-- Vector indexes (HNSW)
CREATE INDEX IF NOT EXISTS idx_entity_embed
    ON entities USING hnsw (embedding vector_cosine_ops)
    WITH (m = {hnsw_m}, ef_construction = {hnsw_ef_construction});
CREATE INDEX IF NOT EXISTS idx_chunk_embed
    ON chunks USING hnsw (embedding vector_cosine_ops)
    WITH (m = {hnsw_m}, ef_construction = {hnsw_ef_construction});

-- Trigram index for entity resolution
CREATE INDEX IF NOT EXISTS idx_entity_name_trgm ON entities USING gin (name gin_trgm_ops);

-- Full-text search index
CREATE INDEX IF NOT EXISTS idx_chunk_search ON chunks USING gin (search_vector);

-- Trigger to auto-update search_vector on chunk insert/update. FTS indexes
-- embedded_content so BM25 queries see heading text (hierarchy strategy) and
-- any future neighbor/summary decoration. Falls back to content if
-- embedded_content is NULL.
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

-- ---------------------------------------------------------------------------
-- Evolving-knowledge-RAG foundational DDL (mirrors migration 002).
-- Tier 1 populates documents evolution columns + document_versions.
-- Tier 2 populates facts (via lede+spaCy).
-- Tier 3 populates fact_edges (via async LLM slow path).
-- All fact_* tables land here so fresh installs don't need a second schema
-- change when tiers ramp up. They stay empty until the relevant tier runs.
-- ---------------------------------------------------------------------------

CREATE INDEX IF NOT EXISTS idx_doc_effective_from ON documents(effective_from);
CREATE INDEX IF NOT EXISTS idx_doc_retracted ON documents(retracted) WHERE retracted;
CREATE INDEX IF NOT EXISTS idx_doc_version_label ON documents(version_label)
    WHERE version_label IS NOT NULL;

CREATE TABLE IF NOT EXISTS document_versions (
    id                       BIGSERIAL PRIMARY KEY,
    namespace                TEXT NOT NULL,
    document_id              BIGINT REFERENCES documents(id) ON DELETE CASCADE,
    version_label            TEXT,
    effective_from           TIMESTAMPTZ,
    effective_to             TIMESTAMPTZ,
    supersedes_document_id   BIGINT REFERENCES documents(id) ON DELETE SET NULL,
    retracted                BOOLEAN DEFAULT FALSE,
    retracted_at             TIMESTAMPTZ,
    retraction_reason        TEXT,
    metadata                 JSONB DEFAULT '{}',
    created_at               TIMESTAMPTZ DEFAULT now()
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
