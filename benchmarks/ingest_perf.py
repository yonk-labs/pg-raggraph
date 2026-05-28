"""Throwaway ingest-performance probe.

Measures the FAST ingest path (chunk + embed + store, skip_llm=True) on a real
corpus and isolates embedding cost — the suspected bottleneck. The full
LLM-extraction arm is deferred (Ollama not assumed up); the point of this probe
is the "non-event" floor that fast-ingest + background extraction would deliver.

Variants:
  --provider local   FastEmbedProvider (in-process, default)
  --provider http    HttpxEmbeddingProvider against --base-url
                     (typical setup: TEI in Docker)

Run:
  uv run python -m benchmarks.ingest_perf --docs 20
  uv run python -m benchmarks.ingest_perf --docs 20 --provider http \\
      --base-url http://localhost:8081 --model BAAI/bge-small-en-v1.5
"""

import argparse
import asyncio
import time

from benchmarks.e2e.datasets.mhr import load as load_mhr
from pg_raggraph import GraphRAG
from pg_raggraph.chunking import chunk_document
from pg_raggraph.config import PGRGConfig


TEST_DSN = "postgresql://postgres:postgres@localhost:5434/pg_raggraph"
NS = "ingest_perf_probe"


def _make_rag(provider: str, base_url: str | None, model: str | None, dim: int) -> GraphRAG:
    kwargs: dict = {"dsn": TEST_DSN, "namespace": NS, "embedding_dim": dim}
    if provider == "http":
        if not base_url:
            raise SystemExit("--base-url required when --provider http")
        kwargs["embedding_provider"] = "http"
        kwargs["embedding_base_url"] = base_url
        if model:
            kwargs["embedding_model"] = model
    elif provider == "local":
        if model:
            kwargs["embedding_model"] = model
    else:
        raise SystemExit(f"unknown --provider: {provider}")
    return GraphRAG(**kwargs)


async def main(n_docs: int, provider: str, base_url: str | None, model: str | None, dim: int) -> None:
    bundle = load_mhr()
    docs = bundle.corpus_docs[:n_docs]
    total_chars = sum(len(d.text) for d in docs)
    label = f"provider={provider}"
    if model:
        label += f" model={model}"
    if base_url:
        label += f" base_url={base_url}"
    print(f"{label}")
    print(f"corpus: {len(docs)} docs, {total_chars:,} chars")

    cfg = PGRGConfig(dsn=TEST_DSN, namespace=NS, embedding_dim=dim)
    rag = _make_rag(provider, base_url, model, dim)
    await rag.connect()
    await rag.delete(NS)  # clean slate

    embedder = rag._get_embedder()

    # --- chunking only ---
    t0 = time.perf_counter()
    all_chunks: list[str] = []
    for d in docs:
        all_chunks.extend(c["content"] for c in chunk_document(d.text, config=cfg))
    t_chunk = time.perf_counter() - t0
    n_chunks = len(all_chunks)

    # Warm the embedder model thoroughly (untimed) so first-batch ONNX/thread
    # spin-up doesn't contaminate the cold-ingest measurement.
    await embedder.embed(all_chunks)

    records = [
        {
            "text": d.text,
            "source_id": f"perf:{d.source_id}",
            "metadata": dict(d.metadata),
            "skip_llm": True,
        }
        for d in docs
    ]

    # --- COLD ingest: embedding cache empty for these texts -> real embedding ---
    await rag.delete(NS)
    await rag._db.execute("DELETE FROM embedding_cache")  # force cache misses
    t0 = time.perf_counter()
    await rag.ingest_records(records, namespace=NS)
    t_cold = time.perf_counter() - t0

    # --- WARM ingest: same texts, cache now populated -> embedding skipped ---
    await rag.delete(NS)
    t0 = time.perf_counter()
    await rag.ingest_records(records, namespace=NS)
    t_warm = time.perf_counter() - t0

    t_embed = t_cold - t_warm  # delta isolates real embedding cost

    await rag.delete(NS)
    await rag.close()

    print("\n=== fast-path ingest (skip_llm=True) ===")
    print(f"  docs={len(docs)}  chunks={n_chunks}  chars={total_chars:,}")
    print(
        f"  chunk-only:            {t_chunk:7.2f}s  "
        f"({1000 * t_chunk / n_chunks:6.1f} ms/chunk)  [negligible]"
    )
    print(
        f"  COLD ingest (real embed): {t_cold:7.2f}s  "
        f"({1000 * t_cold / len(docs):6.1f} ms/doc, {1000 * t_cold / n_chunks:.1f} ms/chunk)"
    )
    print(
        f"  WARM ingest (cache hit):  {t_warm:7.2f}s  "
        f"({1000 * t_warm / len(docs):6.1f} ms/doc, {1000 * t_warm / n_chunks:.1f} ms/chunk)"
    )
    print(
        f"  embedding cost (cold-warm): {t_embed:7.2f}s  "
        f"({100 * t_embed / t_cold:.0f}% of cold ingest, {1000 * t_embed / n_chunks:.0f} ms/chunk)"
    )
    print(f"  store+overhead (warm):  {t_warm:7.2f}s")
    print(f"  cold throughput: {len(docs) / t_cold:.1f} docs/s, {n_chunks / t_cold:.0f} chunks/s")
    print(f"  warm throughput: {len(docs) / t_warm:.1f} docs/s, {n_chunks / t_warm:.0f} chunks/s")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--docs", type=int, default=20)
    ap.add_argument("--provider", choices=["local", "http"], default="local")
    ap.add_argument("--base-url", default=None, help="HTTP embedding endpoint base URL")
    ap.add_argument("--model", default=None, help="Override embedding_model (e.g. BAAI/bge-large-en-v1.5)")
    ap.add_argument("--dim", type=int, default=384, help="Embedding dimension (must match the chosen model)")
    a = ap.parse_args()
    asyncio.run(main(a.docs, a.provider, a.base_url, a.model, a.dim))
