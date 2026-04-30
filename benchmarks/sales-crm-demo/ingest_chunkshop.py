"""Ingest the demo CRM via chunkshop's chunker (Pattern D).

Same SQL pipeline as ingest_inmemory.py — pull rows from the CRM, format
in memory, push through ingest_records — but the chunking step is
delegated to chunkshop's HierarchyChunker. chunkshop is the recommended
chunker for any markdown-shaped corpus; it tends to produce cleaner
section boundaries than our built-in chunker, especially when the
notes carry structured frontmatter.

Requires: pip install 'pg-raggraph[chunkshop]'

Use this when:
  - You want the proven chunkshop hierarchy chunker (heading-prefixed
    chunks, configured + tuned across multiple bake-off corpora).
  - You're going to run more sophisticated benchmarks down the road —
    keeping the same chunker as chunkshop's own factorial benchmarks
    means results compare directly.

Use ingest_inmemory.py when:
  - You don't want to install chunkshop.
  - The built-in chunker is good enough for your corpus shape.

If you also want chunkshop's metadata extractors (RAKE keywords,
spaCy entities, KeyBERT phrases, lang detection) and pre-computed
embeddings, see the "Pattern C" section in
docs/cookbook/chunkshop-integration.md — that's the full chunkshop
pipeline with pg-raggraph reading its output table.
"""

from __future__ import annotations

import asyncio
import os

import psycopg

from pg_raggraph import GraphRAG

CRM_DSN = os.environ.get(
    "CRM_DSN",
    "postgresql://postgres:postgres@127.0.0.1:5434/crm_demo_small",
)
PGRG_DSN = os.environ.get(
    "PGRG_DSN", "postgresql://postgres:postgres@localhost:5434/pg_raggraph"
)
NAMESPACE = os.environ.get("PGRG_NAMESPACE", "sales_crm_chunkshop")
STATUSES = tuple(s.strip() for s in os.environ.get("STATUSES", "won").split(","))


SQL = """
SELECT
  sn.note_id,
  sn.note_text,
  sn.note_type,
  sn.sentiment,
  sn.created_at,
  sn.use_case_mentioned,
  sn.use_case,
  so.order_id, so.status, so.total_value, so.actual_close_date,
  so.win_reason, so.lost_reason,
  c.customer_id, c.company_name, c.industry,
  c.hq_city, c.hq_state, c.hq_country,
  p.product_id, p.product_name, p.category,
  sp.salesperson_id, sp.name AS salesperson_name
FROM sales_demo_app.sales_notes sn
LEFT JOIN sales_demo_app.sales_orders so ON so.order_id = sn.order_id
LEFT JOIN sales_demo_app.customers c    ON c.customer_id = so.customer_id
LEFT JOIN sales_demo_app.products p     ON p.product_id  = so.product_id
LEFT JOIN sales_demo_app.salespeople sp ON sp.salesperson_id = sn.salesperson_id
WHERE so.status = ANY(%s)
ORDER BY so.actual_close_date DESC NULLS LAST, sn.created_at;
"""


def format_doc(row: dict) -> str:
    out = []
    date = row["created_at"].strftime("%Y-%m-%d") if row["created_at"] else "no-date"
    out.append(
        f"# Sales call note — {row['company_name']} / "
        f"{row['product_name'] or 'no product'} / {date}\n\n"
    )
    out.append(
        f"**Customer:** {row['company_name']}"
        f" ({row['industry'] or 'unknown industry'}"
        f" · {row['hq_city'] or '?'}, {row['hq_state'] or '?'}, {row['hq_country'] or '?'})\n"
    )
    out.append(
        f"**Deal:** Order #{row['order_id']} ({row['status']}, "
        f"${row['total_value']}, closed {row['actual_close_date'] or 'pending'})\n"
    )
    if row["product_name"]:
        out.append(
            f"**Product:** {row['product_name']} ({row['category'] or 'uncategorized'})\n"
        )
    out.append(f"**Salesperson:** {row['salesperson_name'] or 'unknown'}\n")
    out.append(f"**Note type:** {row['note_type'] or 'unspecified'}\n")
    out.append(f"**Sentiment:** {row['sentiment'] or 'unspecified'}\n")
    if row["use_case_mentioned"]:
        out.append(f"**Use cases:** {', '.join(row['use_case_mentioned'])}\n")
    out.append("\n## Notes\n\n")
    out.append((row["note_text"] or "").strip() + "\n")
    if row["win_reason"]:
        out.append(f"\n## Win reason\n\n{row['win_reason']}\n")
    if row["lost_reason"]:
        out.append(f"\n## Lost reason\n\n{row['lost_reason']}\n")
    return "".join(out)


