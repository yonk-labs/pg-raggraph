-- Fold chunkshop top_terms (chunks.metadata->'top_terms') into search_vector.
--
-- Before this migration the trigger indexed only embedded_content (or content
-- as fallback) with uniform weight. After this migration:
--   weight 'A' — embedded_content / content (body terms; rank highest)
--   weight 'B' — top_terms[*].term values from metadata JSONB (salient terms
--                supplied by chunkshop or any caller that sets the field)
--
-- Guard: if metadata->'top_terms' is absent or not a JSON array (e.g. a
-- plain string, a number, or NULL) the aggregation produces an empty string
-- and setweight(..., 'B') is a no-op. No behavior change for existing chunks
-- that do not carry top_terms.
--
-- Existing chunks are NOT re-indexed by this migration; search_vector is only
-- rebuilt when a chunk is INSERTed or when content/embedded_content is UPDATEd
-- (the trigger fires on those columns). Re-index existing rows with:
--     UPDATE chunks SET embedded_content = embedded_content;
-- or do a full table-level UPDATE if embedded_content is NULL:
--     UPDATE chunks SET content = content WHERE embedded_content IS NULL;

CREATE OR REPLACE FUNCTION pgrg_update_search_vector() RETURNS trigger AS $$
DECLARE
    top_terms_text TEXT := '';
BEGIN
    IF jsonb_typeof(NEW.metadata->'top_terms') = 'array' THEN
        SELECT COALESCE(string_agg(elem->>'term', ' '), '')
          INTO top_terms_text
          FROM jsonb_array_elements(NEW.metadata->'top_terms') elem;
    END IF;
    NEW.search_vector :=
        setweight(to_tsvector('english', COALESCE(NEW.embedded_content, NEW.content)), 'A')
        || setweight(to_tsvector('english', top_terms_text), 'B');
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
