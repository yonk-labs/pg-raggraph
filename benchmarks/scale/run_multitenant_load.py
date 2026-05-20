"""Phase 4 multi-tenant load harness.

Seeds 50 namespaces with 2,000 chunks each, runs 200 concurrent queries with
two-stage retrieval on and off, asserts no cross-tenant leaks and no pool
timeouts, then writes benchmark evidence to benchmarks/scale-results/.
"""

from __future__ import annotations

import asyncio
import json
import os
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path

from pg_raggraph import GraphRAG

DSN = os.environ.get(
    "PGRG_TEST_DSN",
    "postgresql://postgres:postgres@localhost:5434/pg_raggraph",
)
NAMESPACES = int(os.environ.get("PGRG_LOAD_NAMESPACES", "50"))
CHUNKS_PER_NAMESPACE = int(os.environ.get("PGRG_LOAD_CHUNKS_PER_NAMESPACE", "2000"))
CONCURRENT_QUERIES = int(os.environ.get("PGRG_LOAD_CONCURRENT_QUERIES", "200"))
P99_TARGET_MS = float(os.environ.get("PGRG_LOAD_P99_TARGET_MS", "10000"))
TOP_K = int(os.environ.get("PGRG_LOAD_TOP_K", "5"))
EMBEDDING_DIM = 384
RESULT_DIR = Path("benchmarks/scale-results")


class SyntheticEmbedder:
    @property
    def dimension(self) -> int:
        return EMBEDDING_DIM

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [_vector_for_text(text) for text in texts]


def _namespace(i: int) -> str:
    return f"mt_{i:03d}"


def _vector_for_namespace(ns: str) -> list[float]:
    vec = [0.0] * EMBEDDING_DIM
    vec[int(ns.rsplit("_", 1)[1]) % EMBEDDING_DIM] = 1.0
    return vec


def _vector_for_text(text: str) -> list[float]:
    for token in text.split():
        if token.startswith("mt_"):
            return _vector_for_namespace(token.strip("?:,."))
    return _vector_for_namespace("mt_000")


def _percentile(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, int(round((pct / 100) * (len(ordered) - 1)))))
    return ordered[idx]


async def _seed_corpus(rag: GraphRAG) -> None:
    expected = NAMESPACES * CHUNKS_PER_NAMESPACE
    existing = await rag.db.fetch_one(
        "SELECT count(*) AS cnt FROM chunks c "
        "JOIN documents d ON d.id = c.document_id "
        "WHERE d.namespace LIKE 'mt\\_%' ESCAPE '\\'"
    )
    if existing and existing["cnt"] == expected:
        return

    await rag.db.execute("DELETE FROM relationships WHERE namespace LIKE 'mt\\_%' ESCAPE '\\'")
    await rag.db.execute("DELETE FROM entities WHERE namespace LIKE 'mt\\_%' ESCAPE '\\'")
    await rag.db.execute("DELETE FROM documents WHERE namespace LIKE 'mt\\_%' ESCAPE '\\'")

    for i in range(NAMESPACES):
        ns = _namespace(i)
        vector = _vector_for_namespace(ns)
        async with rag.db.transaction() as tx:
            doc_id = await tx.insert_returning_id(
                "INSERT INTO documents (namespace, content_hash, source_path, metadata) "
                "VALUES (%s, %s, %s, %s::jsonb) RETURNING id",
                (ns, f"{ns}-hash", f"{ns}/load-doc", "{}"),
            )
            rows = [
                (
                    doc_id,
                    f"{ns} tenant document chunk {j} load-test marker",
                    f"{ns} tenant document chunk {j} load-test marker",
                    vector,
                    8,
                    json.dumps({"namespace": ns, "chunk": j}),
                )
                for j in range(CHUNKS_PER_NAMESPACE)
            ]
            await tx.executemany(
                "INSERT INTO chunks "
                "(document_id, content, embedded_content, embedding, token_count, metadata) "
                "VALUES (%s, %s, %s, %s, %s, %s::jsonb)",
                rows,
            )

    await rag.db.execute("ANALYZE documents")
    await rag.db.execute("ANALYZE chunks")


