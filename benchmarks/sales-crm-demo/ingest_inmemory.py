"""Ingest the demo CRM directly from SQL — no markdown disk roundtrip.

Same-database pipeline pattern: pull rows from the CRM tables, format
in memory, push through pg-raggraph's ingest_records() API. The
alternative (prepare.py + ingest.py) writes markdown to disk first;
this is shorter, faster, and the more natural shape when source and
target both live in the same Postgres instance.

Use this when:
  - Your source data lives in another schema/database
  - You don't want a disk roundtrip
  - You want a one-script ETL job (cron / trigger / API endpoint)

Use the disk-based pair (prepare.py + ingest.py) when:
  - You want the intermediate markdown for audit / human review
  - You need to re-ingest the same content many times for tuning
  - You want to fan out the markdown files to other consumers
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
NAMESPACE = os.environ.get("PGRG_NAMESPACE", "sales_crm_inmemory")
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

  so.order_id,
  so.status,
  so.total_value,
  so.actual_close_date,
  so.win_reason,
  so.lost_reason,

  c.customer_id,
  c.company_name,
  c.industry,
  c.hq_city,
  c.hq_state,
  c.hq_country,

  p.product_id,
  p.product_name,
  p.category,

  sp.salesperson_id,
  sp.name AS salesperson_name
FROM sales_demo_app.sales_notes sn
LEFT JOIN sales_demo_app.sales_orders so ON so.order_id = sn.order_id
LEFT JOIN sales_demo_app.customers c    ON c.customer_id = so.customer_id
LEFT JOIN sales_demo_app.products p     ON p.product_id  = so.product_id
LEFT JOIN sales_demo_app.salespeople sp ON sp.salesperson_id = sn.salesperson_id
WHERE so.status = ANY(%s)
ORDER BY so.actual_close_date DESC NULLS LAST, sn.created_at;
"""


def format_doc(row: dict) -> str:
    """Format a sales-note row as markdown text. Same shape as prepare.py
    writes to disk; this just keeps it in memory."""
    out = []
    date = (row["created_at"].strftime("%Y-%m-%d") if row["created_at"] else "no-date")
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
    """Convert a CRM row into an ingest_records() record dict."""
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
    }


async def main() -> None:
    print(f"CRM source: {CRM_DSN}")
    print(f"pgrg target: {PGRG_DSN}, namespace={NAMESPACE}")
    print(f"Filter: status IN {STATUSES}")

    # 1. Pull from CRM (no disk).
    with psycopg.connect(CRM_DSN, row_factory=psycopg.rows.dict_row) as crm_conn:
        with crm_conn.cursor() as cur:
            cur.execute(SQL, (list(STATUSES),))
            rows = cur.fetchall()
    print(f"Fetched {len(rows)} notes")

    # 2. Format in memory.
    records = [row_to_record(r) for r in rows]

    # 3. Push to pg-raggraph (no disk).
    rag = GraphRAG(
        dsn=PGRG_DSN,
        namespace=NAMESPACE,
        embedding_provider="local",
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
