"""Pull won-deal call notes from the demo CRM and format as markdown docs.

Each note becomes one .md file with structured frontmatter so chunks
keep customer/product/deal context even when split mid-doc.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import psycopg

CRM_DSN = os.environ.get(
    "CRM_DSN",
    "postgresql://sales_demo_app:salesdemo123@127.0.0.1:5432/postgres",
)
OUT = Path(__file__).parent / "docs"
OUT.mkdir(parents=True, exist_ok=True)

# Default: won deals only (the canonical "what worked" slice). To use both,
# set STATUSES="won,lost" via env.
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
  so.expected_close_date,
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


def slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", (text or "untitled")).strip("-")[:80]


def format_doc(row: dict) -> str:
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
        f"**Deal:** Order #{row['order_id']} ({row['status']},"
        f" ${row['total_value']}, "
        f"closed {row['actual_close_date'] or 'pending'})\n"
    )
    if row["product_name"]:
        out.append(
            f"**Product:** {row['product_name']} "
            f"({row['category'] or 'uncategorized'})\n"
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


def main():
    print(f"Connecting to {CRM_DSN}")
    print(f"Filter: status IN {STATUSES}")
    with psycopg.connect(CRM_DSN, row_factory=psycopg.rows.dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(SQL, (list(STATUSES),))
            rows = cur.fetchall()
    print(f"Fetched {len(rows)} notes")

    for row in rows:
        path = OUT / f"note-{row['note_id']:06d}-{slug(row['company_name'])}.md"
        path.write_text(format_doc(row))
    print(f"Wrote {len(rows)} markdown files to {OUT}")


if __name__ == "__main__":
    main()
