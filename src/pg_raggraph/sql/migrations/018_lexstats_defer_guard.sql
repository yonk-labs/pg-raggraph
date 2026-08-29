-- Deferrable lexical-stats maintenance (issue #97).
--
-- Migration 016's statement-level lexstats triggers hold row locks on shared
-- lexeme rows for the rest of each per-document ingest transaction, which
-- serializes the storage phase of concurrent same-namespace ingest. The
-- cap-gold-v1 bake hit this for real: ~9h projected for 11.5K docs with the
-- triggers active vs ~15min with a bulk-load bypass.
--
-- This adds an opt-in escape hatch: a transaction-local GUC,
-- `pgrg.defer_lexical_stats`, that the four maintenance triggers honor by
-- early-returning. `ingest_records(..., defer_lexical_stats=True)` sets it
-- (via set_config(..., is_local=true)) so the bulk transactions skip the
-- lock-contended upserts; the caller then runs rebuild_lexical_stats() once,
-- which fully recomputes exact stats from chunks.search_vector.
--
-- Crucially this does NOT touch the search-vector trigger (migration 011):
-- chunks still get their search_vector populated during a deferred load, so
-- the post-load rebuild has everything it needs. Only the df/corpus-length
-- bookkeeping is skipped and reconstructed.
--
-- Trade-off: between the deferred load and the rebuild, lexeme_stats /
-- lexical_corpus_stats are stale for that namespace, so lexical_backend="bm25"
-- scores are wrong in that window. Documented in docs/cookbook/bm25-lexical.md.

-- Centralizes the GUC name + read. Positive only when explicitly set to 'on'
-- for the current transaction; unset → NULL → false.
CREATE OR REPLACE FUNCTION pgrg_lexstats_deferred() RETURNS boolean AS $$
    SELECT current_setting('pgrg.defer_lexical_stats', true) = 'on'
$$ LANGUAGE sql STABLE;

CREATE OR REPLACE FUNCTION pgrg_lexstats_chunks_ins() RETURNS trigger AS $$
BEGIN
    IF pgrg_lexstats_deferred() THEN RETURN NULL; END IF;
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

CREATE OR REPLACE FUNCTION pgrg_lexstats_chunks_del() RETURNS trigger AS $$
BEGIN
    IF pgrg_lexstats_deferred() THEN RETURN NULL; END IF;
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

CREATE OR REPLACE FUNCTION pgrg_lexstats_chunks_upd() RETURNS trigger AS $$
BEGIN
    IF pgrg_lexstats_deferred() THEN RETURN NULL; END IF;
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

CREATE OR REPLACE FUNCTION pgrg_lexstats_doc_del() RETURNS trigger AS $$
BEGIN
    IF pgrg_lexstats_deferred() THEN RETURN OLD; END IF;
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
