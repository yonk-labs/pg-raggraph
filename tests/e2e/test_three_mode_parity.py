"""3-mode no-regression parity test for pg-raggraph.

Proves pg-raggraph returns EQUIVALENT retrieval whether it is reached as:
  1. EMBEDDED -- ``GraphRAG`` in-process, connected to the SAME postgres the
     proxy uses (bento-postgres, host-published on :5433).
  2. SERVICE  -- the proxy's ``POST /v1/query`` via ``docker exec ... curl``.
  3. BENTO    -- bento-api's ``POST /v1/admin/pg-raggraph/query`` (:8000),
     which forwards to the proxy after ``kb_id`` -> namespace resolution.

Design (fairness): the corpus is ingested ONCE via the proxy, so the stored
chunk embeddings are identical for all three modes. All three then QUERY that
one namespace with the same mode/top_k -- isolating the comparison to
retrieval logic, not ingest.

Config is mirrored from the proxy container's env (``docker exec
bento-pg-raggraph-proxy env | grep PGRG``) so the legs are comparable:
    PGRG_LEXICAL_BACKEND=ts_rank   PGRG_FUSION=linear
    PGRG_EMBEDDING_DIM=768         PGRG_EMBEDDING_PROVIDER=local
    PGRG_EVOLUTION_TIER=structural PGRG_MAX_HOPS=2
    PGRG_SUPERSESSION_BEHAVIOR=hide

EMBEDDING CAVEAT (reported, not hidden): the proxy embeds with
``Xenova/bge-base-en-v1.5-int8`` (int8-quantized ONNX). The host's fastembed
build does NOT ship that model id, so the EMBEDDED leg uses
``BAAI/bge-base-en-v1.5`` -- the SAME base model, 768-dim, but fp32 rather
than int8. Query embeddings are therefore NOT byte-identical between EMBEDDED
and SERVICE/BENTO; the fp32-vs-int8 gap can flip near-tie ranks on the vector
leg. Consequences, split by leg:

  - SERVICE vs BENTO: identical model AND config (bento-api is a thin
    forwarder) -> asserted EXACT (same ids, same rank order). Any divergence
    here is a genuine bento-wiring regression.
  - EMBEDDED vs SERVICE: same corpus, same retrieval SQL, embedding differs
    only by quantization -> asserted to a documented tolerance (top-k set
    overlap and top-1 agreement); exact rank order is reported, not required.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from pg_raggraph import GraphRAG

from .conftest import BENTO_API_BASE, delete_bento_namespace, proxy_request

pytestmark = pytest.mark.e2e

# bento-postgres is the proxy's DATABASE_URL target
# (postgresql://bento:bento@postgres:5432/bento inside the docker network),
# published to the host on :5433 -- the DSN the EMBEDDED leg connects with.
HOST_DSN = "postgresql://bento:bento@localhost:5433/bento"

# Same base model + dim as the proxy; fp32 host variant of the proxy's int8
# (see module docstring EMBEDDING CAVEAT).
EMBEDDED_CONFIG = dict(
    embedding_model="BAAI/bge-base-en-v1.5",
    embedding_dim=768,
    embedding_provider="local",
    lexical_backend="ts_rank",
    fusion="linear",
    evolution_tier="structural",
    max_hops=2,
    supersession_behavior="hide",
)

TOP_K = 5  # < corpus size, so rank actually discriminates

CORPUS = [
    "Incident INC-0001 root cause: disk pressure on the ingest worker at 02:00 UTC forced a restart.",
    "The billing service retries failed archive writes three times before paging the oncall engineer.",
    "Postgres connection pool exhaustion caused the checkout latency spike last Tuesday afternoon.",
    "Deployment rollback procedure: flip the feature flag, drain traffic, then redeploy the previous tag.",
    "The search relevance team tuned BM25 weights to improve recall on rare product identifiers.",
    "Nightly ETL loads the analytics warehouse; a schema drift broke the revenue dashboard on Monday.",
    "Kubernetes pod eviction under memory pressure restarted the recommendation model server twice.",
    "Customer support escalation SLA is four hours for priority-one authentication outages.",
    "The caching layer uses valkey with a sixty second TTL for hot product catalog reads.",
    "A migration lock held by a long transaction blocked the users table alter for twenty minutes.",
    "The CDN cache purge webhook fires on every publish to invalidate stale marketing pages.",
    "Load testing revealed the auth token endpoint saturates CPU at fifteen hundred requests per second.",
]

QUERIES = [
    "what caused the disk pressure incident",
    "how does the billing service handle failed writes",
    "why was checkout slow last week",
    "how do we roll back a deployment",
    "how did the team improve search recall",
    "what broke the revenue dashboard",
    "why did the model server restart",
    "what is the support SLA for auth outages",
    "what does the caching layer use",
    "what blocked the users table migration",
    "how is stale marketing content invalidated",
    "when does the auth endpoint saturate cpu",
]

# EMBEDDED vs SERVICE tolerance (fp32-vs-int8 query embedding, vector leg):
MIN_TOTAL_SET_OVERLAP = 0.90  # observed 0.983
MIN_TOP1_AGREEMENT = 0.75  # observed ~1.0 in prototyping
MIN_PER_QUERY_SET_OVERLAP = TOP_K - 1  # at most one slot may differ


def _bento_query(kb_id: str, question: str) -> list[int]:
    resp = httpx.post(
        f"{BENTO_API_BASE}/v1/admin/pg-raggraph/query",
        json={"kb_id": kb_id, "question": question, "mode": "naive", "top_k": TOP_K},
        timeout=20,
    )
    resp.raise_for_status()
    return [c["chunk_id"] for c in resp.json()["chunks"]]


def _service_query(namespace: str, question: str) -> list[int]:
    body = {"question": question, "mode": "naive", "namespace": namespace, "top_k": TOP_K}
    return [c["chunk_id"] for c in proxy_request("POST", "/v1/query", body)["chunks"]]


async def _embedded_all(namespace: str) -> dict[str, list[int]]:
    rag = GraphRAG(dsn=HOST_DSN, namespace=namespace, **EMBEDDED_CONFIG)
    await rag.connect()
    try:
        out = {}
        for q in QUERIES:
            res = await rag.query(q, mode="naive", top_k=TOP_K)
            out[q] = [c.chunk_id for c in res.chunks]
        return out
    finally:
        await rag.close()


@pytest.fixture(scope="module")
def parity_matrix():
    """Ingest the corpus ONCE via the proxy, then run all three modes for
    every query. Returns {query: {"embedded":[...], "service":[...],
    "bento":[...]}}. Module-scoped + sync (asyncio.run for the embedded leg)
    so the expensive embedder load happens once and there is no async-fixture
    loop-scope juggling.
    """
    ts = int(__import__("time").time())
    kb_id = f"test_pgrg_parity_{ts}"
    namespace = f"kb-{kb_id}"  # what bento's kb_namespace() resolves kb_id to

    try:
        try:
            GraphRAG(dsn=HOST_DSN, **EMBEDDED_CONFIG)._get_embedder()
        except Exception as exc:  # noqa: BLE001 -- host lacks the fastembed model
            pytest.skip(f"embedded embedder unavailable on host: {exc}")

        ingest = proxy_request(
            "POST",
            "/v1/ingest",
            {
                "records": [{"text": t, "source_id": f"parity:{i}"} for i, t in enumerate(CORPUS)],
                "namespace": namespace,
                "skip_extraction": True,
            },
        )
        assert ingest.get("chunks_written") == len(CORPUS), ingest

        embedded = asyncio.run(_embedded_all(namespace))
        matrix = {
            q: {
                "embedded": embedded[q],
                "service": _service_query(namespace, q),
                "bento": _bento_query(kb_id, q),
            }
            for q in QUERIES
        }
        _print_parity_table(matrix)
        yield matrix
    finally:
        delete_bento_namespace(namespace)


def _print_parity_table(matrix: dict) -> None:
    print("\n\n=== 3-MODE PARITY (mode=naive, top_k=%d, corpus=%d) ===" % (TOP_K, len(CORPUS)))
    print(f"{'query':44s} {'emb∩svc':>8s} {'emb=svc':>8s} {'svc=bnt':>8s} {'emb_t1=svc_t1':>13s}")
    es_set = sb_set = es_ord = sb_ord = es_t1 = 0
    for q in QUERIES:
        e, s, b = matrix[q]["embedded"], matrix[q]["service"], matrix[q]["bento"]
        o = len(set(e) & set(s))
        es_set += o
        sb_set += len(set(s) & set(b))
        es_ord += e == s
        sb_ord += s == b
        es_t1 += e[:1] == s[:1]
        print(f"{q[:44]:44s} {o:>6d}/{TOP_K} {str(e == s):>8s} {str(s == b):>8s} {str(e[:1] == s[:1]):>13s}")
    n = TOP_K * len(QUERIES)
    print("-" * 88)
    print(
        f"TOTALS: embedded∩service {es_set}/{n} ({es_set / n:.1%})  "
        f"service∩bento {sb_set}/{n} ({sb_set / n:.1%})"
    )
    print(
        f"        exact rank order  embedded=service {es_ord}/{len(QUERIES)}  "
        f"service=bento {sb_ord}/{len(QUERIES)}   "
        f"embedded/service top-1 {es_t1}/{len(QUERIES)}"
    )
    diverging = [q for q in QUERIES if matrix[q]["service"] != matrix[q]["bento"]]
    print(f"        service-vs-bento diverging queries: {diverging or 'none'}\n")


def test_service_and_bento_are_exactly_equal(parity_matrix):
    """PRIMARY no-regression gate. bento-api forwards to the same proxy with
    the same model+config, so retrieval must be byte-for-byte identical --
    same chunk ids in the same rank order for every query. A failure here is a
    real regression in the bento -> proxy wiring (e.g. a param dropped or
    reordered by the forwarder), not embedding noise."""
    mismatches = {
        q: (m["service"], m["bento"]) for q, m in parity_matrix.items() if m["service"] != m["bento"]
    }
    assert not mismatches, f"service vs bento diverged (wiring regression): {mismatches}"


def test_embedded_matches_service_within_quantization_tolerance(parity_matrix):
    """EMBEDDED (library, fp32 query embedding) vs SERVICE (proxy, int8).
    Same corpus + same retrieval SQL; only the query embedding differs by
    quantization, so we assert top-k SET overlap and top-1 agreement to a
    documented tolerance rather than exact rank order (reported below)."""
    n = TOP_K * len(QUERIES)
    total_overlap = sum(
        len(set(m["embedded"]) & set(m["service"])) for m in parity_matrix.values()
    )
    top1 = sum(m["embedded"][:1] == m["service"][:1] for m in parity_matrix.values())
    thin = {
        q: (m["embedded"], m["service"])
        for q, m in parity_matrix.items()
        if len(set(m["embedded"]) & set(m["service"])) < MIN_PER_QUERY_SET_OVERLAP
    }

    assert not thin, f"embedded vs service overlap < {MIN_PER_QUERY_SET_OVERLAP}/{TOP_K}: {thin}"
    assert total_overlap / n >= MIN_TOTAL_SET_OVERLAP, (
        f"embedded∩service {total_overlap}/{n} ({total_overlap / n:.1%}) "
        f"below tolerance {MIN_TOTAL_SET_OVERLAP:.0%}"
    )
    assert top1 / len(QUERIES) >= MIN_TOP1_AGREEMENT, (
        f"embedded/service top-1 agreement {top1}/{len(QUERIES)} below {MIN_TOP1_AGREEMENT:.0%}"
    )
