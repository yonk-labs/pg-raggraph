"""Full user journey test — simulates a real user from install to query.

This test requires:
- Running PostgreSQL on localhost:5434 (docker compose up -d)
- Running LLM at PGRG_TEST_LLM_URL (default: http://192.168.1.193:8000/v1)

Run with: uv run pytest tests/test_user_journey.py -v -s
"""

import os
import time

import httpx
import pytest

from pg_raggraph import GraphRAG

TEST_DSN = "postgresql://postgres:postgres@localhost:5434/pg_raggraph"
LLM_URL = os.environ.get("PGRG_TEST_LLM_URL", "http://192.168.1.193:8000/v1")
LLM_MODEL = os.environ.get("PGRG_TEST_LLM_MODEL", "Intel/Qwen3-Coder-Next-int4-AutoRound")
DEMO_CORPUS = os.path.join(os.path.dirname(os.path.dirname(__file__)), "fixtures", "demo_corpus")


def llm_reachable() -> bool:
    try:
        return httpx.get(f"{LLM_URL}/models", timeout=5).status_code == 200
    except Exception:
        return False


skip_no_llm = pytest.mark.skipif(not llm_reachable(), reason="LLM not reachable")
pytestmark = [pytest.mark.integration, skip_no_llm]


@pytest.fixture
async def rag():
    """Provide a clean GraphRAG instance pointed at the real LLM."""
    r = GraphRAG(
        dsn=TEST_DSN,
        namespace="user_journey",
        llm_base_url=LLM_URL,
        llm_model=LLM_MODEL,
    )
    await r.connect()
    await r.delete("user_journey")
    yield r
    await r.delete("user_journey")
    await r.close()


async def test_step1_ingest_demo_corpus(rag):
    """User ingests 4 engineering docs. Entities and relationships are extracted."""
    t0 = time.perf_counter()
    await rag.ingest([DEMO_CORPUS], namespace="user_journey")
    elapsed = time.perf_counter() - t0

    status = await rag.status("user_journey")
    assert status["documents"] == 4, f"Expected 4 docs, got {status['documents']}"
    assert status["chunks"] >= 20, f"Expected >=20 chunks, got {status['chunks']}"
    assert status["entities"] > 10, f"Expected >10 entities, got {status['entities']}"
    assert status["relationships"] > 5, f"Expected >5 rels, got {status['relationships']}"
    print(
        f"\n  Ingested in {elapsed:.1f}s: {status['entities']} entities, "
        f"{status['relationships']} relationships"
    )


async def test_step2_key_entities_extracted(rag):
    """Known people and systems from the corpus are extracted as entities."""
    await rag.ingest([DEMO_CORPUS], namespace="user_journey")

    entities = await rag.db.fetch_all(
        "SELECT name FROM entities WHERE namespace = %s", ("user_journey",)
    )
    names_lower = [e["name"].lower() for e in entities]

    # People we expect the LLM to find
    expected_people = ["sarah chen", "jake morrison", "david park", "lisa wang", "ahmed hassan"]
    found_people = [p for p in expected_people if any(p in n for n in names_lower)]
    assert len(found_people) >= 3, f"Expected >=3 people, found: {found_people}"

    # Systems we expect
    expected_systems = ["kong", "postgresql", "kubernetes", "datadog", "stripe"]
    found_systems = [s for s in expected_systems if any(s in n for n in names_lower)]
    assert len(found_systems) >= 3, f"Expected >=3 systems, found: {found_systems}"
    print(f"\n  People: {found_people}\n  Systems: {found_systems}")


async def test_step3_relationships_meaningful(rag):
    """Extracted relationships represent real connections from the docs."""
    await rag.ingest([DEMO_CORPUS], namespace="user_journey")

    rels = await rag.db.fetch_all(
        """SELECT e1.name as src, e2.name as dst, r.rel_type
           FROM relationships r
           JOIN entities e1 ON e1.id = r.src_id
           JOIN entities e2 ON e2.id = r.dst_id
           WHERE r.namespace = %s""",
        ("user_journey",),
    )
    assert len(rels) > 5
    # Print a sample for human review
    print(f"\n  {len(rels)} relationships. Sample:")
    for r in rels[:8]:
        print(f"    {r['src']} --[{r['rel_type']}]--> {r['dst']}")


