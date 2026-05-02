"""Build self-contained SQL sample(s) of the demo sales CRM.

Reads the live demo database, writes one .sql file per tier:

  small  (200 won + 100 lost deals)  → quick iteration, ~0.8 MB
  medium (700 won + 300 lost deals)  → realistic shape, ~3-4 MB

Each .sql file loads into any Postgres 14+ via:

    psql -h <host> -d <db> -f docs/cookbook/samples/sales-crm-demo-small.sql

This is a one-shot helper — the resulting .sql files are the actual
deliverables. Re-run if the demo data ever changes.

Usage:
    python _build_sample.py            # builds both small and medium
    python _build_sample.py --tier small
    python _build_sample.py --tier medium
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import psycopg

CRM_DSN = os.environ.get(
    "CRM_DSN",
    "postgresql://sales_demo_app:salesdemo123@127.0.0.1:5432/postgres",
)
HERE = Path(__file__).parent
SCHEMA_DUMP = Path("/tmp/sales-crm-demo-schema.sql")  # produced by pg_dump --schema-only

TIERS = {
    "small": {"won": 200, "lost": 100},
    "medium": {"won": 700, "lost": 300},
}
SEED = 20260430


def quote_value(v) -> str:
    import datetime
    import json

    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, dict):
        # jsonb columns — emit valid JSON, escape single quotes once
        s = json.dumps(v).replace("'", "''")
        return f"'{s}'::jsonb"
    if isinstance(v, list):
        # text[] columns — postgres array literal. Each element is a string
        # to embed; escape backslashes and double-quotes per pg's array syntax.
        parts = []
        for x in v:
            xs = str(x).replace("\\", "\\\\").replace('"', '\\"')
            parts.append(f'"{xs}"')
        inner = ",".join(parts)
        return f"'{{{inner}}}'"
    if isinstance(v, (datetime.date, datetime.datetime)):
        return f"'{v.isoformat()}'"
    s = str(v).replace("\\", "\\\\").replace("'", "''")
    return f"'{s}'"


def insert_rows(table: str, rows: list[dict], cols: list[str]) -> str:
    if not rows:
        return f"-- no rows for {table}\n"
    lines = [f"-- {table}: {len(rows)} rows"]
    col_list = ", ".join(cols)
    for r in rows:
        vals = ", ".join(quote_value(r[c]) for c in cols)
        lines.append(f"INSERT INTO sales_demo_app.{table} ({col_list}) VALUES ({vals});")
    return "\n".join(lines) + "\n\n"


def _clean_schema_dump(s: str) -> str:
    """Strip pg-version-specific noise so the dump loads on PG 14+."""
    out = []
    skip_trigger = False
    for line in s.splitlines():
        # PG18-specific psql restrict directives
        if line.startswith("\\restrict ") or line.startswith("\\unrestrict "):
            continue
        # PG18-specific session var
        if line.strip() == "SET transaction_timeout = 0;":
            continue
        # CREATE TRIGGER blocks reference functions we don't bundle
        if line.startswith("CREATE TRIGGER "):
            skip_trigger = True
        if skip_trigger:
            if line.rstrip().endswith(";"):
                skip_trigger = False
            continue
        out.append(line)
    return "\n".join(out)


def build_tier(tier_name: str, won_n: int, lost_n: int, schema_sql: str):
    out_path = HERE / f"sales-crm-demo-{tier_name}.sql"
    schema_sql = _clean_schema_dump(schema_sql)

    with psycopg.connect(CRM_DSN, row_factory=psycopg.rows.dict_row) as conn:
        with conn.cursor() as cur:
            # Sample deal IDs (stable seed)
            cur.execute(
                "SELECT order_id FROM sales_demo_app.sales_orders "
                "WHERE status='won' ORDER BY md5(order_id::text || %s::text) LIMIT %s",
                (str(SEED), won_n),
            )
            won_ids = [r["order_id"] for r in cur.fetchall()]
            cur.execute(
                "SELECT order_id FROM sales_demo_app.sales_orders "
                "WHERE status='lost' ORDER BY md5(order_id::text || %s::text) LIMIT %s",
                (str(SEED), lost_n),
            )
            lost_ids = [r["order_id"] for r in cur.fetchall()]
            order_ids = won_ids + lost_ids
            print(
                f"\n[{tier_name}] {len(won_ids)} won + {len(lost_ids)} lost = {len(order_ids)} deals"
            )

            # Pull orders
            cur.execute(
                "SELECT * FROM sales_demo_app.sales_orders WHERE order_id = ANY(%s) ORDER BY order_id",
                (order_ids,),
            )
            orders = cur.fetchall()
            order_cols = list(orders[0].keys()) if orders else []

            # Notes for those orders
            cur.execute(
                "SELECT * FROM sales_demo_app.sales_notes WHERE order_id = ANY(%s) ORDER BY note_id",
                (order_ids,),
            )
            notes = cur.fetchall()
            note_cols = [c for c in (notes[0].keys() if notes else []) if c != "note_text_tsv"]
            # tsvector regenerates from trigger; don't dump it.

            # Distinct dependencies
            customer_ids = sorted({r["customer_id"] for r in orders if r["customer_id"]})
            product_ids = sorted({r["product_id"] for r in orders if r["product_id"]})
            salesperson_ids = sorted(
                {r["salesperson_id"] for r in orders if r["salesperson_id"]}
                | {r["salesperson_id"] for r in notes if r["salesperson_id"]}
            )

            cur.execute(
                "SELECT * FROM sales_demo_app.customers WHERE customer_id = ANY(%s) ORDER BY customer_id",
                (customer_ids,),
            )
            customers = cur.fetchall()
            customer_cols = list(customers[0].keys()) if customers else []

            cur.execute(
                "SELECT * FROM sales_demo_app.products WHERE product_id = ANY(%s) ORDER BY product_id",
                (product_ids,),
            )
            products = cur.fetchall()
            product_cols = list(products[0].keys()) if products else []

            cur.execute(
                "SELECT * FROM sales_demo_app.salespeople WHERE salesperson_id = ANY(%s) ORDER BY salesperson_id",
                (salesperson_ids,),
            )
            salespeople = cur.fetchall()
            sp_cols = list(salespeople[0].keys()) if salespeople else []

    print(
        f"  loaded: {len(customers)} customers, {len(products)} products, "
        f"{len(salespeople)} salespeople, {len(orders)} orders, {len(notes)} notes"
    )

    # 2. Stitch together: schema + data inserts in dependency order.
    sql_parts = [
        f"-- Sales CRM demo dataset for pg-raggraph cookbook (tier: {tier_name}).",
        "-- Synthetic data; safe to share. See docs/cookbook/sales-crm-ingestion.md.",
        f"-- Sample: {won_n} won + {lost_n} lost deals + dependencies.",
        "-- Generated 2026-04-30.",
        "",
        "BEGIN;",
        "CREATE SCHEMA IF NOT EXISTS sales_demo_app;",
        "",
        schema_sql.strip(),
        "",
        "-- Data (dependency order: salespeople, customers, products → orders → notes).",
        "",
        insert_rows("salespeople", salespeople, sp_cols),
        insert_rows("customers", customers, customer_cols),
        insert_rows("products", products, product_cols),
        insert_rows("sales_orders", orders, order_cols),
        insert_rows("sales_notes", notes, note_cols),
        "-- Reset sequences to past max to keep new inserts conflict-free.",
        "SELECT setval('sales_demo_app.salespeople_salesperson_id_seq', "
        "(SELECT MAX(salesperson_id) FROM sales_demo_app.salespeople));",
        "SELECT setval('sales_demo_app.customers_customer_id_seq', "
        "(SELECT MAX(customer_id) FROM sales_demo_app.customers));",
        "SELECT setval('sales_demo_app.products_product_id_seq', "
        "(SELECT MAX(product_id) FROM sales_demo_app.products));",
        "SELECT setval('sales_demo_app.sales_orders_order_id_seq', "
        "(SELECT MAX(order_id) FROM sales_demo_app.sales_orders));",
        "SELECT setval('sales_demo_app.sales_notes_note_id_seq', "
        "(SELECT MAX(note_id) FROM sales_demo_app.sales_notes));",
        "",
        "COMMIT;",
    ]

    out_path.write_text("\n".join(sql_parts))
    size_mb = out_path.stat().st_size / 1024 / 1024
    print(f"  wrote {out_path.name} ({size_mb:.2f} MB)")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--tier",
        choices=list(TIERS.keys()) + ["all"],
        default="all",
        help="Which tier(s) to generate.",
    )
    args = parser.parse_args()

    schema_sql = SCHEMA_DUMP.read_text() if SCHEMA_DUMP.exists() else ""
    if not schema_sql:
        raise SystemExit(
            "Run first:  pg_dump -h 127.0.0.1 -U sales_demo_app -d postgres "
            "--schema=sales_demo_app --schema-only "
            "--table=sales_demo_app.salespeople "
            "--table=sales_demo_app.customers "
            "--table=sales_demo_app.products "
            "--table=sales_demo_app.sales_orders "
            "--table=sales_demo_app.sales_notes "
            "--no-owner --no-privileges -f /tmp/sales-crm-demo-schema.sql"
        )

    tiers_to_build = list(TIERS.keys()) if args.tier == "all" else [args.tier]
    for tier in tiers_to_build:
        sizes = TIERS[tier]
        build_tier(tier, sizes["won"], sizes["lost"], schema_sql)


if __name__ == "__main__":
    main()
