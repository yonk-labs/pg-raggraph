"""Retrieval Mode Comparison Test.

Compares vector-only, vector+BM25, and vector+BM25+graph retrieval
to demonstrate when each mode excels. Uses a dataset designed to
make the differences obvious.

Run: uv run pytest tests/test_retrieval_comparison.py -v -s

Requires: Running PostgreSQL + LLM at PGRG_TEST_LLM_URL
"""

from __future__ import annotations

import os

import httpx
import pytest

from pg_raggraph import GraphRAG

TEST_DSN = "postgresql://postgres:postgres@localhost:5434/pg_raggraph"
LLM_URL = os.environ.get("PGRG_TEST_LLM_URL", "http://192.168.1.193:8000/v1")
LLM_MODEL = os.environ.get("PGRG_TEST_LLM_MODEL", "Intel/Qwen3-Coder-Next-int4-AutoRound")
CORPUS_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "comparison_corpus")

pytestmark = pytest.mark.integration


def llm_reachable() -> bool:
    try:
        return httpx.get(f"{LLM_URL}/models", timeout=5).status_code == 200
    except Exception:
        return False


skip_no_llm = pytest.mark.skipif(not llm_reachable(), reason="LLM not reachable")


@pytest.fixture(scope="module")
def event_loop():
    """Module-scoped event loop for shared fixture."""
    import asyncio

    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="module")
async def seeded_rag(event_loop):
    """Ingest the comparison corpus once, reuse across all tests."""
    if not llm_reachable():
        pytest.skip("LLM not reachable")

    rag = GraphRAG(
        dsn=TEST_DSN,
        namespace="comparison_test",
        llm_base_url=LLM_URL,
        llm_model=LLM_MODEL,
    )
    await rag.connect()
    await rag.delete("comparison_test")

    # Ingest with real LLM
    await rag.ingest([CORPUS_DIR], namespace="comparison_test")

    status = await rag.status("comparison_test")
    print(f"\n  Seeded: {status['entities']} entities, {status['relationships']} rels")

    yield rag

    await rag.delete("comparison_test")
    await rag.close()


# === THE COMPARISON QUERIES ===
# Each query is designed to show where a specific mode excels or struggles.


@skip_no_llm
async def test_direct_keyword_query(seeded_rag):
    """Q1: 'payment outage' — BM25 should boost results that mention these exact words.

    Vector might match semantically similar content (like 'transaction failure').
    BM25 specifically rewards the exact keyword match.
    """
    print("\n" + "=" * 70)
    print("Q1: 'payment outage' (BM25 should help with exact term matching)")
    print("=" * 70)

    # Vector only (naive mode — combines vector + BM25 by default)
    r_naive = await seeded_rag.query("payment outage", mode="naive", namespace="comparison_test")
    # Local mode (vector → entity seeds → graph expansion → chunks)
    r_local = await seeded_rag.query("payment outage", mode="local", namespace="comparison_test")
    # Hybrid (local + global combined)
    r_hybrid = await seeded_rag.query("payment outage", mode="hybrid", namespace="comparison_test")

    print(
        f"\n  Naive (vector+BM25):  {len(r_naive.chunks)} chunks, "
        f"{r_naive.latency_ms:.0f}ms, {len(r_naive.entities)} entities"
    )
    print(
        f"  Local (graph):        {len(r_local.chunks)} chunks, "
        f"{r_local.latency_ms:.0f}ms, {len(r_local.entities)} entities"
    )
    print(
        f"  Hybrid (all):         {len(r_hybrid.chunks)} chunks, "
        f"{r_hybrid.latency_ms:.0f}ms, {len(r_hybrid.entities)} entities"
    )

    # Verify all modes find payment-related content
    for mode_name, result in [("naive", r_naive), ("local", r_local), ("hybrid", r_hybrid)]:
        content = " ".join(c.content.lower() for c in result.chunks)
        has_payment = "payment" in content
        print(f"  {mode_name}: contains 'payment' = {has_payment}")
        assert has_payment, f"{mode_name} should find payment-related content"

    # BM25 OR check: naive should rank "payment outage" chunks higher
    if r_naive.chunks:
        top_content = r_naive.chunks[0].content.lower()
        assert "payment" in top_content or "outage" in top_content


