-- Earlier imports have a NULL fingerprint and are refreshed on their next import.
ALTER TABLE documents ADD COLUMN IF NOT EXISTS input_fingerprint TEXT;

-- Match by source without indexing arbitrarily long source identifiers.
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_documents_source_latest
    ON documents (namespace, md5(source_path), id DESC);

-- Find the affected edge provenance when replacing a document.
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_relationship_chunks_chunk
    ON relationship_chunks (chunk_id);