def row_to_record(row: dict) -> dict:
    company = row["company_name"]
    product = row["product_name"]
    salesperson = row["salesperson_name"]

    entities = []
    if company:
        entities.append({
            "name": company,
            "entity_type": "Customer",
            "description": (
                f"{row.get('industry') or ''} "
                f"{row.get('hq_city') or ''}, {row.get('hq_state') or ''}"
            ).strip(),
        })
    if product:
        entities.append({
            "name": product,
            "entity_type": "Product",
            "description": row.get("category") or "",
        })
    if salesperson:
        entities.append({"name": salesperson, "entity_type": "Salesperson"})

    relationships = []
    if company and product:
        relationships.append({
            "src": company, "dst": product, "rel_type": "BOUGHT",
            "description": f"order #{row['order_id']} ({row['status']})",
        })
    if salesperson and company:
        relationships.append({
            "src": salesperson, "dst": company, "rel_type": "SOLD_TO",
        })
    if company and row.get("use_case"):
        relationships.append({
            "src": company, "dst": row["use_case"], "rel_type": "HAS_USE_CASE",
        })
        entities.append({"name": row["use_case"], "entity_type": "UseCase"})

    return {
        "text": format_doc(row),
        "source_id": f"sales_note:{row['note_id']}",
        "metadata": {
            "order_id": row["order_id"],
            "customer_id": row["customer_id"],
            "product_id": row["product_id"],
            "salesperson_id": row["salesperson_id"],
            "status": row["status"],
            "sentiment": row["sentiment"],
            "note_type": row["note_type"],
            "primary_use_case": row["use_case"],
            "use_cases_mentioned": row["use_case_mentioned"] or [],
        },
        "entities": entities,
        "relationships": relationships,
    }


async def main() -> None:
    print(f"CRM source: {CRM_DSN}")
    print(f"pgrg target: {PGRG_DSN}, namespace={NAMESPACE}")
    print(f"Filter: status IN {STATUSES}")
    print("Chunker: chunkshop:hierarchy (optional dep — pip install 'pg-raggraph[chunkshop]')")

    with psycopg.connect(CRM_DSN, row_factory=psycopg.rows.dict_row) as crm_conn:
        with crm_conn.cursor() as cur:
            cur.execute(SQL, (list(STATUSES),))
            rows = cur.fetchall()
    print(f"Fetched {len(rows)} notes")

    records = [row_to_record(r) for r in rows]

    rag = GraphRAG(
        dsn=PGRG_DSN,
        namespace=NAMESPACE,
        embedding_provider="local",
        # The single line that switches us to chunkshop:
        chunk_strategy="chunkshop:hierarchy",
        llm_base_url=os.environ.get("LLM_URL", "https://api.openai.com/v1"),
        llm_model=os.environ.get("LLM_MODEL", "gpt-4o-mini"),
        llm_api_key=os.environ.get("OPENAI_API_KEY", ""),
        extraction_prompt="dev",
        doc_concurrency=4,
        extract_concurrency=8,
    )
    await rag.connect()
    try:
        await rag.ingest_records(records, namespace=NAMESPACE)
        status = await rag.status(NAMESPACE)
        print()
        print("=" * 60)
        print(
            f"Done: {status['documents']} docs, {status['chunks']} chunks, "
            f"{status['entities']} entities, {status['relationships']} rels"
        )
        print("=" * 60)
    finally:
        await rag.close()


if __name__ == "__main__":
    asyncio.run(main())
