"""Ingest the pooled MuSiQue paragraph corpus into pg-raggraph.

Reads every markdown doc under docs/ and ingests it into the
`bench_musique` namespace. The pooled corpus contains supporting +
distractor paragraphs from all sampled questions, dedup'd by
(title, paragraph_text).

Re-runs are idempotent: the (namespace, content_hash) UNIQUE constraint
on documents skips already-ingested docs.
"""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path

from pg_raggraph import GraphRAG

ROOT = Path(__file__).parent
DOCS_DIR = ROOT / "docs"
NAMESPACE = "bench_musique"
DSN = os.environ.get("PGRG_DSN", "postgresql://postgres:postgres@localhost:5434/pg_raggraph")
LLM_URL = os.environ.get("PGRG_TEST_LLM_URL", "http://192.168.1.193:8000/v1")
LLM_MODEL = os.environ.get("PGRG_TEST_LLM_MODEL", "Intel/Qwen3-Coder-Next-int4-AutoRound")


async def main() -> None:
    files = sorted(str(p) for p in DOCS_DIR.glob("*.md"))
    print(f"Ingesting {len(files)} paragraph docs into namespace={NAMESPACE}")

    rag = GraphRAG(
        dsn=DSN,
        namespace=NAMESPACE,
        llm_base_url=LLM_URL,
        llm_model=LLM_MODEL,
        doc_concurrency=4,
        extract_concurrency=16,
    )
    await rag.connect()
    try:
        t0 = time.perf_counter()
        # Single batch call so doc_concurrency parallelism kicks in.
        await rag.ingest(files, namespace=NAMESPACE)
        elapsed = time.perf_counter() - t0

        status = await rag.status(NAMESPACE)
        print(
            f"Done in {elapsed / 60:.1f}min: "
            f"{status['documents']} docs, "
            f"{status['chunks']} chunks, "
            f"{status['entities']} entities, "
            f"{status['relationships']} rels "
            f"({elapsed / max(status['documents'], 1):.1f}s/doc)"
        )
    finally:
        await rag.close()


if __name__ == "__main__":
    asyncio.run(main())
