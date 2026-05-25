CREATE TABLE IF NOT EXISTS living_audit_log (
    id BIGSERIAL PRIMARY KEY,
    namespace TEXT NOT NULL,
    logical_id TEXT NOT NULL,
    cadence TEXT NOT NULL,
    bucket TEXT NOT NULL,
    source_path TEXT NOT NULL,
    old_document_id BIGINT,
    new_document_id BIGINT,
    old_content_hash TEXT,
    new_content_hash TEXT,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_doc_living_identity
    ON documents (
        namespace,
        (metadata->>'living_logical_id'),
        (metadata->>'living_cadence'),
        (metadata->>'living_bucket')
    )
    WHERE metadata ? 'living_logical_id';

CREATE INDEX IF NOT EXISTS idx_doc_living_current
    ON documents (namespace, (metadata->>'living_current'))
    WHERE metadata ? 'living_current';

CREATE INDEX IF NOT EXISTS idx_living_audit_identity
    ON living_audit_log (namespace, logical_id, cadence, bucket);