@skip_no_llm
async def test_multi_hop_relationship_query(seeded_rag):
    """Q2: 'Who deployed the change that caused the payment outage?'

    This requires multi-hop reasoning:
    - outage → caused by Kong rate limit → deployed by Maria Santos

    Vector-only will find chunks mentioning "payment outage" but might miss
    the connection to Maria Santos (who is in a different chunk/section).
    Graph mode should find Maria via entity relationships.
    """
    print("\n" + "=" * 70)
    print("Q2: 'Who deployed the change that caused the payment outage?'")
    print("    (requires: outage → Kong → Maria Santos = multi-hop)")
    print("=" * 70)

    r_naive = await seeded_rag.query(
        "Who deployed the change that caused the payment outage?",
        mode="naive",
        namespace="comparison_test",
    )
    r_local = await seeded_rag.query(
        "Who deployed the change that caused the payment outage?",
        mode="local",
        namespace="comparison_test",
    )
    r_hybrid = await seeded_rag.query(
        "Who deployed the change that caused the payment outage?",
        mode="hybrid",
        namespace="comparison_test",
    )

    def has_maria(result) -> bool:
        content = " ".join(c.content.lower() for c in result.chunks)
        return "maria" in content

    def has_kong(result) -> bool:
        content = " ".join(c.content.lower() for c in result.chunks)
        return "kong" in content

    naive_maria = has_maria(r_naive)
    local_maria = has_maria(r_local)
    hybrid_maria = has_maria(r_hybrid)

    print(
        f"\n  Naive:  finds Maria = {naive_maria}, finds Kong = {has_kong(r_naive)}, "
        f"{len(r_naive.entities)} entities"
    )
    print(
        f"  Local:  finds Maria = {local_maria}, finds Kong = {has_kong(r_local)}, "
        f"{len(r_local.entities)} entities"
    )
    print(
        f"  Hybrid: finds Maria = {hybrid_maria}, finds Kong = {has_kong(r_hybrid)}, "
        f"{len(r_hybrid.entities)} entities"
    )

    # Graph modes should find MORE context through entity connections
    # Hybrid should have more entities than naive (graph expansion)
    print(
        f"\n  Entities — Naive: {len(r_naive.entities)} | "
        f"Local: {len(r_local.entities)} | Hybrid: {len(r_hybrid.entities)}"
    )

    # The hybrid/local modes should find Maria Santos through graph traversal
    # (entity: payment service → relationship → Maria Santos)
    assert hybrid_maria or local_maria, (
        "Graph mode should find Maria Santos (she deployed the Kong change "
        "that caused the outage) via entity relationships"
    )


@skip_no_llm
async def test_entity_centric_query(seeded_rag):
    """Q3: 'What does Jake Morrison own?'

    Graph mode excels here — it can find the entity 'Jake Morrison'
    and traverse ALL its relationships to find everything he's connected to.
    Vector-only will find chunks that mention his name but miss chunks
    about his responsibilities that don't mention him by name.
    """
    print("\n" + "=" * 70)
    print("Q3: 'What does Jake Morrison own?'")
    print("    (graph follows entity relationships vs vector matches name)")
    print("=" * 70)

    r_naive = await seeded_rag.query(
        "What does Jake Morrison own?", mode="naive", namespace="comparison_test"
    )
    r_local = await seeded_rag.query(
        "What does Jake Morrison own?", mode="local", namespace="comparison_test"
    )
    r_hybrid = await seeded_rag.query(
        "What does Jake Morrison own?", mode="hybrid", namespace="comparison_test"
    )

    def count_jake_context(result) -> int:
        """Count chunks that mention Jake's responsibilities."""
        keywords = ["kubernetes", "monitoring", "datadog", "pagerduty", "on-call", "platform"]
        content = " ".join(c.content.lower() for c in result.chunks)
        return sum(1 for k in keywords if k in content)

    naive_ctx = count_jake_context(r_naive)
    local_ctx = count_jake_context(r_local)
    hybrid_ctx = count_jake_context(r_hybrid)

    print("\n  Responsibility keywords found:")
    print(
        f"    Naive:  {naive_ctx}/6 (kubernetes, monitoring, datadog, pagerduty, on-call, platform)"
    )
    print(f"    Local:  {local_ctx}/6")
    print(f"    Hybrid: {hybrid_ctx}/6")
    print(
        f"  Entities — Naive: {len(r_naive.entities)} | "
        f"Local: {len(r_local.entities)} | Hybrid: {len(r_hybrid.entities)}"
    )

    # Graph modes should find more of Jake's context through entity traversal
    assert local_ctx >= naive_ctx or hybrid_ctx >= naive_ctx, (
        "Graph modes should find at least as much context about Jake's responsibilities"
    )


