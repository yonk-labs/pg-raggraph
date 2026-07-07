-- Microsoft's accelerator GraphRAG query, adapted for a local run.
-- Source: get_vector_semantic_graphrag_optimized in
--   Azure-Samples/graphrag-legalcases-postgres
--   src/backend/fastapi_app/setup_postgres_legal_seeddata.py
--
-- Adaptations (each recorded in README "Asymmetries"):
--   1. SEMANTIC RERANK STAGE REMOVED. Their stage 2 calls
--      azure_ml.invoke(..., deployment_name => 'bge-...-reranker') — an
--      Azure-only extension that does not exist locally. We substitute
--      semantic_rank := vector_rank (identity rerank). The pg-raggraph arm
--      runs without a reranker too, so the skip is symmetric — but this is
--      NOT Microsoft's full published pipeline.
--   2. cypher() column list declared agtype + explicit quote-trim, instead
--      of their `AS (case_id TEXT, ref_id TEXT)`. See the composability
--      probe in run_age.py, which tests their verbatim form separately.
--   3. embedding parameter is fastembed bge-small (384-dim), not
--      text-embedding-3-small (1536-dim).
--   4. plpgsql wrapper dropped; runs as ONE SQL statement.
-- Everything else — court filter, consider_n=60, semantic_rank <= 25 gate,
-- ref_cosine ORDER + LIMIT 200, RRF constants 60/60, gold_dataset join —
-- is their structure verbatim.
WITH vector_stage AS (
    SELECT cases_updated.id,
        cases_updated.data#>>'{name_abbreviation}' AS case_name,
        cases_updated.data#>>'{decision_date}' AS date,
        RANK() OVER (ORDER BY description_vector <=> %(qvec)s::vector) AS vector_rank
    FROM cases_updated
    WHERE (cases_updated.data#>>'{court, id}')::integer IN (9029)
    ORDER BY description_vector <=> %(qvec)s::vector
    LIMIT 60
),
semantic_ranked AS (
    -- rerank stage removed: identity mapping (see adaptation note 1)
    SELECT vector_stage.*, vector_stage.vector_rank AS semantic_rank
    FROM vector_stage
),
graph_query AS (
    SELECT trim(both '"' from a.case_id::text) AS case_id,
           trim(both '"' from a.ref_id::text)  AS ref_id
    FROM ag_catalog.cypher('case_graph',
        $$ MATCH (s)-[r:REF]->(n) RETURN n.case_id AS case_id, s.case_id AS ref_id $$
    ) AS a(case_id agtype, ref_id agtype)
),
graph AS (
    SELECT subquery.id, COUNT(subquery.ref_id) AS refs
    FROM (
        SELECT semantic_ranked.id, graph_query.ref_id,
               c2.description_vector <=> %(qvec)s::vector AS ref_cosine
        FROM semantic_ranked
        LEFT JOIN graph_query ON semantic_ranked.id = graph_query.case_id
        LEFT JOIN cases_updated c2 ON c2.id = graph_query.ref_id
        WHERE semantic_ranked.semantic_rank <= 25
        ORDER BY ref_cosine
        LIMIT 200
    ) AS subquery
    GROUP BY subquery.id
),
graph2 AS (
    SELECT semantic_ranked.*, graph.refs
    FROM semantic_ranked
    LEFT JOIN graph ON semantic_ranked.id = graph.id
),
graph_ranked AS (
    SELECT RANK() OVER (ORDER BY COALESCE(graph2.refs, 0) DESC) AS graph_rank, graph2.*
    FROM graph2
),
rrf AS (
    SELECT
        gold_dataset.label,
        COALESCE(1.0 / (60 + graph_ranked.graph_rank), 0.0) +
        COALESCE(1.0 / (60 + graph_ranked.semantic_rank), 0.0) AS score,
        graph_ranked.*
    FROM graph_ranked
    LEFT JOIN gold_dataset ON graph_ranked.id = gold_dataset.gold_id
)
SELECT rrf.label, rrf.score, rrf.graph_rank, rrf.semantic_rank, rrf.vector_rank,
       rrf.id, rrf.case_name, rrf.refs
FROM rrf
ORDER BY rrf.score DESC
LIMIT %(k)s;
