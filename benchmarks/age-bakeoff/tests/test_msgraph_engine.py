"""Smoke + unit tests for the MS GraphRAG engine adapter.

Live tests actually index a 3-document mini corpus and run each of the 4
query modes. They cost money and need BAKEOFF_MSGRAPH_LIVE=1 to run.
"""
from __future__ import annotations

import os

import pytest


def test_msgraph_engine_imports():
    """Adapter imports and exposes the expected class."""
    from age_bakeoff.engines.msgraph import MsGraphEngine, MsGraphMode

    assert MsGraphEngine.__name__ == "MsGraphEngine"
    # Type is a typing.Literal — not easily introspectable at runtime, but the
    # class at least imports without the graphrag package needing to be loaded.
    assert MsGraphMode is not None


def test_msgraph_modes_enumerate():
    """Instantiating with each known mode doesn't error."""
    from age_bakeoff.engines.msgraph import MsGraphEngine

    for mode in ("basic", "local", "global", "drift"):
        eng = MsGraphEngine(corpus_id="test-corpus", mode=mode)  # type: ignore[arg-type]
        info = eng.info()
        assert info.name == "msgraph"
        assert info.embedding_model == "text-embedding-3-small"


def test_settings_yaml_template_valid():
    """The generated settings.yaml parses as YAML and has expected top keys."""
    import yaml

    from age_bakeoff.engines.msgraph import _settings_yaml

    parsed = yaml.safe_load(_settings_yaml())
    # Core keys MS GraphRAG needs to build_index + query
    for key in (
        "completion_models",
        "embedding_models",
        "input",
        "chunking",
        "input_storage",
        "output_storage",
        "extract_graph",
        "local_search",
        "global_search",
        "basic_search",
    ):
        assert key in parsed, f"missing top-level key: {key}"


LIVE = os.environ.get("BAKEOFF_MSGRAPH_LIVE") == "1"