async def test_step4_query_who_leads_platform(rag):
    """Direct question: 'Who leads the Platform Team?' → Sarah Chen."""
    await rag.ingest([DEMO_CORPUS], namespace="user_journey")

    result = await rag.query(
        "Who leads the Platform Team?", mode="hybrid", namespace="user_journey"
    )
    all_content = " ".join(c.content for c in result.chunks).lower()
    assert "sarah chen" in all_content
    # Latency budget is intentionally loose: the bake-off shows hybrid
    # retrieval p95 around 90 ms, but cold-start CI runners and
    # contended dev machines have produced ~280 ms on this exact test.
    # Catch a 5×+ regression without flaking on transient load.
    assert result.latency_ms < 1500, (
        f"hybrid query latency {result.latency_ms:.0f}ms exceeds 1500 ms — "
        "investigate query plan / connection pool"
    )
    print(f"\n  ✓ Found Sarah Chen ({result.latency_ms:.0f}ms)")


async def test_step5_query_kubernetes_contact(rag):
    """Multi-hop: 'Who manages Kubernetes?' → Jake Morrison (via team/system graph)."""
    await rag.ingest([DEMO_CORPUS], namespace="user_journey")

    result = await rag.query(
        "Who should I contact about Kubernetes access?",
        mode="hybrid",
        namespace="user_journey",
    )
    all_content = " ".join(c.content for c in result.chunks).lower()
    assert "jake" in all_content, "Expected Jake Morrison (manages K8s)"
    print(f"\n  ✓ Found Jake Morrison ({result.latency_ms:.0f}ms)")


async def test_step6_query_incident_root_cause(rag):
    """Cross-doc: 'What caused the payment outage?' → Kong rate limit misconfiguration."""
    await rag.ingest([DEMO_CORPUS], namespace="user_journey")

    result = await rag.query(
        "What caused the payment service outage?",
        mode="hybrid",
        namespace="user_journey",
    )
    all_content = " ".join(c.content for c in result.chunks).lower()
    assert "payment" in all_content
    has_root_cause = "kong" in all_content or "rate limit" in all_content
    assert has_root_cause, "Expected Kong/rate limit as root cause"
    print(f"\n  ✓ Found root cause ({result.latency_ms:.0f}ms)")


async def test_step7_query_lisa_wang_systems(rag):
    """Entity-centric: 'What does Lisa Wang own?' → authentication service."""
    await rag.ingest([DEMO_CORPUS], namespace="user_journey")

    result = await rag.query(
        "What systems does Lisa Wang own?",
        mode="hybrid",
        namespace="user_journey",
    )
    all_content = " ".join(c.content for c in result.chunks).lower()
    assert "authentication" in all_content or "auth" in all_content
    print(f"\n  ✓ Found auth service ({result.latency_ms:.0f}ms)")


async def test_step8_hybrid_beats_naive(rag):
    """Hybrid mode finds more context than naive for graph-dependent questions."""
    await rag.ingest([DEMO_CORPUS], namespace="user_journey")

    r_naive = await rag.query(
        "escalation path for P1 incidents",
        mode="naive",
        namespace="user_journey",
    )
    r_hybrid = await rag.query(
        "escalation path for P1 incidents",
        mode="hybrid",
        namespace="user_journey",
    )
    # Hybrid uses graph → should find more entities
    assert len(r_hybrid.entities) >= len(r_naive.entities)
    print(
        f"\n  Naive: {len(r_naive.entities)} entities | Hybrid: {len(r_hybrid.entities)} entities"
    )


async def test_step9_dedup_works(rag):
    """Re-ingesting the same corpus doesn't create duplicates."""
    await rag.ingest([DEMO_CORPUS], namespace="user_journey")
    s1 = await rag.status("user_journey")

    await rag.ingest([DEMO_CORPUS], namespace="user_journey")
    s2 = await rag.status("user_journey")

    assert s2["documents"] == s1["documents"]
    print(f"\n  ✓ Docs unchanged: {s1['documents']} → {s2['documents']}")


async def test_step10_latency_acceptable(rag):
    """All query modes return in well under 1500 ms (regression guard).

    The threshold is intentionally generous: bake-off measurements show
    real p95 retrieval at <100 ms, so 1500 ms catches a 15×+ regression
    without flaking on cold-start CI or contended dev machines. Tighten
    in a separate benchmark if you want to track perf drift over time.
    """
    await rag.ingest([DEMO_CORPUS], namespace="user_journey")

    for mode in ["naive", "local", "global", "hybrid"]:
        result = await rag.query("PostgreSQL", mode=mode, namespace="user_journey")
        assert result.latency_ms < 1500, f"{mode} took {result.latency_ms:.0f}ms"
    print("\n  ✓ All modes < 1500ms (regression guard)")
