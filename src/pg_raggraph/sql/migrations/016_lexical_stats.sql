-- BM25-quality lexical scoring (issue #96).
--
-- The shipped lexical leg is ts_rank over an 'english'-stemmed tsvector:
-- no corpus IDF, and code identifiers get parser-split + stemmed
-- ('validate_billing_archive' -> 'valid','bill','archiv'). This migration
-- adds everything the opt-in `lexical_backend="bm25"` needs:
--
-- 1. Per-namespace corpus statistics:
--      lexeme_stats(namespace, lexeme, df)     — document frequency per lexeme
--      lexical_corpus_stats(namespace, ...)    — chunk_count + total token length
--    Maintained incrementally by statement-level triggers on `chunks`
--    (insert / update / delete) plus a BEFORE DELETE trigger on `documents`
--    for the FK-cascade path (by the time a cascaded chunk delete fires the
--    chunk-level trigger, the parent documents row — and with it the
--    namespace — is already gone, so the documents trigger decrements while
--    the chunks still exist). Deletes DECREMENT — stats stay exact, no drift.
--    Chunks ingested BEFORE this migration are not counted: run
--    rag.rebuild_lexical_stats() (or `pgrg rebuild-lexical-stats`) once per
--    pre-existing namespace before flipping lexical_backend to "bm25".
--
-- 2. Identifier-preserving tokenization. The tsvector *parser* splits
--    underscored identifiers regardless of dictionary config ('simple'
--    included), so pgrg_identifier_tsvector() extracts identifier-shaped
--    tokens with a regex and injects them via array_to_tsvector, bypassing
--    the parser. pgrg_update_search_vector() appends them to every chunk's
--    search_vector; the query side uses the same function so index-time and
--    query-time tokenization stay symmetric. Identifier lexemes carry no
--    positions: ts_rank ignores them (no behavior change for the default
--    backend) while BM25 counts them with tf=1.
--
-- ponytail: statement-level upserts hold row locks on shared lexeme rows for
-- the remainder of the per-document ingest transaction. The insert path
-- ORDER BYs (namespace, lexeme) so concurrent ingests acquire locks in one
-- global order (no deadlocks); throughput ceiling is the storage phase of
-- concurrent docs serializing on hot lexemes. If that ever matters, move the
-- maintenance to an async aggregation of per-statement deltas.

CREATE TABLE IF NOT EXISTS lexeme_stats (
    namespace TEXT NOT NULL,
    lexeme    TEXT NOT NULL,
    df        BIGINT NOT NULL DEFAULT 0,
    PRIMARY KEY (namespace, lexeme)
);

CREATE TABLE IF NOT EXISTS lexical_corpus_stats (
    namespace   TEXT PRIMARY KEY,
    chunk_count BIGINT NOT NULL DEFAULT 0,
    total_len   BIGINT NOT NULL DEFAULT 0
);

-- Total term occurrences in a tsvector (sum of per-lexeme position counts).
-- Positionless lexemes (array_to_tsvector output) count as 1 occurrence.
CREATE OR REPLACE FUNCTION pgrg_lexeme_len(v tsvector) RETURNS bigint AS $$
    SELECT COALESCE(sum(COALESCE(array_length(t.positions, 1), 1)), 0)::bigint
    FROM unnest(v) t
$$ LANGUAGE sql IMMUTABLE PARALLEL SAFE;

-- Identifier-shaped tokens (>= one underscore between alphanumeric runs),
-- lowercased and deduped, as a positionless tsvector. The 512-byte cap keeps
-- pathological tokens (minified blobs) from hitting the 2046-byte lexeme
-- hard limit and aborting ingest.
CREATE OR REPLACE FUNCTION pgrg_identifier_tsvector(body text) RETURNS tsvector AS $$
    SELECT COALESCE(array_to_tsvector(array_agg(DISTINCT lower(m[1]))), ''::tsvector)
    FROM regexp_matches(body, '([A-Za-z0-9]+(?:_[A-Za-z0-9]+)+)', 'g') m
    WHERE length(m[1]) <= 512
$$ LANGUAGE sql IMMUTABLE PARALLEL SAFE;

-- Layer identifier lexemes onto the search-vector trigger (previous
-- definition: migration 011 — body 'A' + top_terms 'B'). Existing chunks are
-- NOT re-indexed here; see migration 011's notes for the re-index UPDATE.
CREATE OR REPLACE FUNCTION pgrg_update_search_vector() RETURNS trigger AS $$
DECLARE
    top_terms_text TEXT := '';
    body TEXT;
BEGIN
    body := COALESCE(NEW.embedded_content, NEW.content);
    IF jsonb_typeof(NEW.metadata->'top_terms') = 'array' THEN
        SELECT COALESCE(string_agg(elem->>'term', ' '), '')
          INTO top_terms_text
          FROM jsonb_array_elements(NEW.metadata->'top_terms') elem;
    END IF;
    NEW.search_vector :=
        setweight(to_tsvector('english', body), 'A')
        || setweight(to_tsvector('english', top_terms_text), 'B')
        || pgrg_identifier_tsvector(body);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- --- Incremental stats maintenance ---------------------------------------

CREATE OR REPLACE FUNCTION pgrg_lexstats_chunks_ins() RETURNS trigger AS $$
BEGIN
    -- ORDER BY (namespace, lexeme): consistent lock-acquisition order across
    -- concurrent ingest transactions prevents upsert deadlocks.
    INSERT INTO lexeme_stats (namespace, lexeme, df)
    SELECT d.namespace, t.lexeme, count(*)
    FROM newtab n
    JOIN documents d ON d.id = n.document_id
    CROSS JOIN LATERAL unnest(n.search_vector) t
    GROUP BY d.namespace, t.lexeme
    ORDER BY 1, 2
    ON CONFLICT (namespace, lexeme)
        DO UPDATE SET df = lexeme_stats.df + EXCLUDED.df;

    INSERT INTO lexical_corpus_stats (namespace, chunk_count, total_len)
    SELECT d.namespace, count(*), COALESCE(sum(pgrg_lexeme_len(n.search_vector)), 0)
    FROM newtab n
    JOIN documents d ON d.id = n.document_id
    GROUP BY d.namespace
    ON CONFLICT (namespace)
        DO UPDATE SET chunk_count = lexical_corpus_stats.chunk_count + EXCLUDED.chunk_count,
                      total_len   = lexical_corpus_stats.total_len + EXCLUDED.total_len;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_chunks_lexstats_ins ON chunks;
CREATE TRIGGER trg_chunks_lexstats_ins
    AFTER INSERT ON chunks
    REFERENCING NEW TABLE AS newtab
    FOR EACH STATEMENT EXECUTE FUNCTION pgrg_lexstats_chunks_ins();

-- Direct chunk deletes only: the parent documents row still exists, so the
-- join resolves the namespace. Document-cascade deletes see no parent row
-- here (empty join, no-op) — trg_documents_lexstats_del handles that path.
CREATE OR REPLACE FUNCTION pgrg_lexstats_chunks_del() RETURNS trigger AS $$
BEGIN
    UPDATE lexeme_stats ls
    SET df = GREATEST(ls.df - dec.cnt, 0)
    FROM (
        SELECT d.namespace, t.lexeme, count(*) AS cnt
        FROM oldtab o
        JOIN documents d ON d.id = o.document_id
        CROSS JOIN LATERAL unnest(o.search_vector) t
        GROUP BY d.namespace, t.lexeme
    ) dec
    WHERE ls.namespace = dec.namespace AND ls.lexeme = dec.lexeme;

    UPDATE lexical_corpus_stats cs
    SET chunk_count = GREATEST(cs.chunk_count - dec.cnt, 0),
        total_len   = GREATEST(cs.total_len - dec.len, 0)
    FROM (
        SELECT d.namespace, count(*) AS cnt,
               COALESCE(sum(pgrg_lexeme_len(o.search_vector)), 0) AS len
        FROM oldtab o
        JOIN documents d ON d.id = o.document_id
        GROUP BY d.namespace
    ) dec
    WHERE cs.namespace = dec.namespace;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_chunks_lexstats_del ON chunks;
CREATE TRIGGER trg_chunks_lexstats_del
    AFTER DELETE ON chunks
    REFERENCING OLD TABLE AS oldtab
    FOR EACH STATEMENT EXECUTE FUNCTION pgrg_lexstats_chunks_del();

-- Fires on every UPDATE (transition tables cannot combine with a column
-- list), but only rows whose search_vector changed contribute — embedding/
-- metadata bulk updates net to zero rows. Decrement OLD, increment NEW.
CREATE OR REPLACE FUNCTION pgrg_lexstats_chunks_upd() RETURNS trigger AS $$
BEGIN
    -- Only rows whose search_vector actually changed contribute; embedding-
    -- or metadata-only bulk updates group over zero rows and no-op.
    UPDATE lexeme_stats ls
    SET df = GREATEST(ls.df - dec.cnt, 0)
    FROM (
        SELECT d.namespace, t.lexeme, count(*) AS cnt
        FROM oldtab o
        JOIN newtab n ON n.id = o.id
        JOIN documents d ON d.id = o.document_id
        CROSS JOIN LATERAL unnest(o.search_vector) t
        WHERE o.search_vector IS DISTINCT FROM n.search_vector
        GROUP BY d.namespace, t.lexeme
    ) dec
    WHERE ls.namespace = dec.namespace AND ls.lexeme = dec.lexeme;

    INSERT INTO lexeme_stats (namespace, lexeme, df)
    SELECT d.namespace, t.lexeme, count(*)
    FROM newtab n
    JOIN oldtab o ON o.id = n.id
    JOIN documents d ON d.id = n.document_id
    CROSS JOIN LATERAL unnest(n.search_vector) t
    WHERE o.search_vector IS DISTINCT FROM n.search_vector
    GROUP BY d.namespace, t.lexeme
    ORDER BY 1, 2
    ON CONFLICT (namespace, lexeme)
        DO UPDATE SET df = lexeme_stats.df + EXCLUDED.df;

    UPDATE lexical_corpus_stats cs
    SET total_len = GREATEST(cs.total_len - dec.old_len + dec.new_len, 0)
    FROM (
        SELECT d.namespace,
               COALESCE(sum(pgrg_lexeme_len(o.search_vector)), 0) AS old_len,
               COALESCE(sum(pgrg_lexeme_len(n.search_vector)), 0) AS new_len
        FROM oldtab o
        JOIN newtab n ON n.id = o.id
        JOIN documents d ON d.id = n.document_id
        WHERE o.search_vector IS DISTINCT FROM n.search_vector
        GROUP BY d.namespace
    ) dec
    WHERE cs.namespace = dec.namespace;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_chunks_lexstats_upd ON chunks;
CREATE TRIGGER trg_chunks_lexstats_upd
    AFTER UPDATE ON chunks
    REFERENCING OLD TABLE AS oldtab NEW TABLE AS newtab
    FOR EACH STATEMENT EXECUTE FUNCTION pgrg_lexstats_chunks_upd();

-- Cascade path: decrement while the document's chunks are still visible.
CREATE OR REPLACE FUNCTION pgrg_lexstats_doc_del() RETURNS trigger AS $$
BEGIN
    UPDATE lexeme_stats ls
    SET df = GREATEST(ls.df - dec.cnt, 0)
    FROM (
        SELECT t.lexeme, count(*) AS cnt
        FROM chunks c
        CROSS JOIN LATERAL unnest(c.search_vector) t
        WHERE c.document_id = OLD.id
        GROUP BY t.lexeme
    ) dec
    WHERE ls.namespace = OLD.namespace AND ls.lexeme = dec.lexeme;

    UPDATE lexical_corpus_stats cs
    SET chunk_count = GREATEST(cs.chunk_count - dec.cnt, 0),
        total_len   = GREATEST(cs.total_len - dec.len, 0)
    FROM (
        SELECT count(*) AS cnt,
               COALESCE(sum(pgrg_lexeme_len(c.search_vector)), 0) AS len
        FROM chunks c
        WHERE c.document_id = OLD.id
    ) dec
    WHERE cs.namespace = OLD.namespace AND dec.cnt > 0;
    RETURN OLD;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_documents_lexstats_del ON documents;
CREATE TRIGGER trg_documents_lexstats_del
    BEFORE DELETE ON documents
    FOR EACH ROW EXECUTE FUNCTION pgrg_lexstats_doc_del();

-- --- RLS parity (migration 003) -------------------------------------------
-- The chunk triggers write these tables during every ingest, so the app role
-- needs grants or RLS deployments break on the next INSERT INTO chunks.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'pgrg_app') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON lexeme_stats, lexical_corpus_stats TO pgrg_app;
    END IF;
END $$;

ALTER TABLE lexeme_stats ENABLE ROW LEVEL SECURITY;
ALTER TABLE lexeme_stats FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS ns_isolation ON lexeme_stats;
CREATE POLICY ns_isolation ON lexeme_stats
    USING (pgrg_tenant() IS NULL OR namespace = pgrg_tenant());

ALTER TABLE lexical_corpus_stats ENABLE ROW LEVEL SECURITY;
ALTER TABLE lexical_corpus_stats FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS ns_isolation ON lexical_corpus_stats;
CREATE POLICY ns_isolation ON lexical_corpus_stats
    USING (pgrg_tenant() IS NULL OR namespace = pgrg_tenant());