@pytest.mark.skipif(not LIVE, reason="Set BAKEOFF_MSGRAPH_LIVE=1 (costs ~$0.50)")
@pytest.mark.asyncio
async def test_msgraph_end_to_end_mini_corpus():
    """Build a small index, run one query per mode. ~$0.50 in OpenAI cost.

    MS GraphRAG's LanceDB vector store has a hard floor on corpus size — with
    <5 documents of substantive text, the vector-store load step trips a
    pyarrow array-length assertion. We use 6 docs of ~200 words each so the
    embedding + chunk pipeline produces enough text_units to index cleanly.
    This isn't a bug in our adapter; it's a property of MS GraphRAG's
    indexing pipeline. Documented here so future debugging doesn't chase it.
    """
    from age_bakeoff.engines.msgraph import MsGraphEngine

    documents = [
        {
            "id": "doc-pg-history",
            "title": "PostgreSQL history",
            "content": (
                "PostgreSQL traces its lineage to the Ingres project at UC Berkeley in the late 1970s, "
                "led by Michael Stonebraker. The Postgres project began in 1986 as a successor. By 1994 "
                "the project had migrated to SQL and was renamed PostgreSQL. Tom Lane has been a major "
                "contributor since the mid-1990s, shaping the query planner and executor. The PostgreSQL "
                "Global Development Group released version 16 in September 2023, introducing logical "
                "replication enhancements and better parallelism for complex queries. Bruce Momjian "
                "founded the project community processes that remain in use today. The project is "
                "famously governed by a small team of core committers who review every patch before merge."
            ),
        },
        {
            "id": "doc-pgvector",
            "title": "pgvector extension",
            "content": (
                "pgvector is a PostgreSQL extension for vector similarity search. It was created by "
                "Andrew Kane, who remains its primary maintainer. pgvector adds a vector data type and "
                "HNSW and IVFFlat index types for approximate nearest-neighbor queries. The extension "
                "works on PostgreSQL 12 and later. It pairs well with the logical replication improvements "
                "in Postgres 16, enabling low-latency read replicas of vector workloads. pgvector 0.7 "
                "added scalar quantization; 0.8 added binary quantization. The extension is Apache 2.0 "
                "licensed and ships on every managed Postgres provider including AWS RDS, GCP Cloud SQL, "
                "Azure Database, Supabase, and Neon."
            ),
        },
        {
            "id": "doc-apache-age",
            "title": "Apache AGE extension",
            "content": (
                "Apache AGE is a PostgreSQL extension that adds property-graph support and Cypher queries. "
                "It was originally developed by Bitnine and donated to the Apache Software Foundation in 2020. "
                "AGE requires shared_preload_libraries, which means it cannot be installed on most managed "
                "Postgres providers — only Microsoft Azure Database for PostgreSQL supports it at the time "
                "of writing. This is a significant adoption barrier for teams that run on AWS RDS, GCP Cloud "
                "SQL, Supabase, or Neon. AGE's query planner has shown some pathological cases; the LightRAG "
                "project's issue #2255 documented a 17-hour migration trying to process 407,000 edges due to "
                "a bad plan involving 49 billion estimated rows."
            ),
        },
        {
            "id": "doc-managed-pg",
            "title": "Managed Postgres providers",
            "content": (
                "AWS RDS was one of the first managed Postgres offerings, launched in 2013. GCP Cloud SQL "
                "followed shortly after. Microsoft Azure offers Azure Database for PostgreSQL in both "
                "Flexible Server and Hyperscale (Citus) configurations. Supabase provides Postgres plus "
                "an auth and storage layer aimed at frontend developers. Neon offers branching Postgres "
                "with storage-compute separation and has been a notable entrant since 2023. All of these "
                "providers support pgvector; only Azure supports Apache AGE. The managed-Postgres market "
                "is estimated at several billion dollars as of 2025 and is growing rapidly. Many teams "
                "choose managed Postgres specifically to avoid the operational burden of running Postgres "
                "themselves, which makes extension availability a critical consideration."
            ),
        },
        {
            "id": "doc-lightrag",
            "title": "LightRAG project",
            "content": (
                "LightRAG is a retrieval-augmented generation framework from HKUDS (Hong Kong University "
                "of Science and Technology). It introduced dual-level retrieval, where an LLM extracts "
                "both low-level (entity-specific) and high-level (thematic) keywords from a query and "
                "matches them against entity and relationship vector indexes respectively. LightRAG's paper "
                "(arXiv 2410.05779) was accepted at EMNLP 2025 Findings. The project has over 33,000 "
                "GitHub stars. LightRAG claims a 6,000x reduction in query-time token cost compared to "
                "Microsoft GraphRAG, because it avoids the community-summary scanning approach MS GraphRAG "
                "uses. It supports multiple backends including PostgreSQL via Apache AGE, though the AGE "
                "integration has had documented performance issues."
            ),
        },
        {
            "id": "doc-ms-graphrag",
            "title": "Microsoft GraphRAG",
            "content": (
                "Microsoft GraphRAG was introduced in April 2024 as a graph-based approach to RAG. The "
                "original paper, Edge et al. 2024, defined a pipeline that extracts entities and "
                "relationships via LLM, builds a knowledge graph, runs Leiden community detection, and "
                "generates hierarchical community summaries. These summaries enable global sensemaking "
                "queries that span the entire corpus. MS GraphRAG's indexing is expensive — the Edge "
                "paper reported about 600,000 tokens per query due to community scanning, and "
                "approximately $6 to $7 in OpenAI cost to index 32,000 words with GPT-4o. The project "
                "has spawned several successors including LazyGraphRAG, which defers community "
                "summarization to query time. The GraphRAG-Bench paper at ICLR 2026 benchmarks these "
                "approaches head-to-head on medical and literary corpora."
            ),
        },
    ]

    eng = MsGraphEngine(corpus_id="test-mini", mode="local")
    await eng.ingest_raw(documents)

    # Query each mode once
    results = {}
    for mode in ("basic", "local", "global", "drift"):
        eng._mode = mode
        answer, chunks, retrieval_ms, total_ms = await eng.query_end_to_end(
            "Who created pgvector?"
        )
        results[mode] = {
            "answer": answer,
            "n_chunks": len(chunks),
            "latency_ms": total_ms,
        }
        assert isinstance(answer, str) and len(answer) > 0, f"mode {mode}: empty answer"

    # All four modes should have completed; results matrix visible in -s output
    for mode, r in results.items():
        print(
            f"  {mode:8s} {r['latency_ms']:7.0f}ms  n_chunks={r['n_chunks']:3d}  "
            f"{r['answer'][:80]}..."
        )