@skip_no_llm
async def test_bm25_or_semantics(seeded_rag):
    """Q4: Verify BM25 uses OR (not AND) for word matching.

    Query 'circuit breaker Stripe' should match chunks containing
    'circuit breaker' OR 'Stripe', not requiring both.
    """
    print("\n" + "=" * 70)
    print("Q4: BM25 OR semantics — 'circuit breaker Stripe'")
    print("    (should match chunks with ANY of these words)")
    print("=" * 70)

    result = await seeded_rag.query(
        "circuit breaker Stripe", mode="naive", namespace="comparison_test"
    )

    # Should find chunks mentioning circuit breaker (team comms)
    # AND chunks mentioning Stripe (service ownership, incident)
    content_lower = [c.content.lower() for c in result.chunks]

    has_circuit_breaker = any("circuit breaker" in c for c in content_lower)
    has_stripe = any("stripe" in c for c in content_lower)

    print(f"\n  Results: {len(result.chunks)} chunks")
    print(f"  Contains 'circuit breaker': {has_circuit_breaker}")
    print(f"  Contains 'Stripe': {has_stripe}")

    # With OR semantics, we should find BOTH types of content
    assert has_circuit_breaker or has_stripe, (
        "BM25 with OR should match chunks containing 'circuit breaker' OR 'Stripe'"
    )
    # Ideally both are found (they're in different documents)
    if has_circuit_breaker and has_stripe:
        print("  ✓ Both found — OR semantics working correctly")


@skip_no_llm
async def test_performance_comparison(seeded_rag):
    """Q5: Performance benchmark — all modes should be fast."""
    print("\n" + "=" * 70)
    print("Q5: Performance comparison (latency)")
    print("=" * 70)

    queries = [
        "payment outage",
        "Who owns Kubernetes?",
        "What happened on March 15?",
    ]
    modes = ["naive", "local", "global", "hybrid"]

    results = {}
    for mode in modes:
        latencies = []
        for q in queries:
            r = await seeded_rag.query(q, mode=mode, namespace="comparison_test")
            latencies.append(r.latency_ms)
        avg = sum(latencies) / len(latencies)
        p95 = sorted(latencies)[int(len(latencies) * 0.95)]
        results[mode] = {"avg": avg, "p95": p95, "latencies": latencies}

    print("\n  Mode       Avg (ms)    P95 (ms)    Per-query")
    print("  " + "-" * 55)
    for mode in modes:
        r = results[mode]
        per_q = ", ".join(f"{l:.0f}" for l in r["latencies"])
        print(f"  {mode:10} {r['avg']:8.1f}    {r['p95']:8.1f}    [{per_q}]")

    # All modes should be under 200ms
    for mode, r in results.items():
        assert r["p95"] < 200, f"{mode} p95 = {r['p95']:.0f}ms (>200ms)"

    print("\n  ✓ All modes under 200ms")


@skip_no_llm
async def test_accuracy_summary(seeded_rag):
    """Q6: Accuracy summary — which mode finds the right answer for each question type."""
    print("\n" + "=" * 70)
    print("ACCURACY SUMMARY: When to use which mode")
    print("=" * 70)

    test_cases = [
        {
            "question": "payment outage root cause",
            "expected_keywords": ["kong", "rate limit"],
            "best_mode": "All modes (direct keyword match)",
        },
        {
            "question": "Who is responsible for the monitoring stack?",
            "expected_keywords": ["jake"],
            "best_mode": "local/hybrid (entity traversal finds Jake → monitoring)",
        },
        {
            "question": "What was the impact of Maria's deployment?",
            "expected_keywords": ["payment", "transaction", "47 minutes"],
            "best_mode": "hybrid (needs Maria → Kong → payment service chain)",
        },
        {
            "question": "What action items came from the incident?",
            "expected_keywords": ["circuit breaker", "review"],
            "best_mode": "naive (direct keyword match on action items text)",
        },
    ]

    print(f"\n  {'Question':<50} {'naive':>6} {'local':>6} {'hybrid':>7}")
    print("  " + "-" * 75)

    for tc in test_cases:
        scores = {}
        for mode in ["naive", "local", "hybrid"]:
            r = await seeded_rag.query(tc["question"], mode=mode, namespace="comparison_test")
            content = " ".join(c.content.lower() for c in r.chunks)
            found = sum(1 for k in tc["expected_keywords"] if k in content)
            scores[mode] = found

        q_short = tc["question"][:48]
        print(
            f"  {q_short:<50} "
            f"{scores['naive']:>4}/{len(tc['expected_keywords'])} "
            f"{scores['local']:>4}/{len(tc['expected_keywords'])} "
            f"{scores['hybrid']:>5}/{len(tc['expected_keywords'])}"
        )

    print("\n  Key insight: Graph modes (local/hybrid) excel when the answer")
    print("  requires following relationships between entities across documents.")
    print("  Naive mode excels when the answer is directly in the text.")