async def _run_queries(two_stage: bool) -> dict:
    rag = GraphRAG(
        DSN,
        namespace="mt_000",
        skip_extraction=True,
        embedding_provider="http",
        embedding_base_url="http://synthetic.invalid/v1",
        two_stage_retrieval=two_stage,
        retrieval_candidate_k=200,
        top_k=TOP_K,
        pool_min=2,
        pool_max=50,
        statement_timeout_ms=15000,
    )
    rag._embedder = SyntheticEmbedder()
    await rag.connect()
    latencies: list[float] = []
    leaks: list[dict] = []
    errors: list[str] = []
    result_count_failures: list[dict] = []

    async def one_query(i: int) -> None:
        ns = _namespace(i % NAMESPACES)
        started = time.perf_counter()
        try:
            result = await rag.query(f"{ns} load test query {i}", mode="naive", namespace=ns)
            latencies.append((time.perf_counter() - started) * 1000)
            chunk_count = len(result.chunks)
            if chunk_count == 0:
                result_count_failures.append(
                    {
                        "query_index": i,
                        "query_namespace": ns,
                        "expected_min_chunks": TOP_K,
                        "actual_chunks": chunk_count,
                        "failure": "empty_result",
                    }
                )
            elif chunk_count < TOP_K:
                result_count_failures.append(
                    {
                        "query_index": i,
                        "query_namespace": ns,
                        "expected_min_chunks": TOP_K,
                        "actual_chunks": chunk_count,
                        "failure": "short_result",
                    }
                )
            for chunk in result.chunks:
                if chunk.document_source != f"{ns}/load-doc":
                    leaks.append(
                        {
                            "query_namespace": ns,
                            "document_source": chunk.document_source,
                            "chunk_id": chunk.chunk_id,
                        }
                    )
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")

    await asyncio.gather(*(one_query(i) for i in range(CONCURRENT_QUERIES)))
    await rag.close()

    if errors:
        raise AssertionError(f"{len(errors)} query errors; first={errors[0]}")
    if leaks:
        raise AssertionError(f"{len(leaks)} cross-tenant leaks; first={leaks[0]}")
    if result_count_failures:
        raise AssertionError(
            f"{len(result_count_failures)} result count failures; first={result_count_failures[0]}"
        )

    p99 = _percentile(latencies, 99)
    if p99 > P99_TARGET_MS:
        raise AssertionError(f"p99 {p99:.1f}ms exceeded target {P99_TARGET_MS:.1f}ms")

    return {
        "two_stage": two_stage,
        "queries": len(latencies),
        "p50_ms": statistics.median(latencies),
        "p95_ms": _percentile(latencies, 95),
        "p99_ms": p99,
        "max_ms": max(latencies),
        "cross_tenant_leaks": len(leaks),
        "query_errors": len(errors),
        "correctness_failures": len(result_count_failures),
        "result_count_failures": len(result_count_failures),
        "empty_results": sum(
            1 for failure in result_count_failures if failure["failure"] == "empty_result"
        ),
        "short_results": sum(
            1 for failure in result_count_failures if failure["failure"] == "short_result"
        ),
    }


async def main() -> None:
    started = time.perf_counter()
    setup = GraphRAG(
        DSN,
        namespace="mt_000",
        skip_extraction=True,
        embedding_provider="http",
        embedding_base_url="http://synthetic.invalid/v1",
        pool_min=2,
        pool_max=20,
    )
    setup._embedder = SyntheticEmbedder()
    await setup.connect()
    await _seed_corpus(setup)
    await setup.close()

    two_stage = await _run_queries(True)
    single_stage = await _run_queries(False)
    result = {
        "timestamp": datetime.now(UTC).isoformat(),
        "dsn": DSN.replace("postgres:postgres@", "***:***@"),
        "namespaces": NAMESPACES,
        "chunks_per_namespace": CHUNKS_PER_NAMESPACE,
        "total_chunks": NAMESPACES * CHUNKS_PER_NAMESPACE,
        "concurrent_queries": CONCURRENT_QUERIES,
        "top_k": TOP_K,
        "p99_target_ms": P99_TARGET_MS,
        "two_stage": two_stage,
        "single_stage": single_stage,
        "two_stage_vs_single_stage_p99_delta_ms": two_stage["p99_ms"] - single_stage["p99_ms"],
        "pool_exhausted": False,
        "duration_s": time.perf_counter() - started,
    }

    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULT_DIR / "2026-05-20-multitenant-load.json"
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())
