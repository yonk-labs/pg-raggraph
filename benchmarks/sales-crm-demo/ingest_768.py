"""768d ingest harness — same in-memory pipeline as ingest_inmemory.py
but configurable embedder + chunker. Used to isolate the contribution
of higher-dim embedder vs chunkshop chunker.

  uv run python benchmarks/sales-crm-demo/ingest_768.py --chunker auto              --namespace sales_crm_a_768
  uv run python benchmarks/sales-crm-demo/ingest_768.py --chunker chunkshop:hierarchy --namespace sales_crm_d_h_768
  uv run python benchmarks/sales-crm-demo/ingest_768.py --chunker chunkshop:semantic  --namespace sales_crm_d_s_768
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

import psycopg

from pg_raggraph import GraphRAG

# Reuse SQL + row_to_record from ingest_inmemory.py so the format/metadata/
# entities/relationships logic stays in one place.
sys.path.insert(0, str(Path(__file__).parent))
from ingest_inmemory import SQL, row_to_record  # noqa: E402

CRM_DSN = os.environ.get(
    "CRM_DSN", "postgresql://postgres:postgres@127.0.0.1:5434/crm_demo_small"
)
PGRG_DSN = os.environ.get(
    "PGRG_DSN", "postgresql://postgres:postgres@localhost:5434/pg_raggraph_768"
)
STATUSES = tuple(s.strip() for s in os.environ.get("STATUSES", "won").split(","))


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--chunker", default="auto",
                        help="auto | hierarchy | chunkshop:hierarchy | chunkshop:semantic | ...")
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--embedding-model", default="BAAI/bge-base-en-v1.5")
    parser.add_argument("--embedding-dim", type=int, default=768)
    args = parser.parse_args()

    print(f"CRM source: {CRM_DSN}")
    print(f"pgrg target: {PGRG_DSN}, namespace={args.namespace}")
    print(f"Embedder: {args.embedding_model} @ dim={args.embedding_dim}")
    print(f"Chunker: {args.chunker}")
    print(f"Filter: status IN {STATUSES}")

    with psycopg.connect(CRM_DSN, row_factory=psycopg.rows.dict_row) as crm_conn:
        with crm_conn.cursor() as cur:
            cur.execute(SQL, (list(STATUSES),))
            rows = cur.fetchall()
    print(f"Fetched {len(rows)} notes")

    records = [row_to_record(r) for r in rows]

    rag = GraphRAG(
        dsn=PGRG_DSN,
        namespace=args.namespace,
        embedding_provider="local",
        embedding_model=args.embedding_model,
        embedding_dim=args.embedding_dim,
        chunk_strategy=args.chunker,
        llm_base_url=os.environ.get("LLM_URL", "https://api.openai.com/v1"),
        llm_model=os.environ.get("LLM_MODEL", "gpt-4o-mini"),
        llm_api_key=os.environ.get("OPENAI_API_KEY", ""),
        extraction_prompt="dev",
        doc_concurrency=4,
        extract_concurrency=8,
    )
    await rag.connect()
    try:
        await rag.delete(args.namespace)
        await rag.ingest_records(records, namespace=args.namespace)
        status = await rag.status(args.namespace)
        print()
        print("=" * 60)
        print(
            f"[{args.namespace}] Done: {status['documents']} docs, "
            f"{status['chunks']} chunks, {status['entities']} entities, "
            f"{status['relationships']} rels"
        )
        print("=" * 60)
    finally:
        await rag.close()


if __name__ == "__main__":
    asyncio.run(main())
