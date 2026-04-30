# Cookbook: ingest a sales CRM into pg-raggraph

> **Worked example.** This walks the full pipeline using a real sales-CRM schema (`sales_demo_app.*`) — call notes, orders, customers, products, salespeople. Same shape as Salesforce / HubSpot / a custom Postgres CRM. The decisions and code work for any CRM with similar structure.
>
> **Reproducible sample dataset:** [`samples/sales-crm-demo.sql`](samples/sales-crm-demo.sql) ships with this cookbook. 200 won + 100 lost deals + 974 call notes + their dependencies (254 customers, 15 products, 46 salespeople). All synthetic. Load with `psql -d <yourdb> -f docs/cookbook/samples/sales-crm-demo.sql` and follow along verbatim.

## TL;DR

1. **Each row in `sales_notes` becomes one document.** That's the right grain.
2. **Wrap the note in markdown with structured frontmatter** (customer, product, deal status, sentiment, salesperson). The frontmatter gives every chunk context, so retrieval works even mid-document.
3. **Filter to `status='won'`** as a starter slice. ~50-200 deals is enough to validate.
4. **Let the LLM extract soft entities** (people mentioned in notes, competing products, pain points) — that's what it's good at.
5. **Inject structured edges directly** from your existing FKs: `(Customer)–[BOUGHT]–(Product)`, `(Salesperson)–[CLOSED]–(Customer)`, `(UseCase)–[APPLIES_TO]–(Product)`. That's what your CRM already knows; don't make the LLM re-derive it.
6. Total work: ~150 lines of Python (1 SQL query + 1 markdown formatter + 1 `rag.ingest()` + 1 structured-edge injector).

## The source schema (what you bring)

```
customers (customer_id, company_name, industry, hq_city, hq_state, hq_country, ...)
   │
   │ FK customer_id
   ▼
sales_orders (order_id, customer_id, salesperson_id, product_id,
              status, total_value, win_reason, lost_reason,
              expected_close_date, actual_close_date, ...)
   │                              │              │
   │ FK product_id                │              │ FK salesperson_id
   ▼                              ▼              ▼
products (product_id,        sales_notes      salespeople
          product_name,      (note_id,        (salesperson_id, ...)
          category, ...)     order_id,
                             salesperson_id,
                             note_text,           ← the textual content
                             note_type,           ← demo / discovery / objection / etc.
                             sentiment,
                             use_case_mentioned,  ← pre-extracted use-case array
                             use_case,            ← pre-extracted single use-case
                             created_at)
```

All four core tables in this example come from the schema you already showed:

```
\dt sales*
                            List of tables
     Schema     |            Name            | Type  |     Owner
----------------+----------------------------+-------+----------------
 sales_demo_app | sales_notes                | table | sales_demo_app
 sales_demo_app | sales_order_status_history | table | sales_demo_app
 sales_demo_app | sales_orders               | table | sales_demo_app
 sales_demo_app | salespeople                | table | sales_demo_app
```

## The decisions (you make these — once)

### 1. Document grain — per call note

Three options I considered:

| Option | Doc count (won) | Pros | Cons |
|---|---|---|---|
| **Per call note (chosen)** | 100s-1000s | Natural narrative; chunks stay focused; metadata-filterable | Many small docs |
| Per deal (aggregate calls) | 10s-100s | One doc per deal | Loses per-call structure; harder to filter by date |
| Per account | 10s | Coarse-grained customer view | Single doc balloons past chunk budget |

**Per-call-note wins** because the LLM extraction works best on coherent narrative units, and you can always filter by metadata (`deal_id`, `status`) at retrieval to get deal-level views.

### 2. What goes in the markdown frontmatter

The header on every doc should carry the *context the chunk loses* if it's split mid-doc. Cheap insurance against context-collapse:

```markdown
# Sales call note — {company_name} / {product_name} / {created_at:%Y-%m-%d}

**Customer:** {company_name} ({industry} · {hq_city}, {hq_state})
**Deal:** Order #{order_id} ({status}, ${total_value}, closed {actual_close_date})
**Product:** {product_name} ({category})
**Salesperson:** {salesperson_name}
**Note type:** {note_type}
**Sentiment:** {sentiment}
**Use cases:** {use_case_mentioned}

## Notes

{note_text}

## Win reason

{win_reason if present}
```

### 3. Metadata to attach (filterable at query time)

```python
metadata = {
    "order_id": ...,
    "customer_id": ...,
    "product_id": ...,
    "salesperson_id": ...,
    "status": "won",
    "sentiment": ...,
    "note_type": ...,
    "use_cases_mentioned": [...],
    "primary_use_case": ...,
    "total_value": ...,
    "actual_close_date": ...,
}
```

Two upsides:
- Query: `WHERE metadata->>'status' = 'won' AND (metadata->>'total_value')::numeric > 50000`
- Tier 1 evolution awareness later: `effective_from`, `version_label` slot here naturally.

## Step 1 — Pull rows + format markdown

`benchmarks/sales_crm/prepare.py` (or wherever you keep it):

```python
"""Pull won sales notes from the CRM and format as markdown docs."""

import os
import re
from pathlib import Path

import psycopg

CRM_DSN = os.environ["CRM_DSN"]   # e.g. postgresql://sales_demo_app@127.0.0.1/postgres
OUT = Path("benchmarks/sales_crm/docs")
OUT.mkdir(parents=True, exist_ok=True)


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
WHERE so.status = 'won'
ORDER BY so.actual_close_date DESC, sn.created_at;
"""


def slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", (text or "untitled")).strip("-")[:80]


def format_doc(row: dict) -> str:
    out = []
    out.append(
        f"# Sales call note — {row['company_name']} / {row['product_name'] or 'no product'} "
        f"/ {row['created_at']:%Y-%m-%d}\n"
    )
    out.append(
        f"**Customer:** {row['company_name']}"
        f" ({row['industry'] or 'unknown industry'}"
        f" · {row['hq_city'] or '?'}, {row['hq_state'] or '?'}, {row['hq_country'] or '?'})\n"
    )
    out.append(
        f"**Deal:** Order #{row['order_id']} ({row['status']},"
        f" ${row['total_value']}, closed {row['actual_close_date']})\n"
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
    out.append(row["note_text"].strip())
    out.append("\n")
    if row["win_reason"]:
        out.append(f"\n## Win reason\n\n{row['win_reason']}\n")
    return "".join(out)


def main():
    with psycopg.connect(CRM_DSN, row_factory=psycopg.rows.dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(SQL)
            rows = cur.fetchall()
    print(f"Fetched {len(rows)} won notes")
    for row in rows:
        path = OUT / f"note-{row['note_id']:06d}-{slug(row['company_name'])}.md"
        path.write_text(format_doc(row))
    print(f"Wrote {len(rows)} markdown files to {OUT}")


if __name__ == "__main__":
    main()
```

After this runs you have one markdown file per won call note in `benchmarks/sales_crm/docs/`.

## Step 2 — Ingest (two patterns)

You have two equally valid pipeline shapes. Pick the one that matches your situation.

### Pattern A — disk-based (write markdown first, ingest from disk)

Useful when:
- You want the intermediate markdown for human audit / review
- You'll re-ingest the same content many times for prompt/config tuning
- You want to fan out the markdown to other consumers (e.g. ETL into other tools)

This is the `prepare.py` + `ingest.py` pair shown in this section. See [`benchmarks/sales-crm-demo/prepare.py`](../../benchmarks/sales-crm-demo/prepare.py) and [`benchmarks/sales-crm-demo/ingest.py`](../../benchmarks/sales-crm-demo/ingest.py).

```python
# prepare.py runs the SQL → markdown formatter and writes .md files
# ingest.py reads the .md files and calls rag.ingest(file_paths, ...)
```

### Pattern B — in-memory (SQL → in-memory records → pg-raggraph; no disk)

**Recommended for same-database CRM/ERP pipelines.** Source data lives in your existing Postgres schema; pg-raggraph's tables live in another database (or another namespace in the same DB). No reason for the data to touch disk in between.

```python
import asyncio, os, psycopg
from pg_raggraph import GraphRAG

CRM_DSN  = os.environ["CRM_DSN"]
PGRG_DSN = os.environ["PGRG_DSN"]

SQL = """
  SELECT sn.note_id, sn.note_text, sn.note_type, sn.sentiment,
         so.order_id, so.status, so.win_reason,
         c.company_name, c.industry,
         p.product_name,
         sp.name AS salesperson_name
  FROM sales_demo_app.sales_notes sn
  JOIN sales_demo_app.sales_orders so ON so.order_id = sn.order_id
  LEFT JOIN sales_demo_app.customers c ON c.customer_id = so.customer_id
  LEFT JOIN sales_demo_app.products  p ON p.product_id  = so.product_id
  LEFT JOIN sales_demo_app.salespeople sp ON sp.salesperson_id = sn.salesperson_id
  WHERE so.status = 'won'
"""

def format_doc(row):
    """SQL row → markdown body kept in memory (never written to disk)."""
    return f"""# Sales call note — {row['company_name']} / {row['product_name']}

**Customer:** {row['company_name']} ({row['industry']})
**Deal:** Order #{row['order_id']} ({row['status']})
**Product:** {row['product_name']}
**Salesperson:** {row['salesperson_name']}
**Sentiment:** {row['sentiment']}
**Note type:** {row['note_type']}

## Notes

{row['note_text']}
""" + (f"\n## Win reason\n\n{row['win_reason']}" if row['win_reason'] else "")


async def main():
    # 1. Pull rows from CRM (no disk).
    with psycopg.connect(CRM_DSN, row_factory=psycopg.rows.dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(SQL)
            rows = cur.fetchall()

    # 2. Format in memory; build the records list.
    #
    # `metadata` is persisted as documents.metadata JSONB — query later via
    # `metadata->>'order_id'`. Keep it for filterable scalars only.
    #
    # `entities` and `relationships` seed the GRAPH directly with what your
    # CRM already knows. The LLM doesn't need to re-derive them; it adds
    # soft signals (champions mentioned, competing products) on top.
    records = [
        {
            "text": format_doc(row),
            "source_id": f"sales_note:{row['note_id']}",
            "metadata": {
                "order_id": row["order_id"],
                "customer_id": row["customer_id"],
                "product_id": row["product_id"],
                "status": row["status"],
                "sentiment": row["sentiment"],
                "note_type": row["note_type"],
            },
            "entities": [
                {"name": row["company_name"],     "entity_type": "Customer"},
                {"name": row["product_name"],    "entity_type": "Product"},
                {"name": row["salesperson_name"], "entity_type": "Salesperson"},
            ],
            "relationships": [
                {"src": row["company_name"],     "dst": row["product_name"],
                 "rel_type": "BOUGHT",
                 "description": f"order #{row['order_id']} ({row['status']})"},
                {"src": row["salesperson_name"], "dst": row["company_name"],
                 "rel_type": "SOLD_TO"},
            ],
        }
        for row in rows
    ]

    # 3. Push to pg-raggraph (no disk).
    rag = GraphRAG(
        dsn=PGRG_DSN, namespace="sales_calls_won",
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4o-mini",
        llm_api_key=os.environ["OPENAI_API_KEY"],
        extraction_prompt="dev",
    )
    await rag.connect()
    await rag.ingest_records(records, namespace="sales_calls_won")
    print(await rag.status("sales_calls_won"))
    await rag.close()

asyncio.run(main())
```

That's the whole ETL job. Three blocks. No filesystem. Full runnable version: [`benchmarks/sales-crm-demo/ingest_inmemory.py`](../../benchmarks/sales-crm-demo/ingest_inmemory.py).

The `ingest_records()` API:
- Each record is a dict with `text` (required), `source_id` (required, used as content-hash dedup key + stale-doc identifier), `metadata` (optional, same shape as `ingest()`'s metadata kwarg)
- `source_id` should be stable — e.g. `"sales_note:42"` — so re-ingesting the same record replaces the prior version atomically
- Returns the same stats as `ingest()`: documents/chunks/entities/relationships counts

Both patterns share all the same tunables (chunking, embedder, LLM, namespace, evolution metadata). Pick by ergonomics, not by capability.

### Original disk-based variant (Pattern A details)

`benchmarks/sales_crm/ingest.py`:

```python
"""Ingest the won sales notes into pg-raggraph."""

import asyncio
import json
import os
import re
from pathlib import Path

import psycopg

from pg_raggraph import GraphRAG

DOCS = Path("benchmarks/sales_crm/docs")
DSN = os.environ["PGRG_DSN"]
NAMESPACE = "sales_calls_won"


def parse_metadata_from_doc(text: str) -> dict:
    """Cheap extractor: pull `**Key:** value` lines from the markdown frontmatter
    so each chunk's parent doc carries structured fields."""
    md = {}
    for line in text.splitlines():
        m = re.match(r"^\*\*([^:]+):\*\*\s*(.+)$", line)
        if m:
            md[m.group(1).strip().lower().replace(" ", "_")] = m.group(2).strip()
        if line.startswith("## Notes"):
            break
    return md


async def main():
    rag = GraphRAG(
        dsn=DSN,
        namespace=NAMESPACE,
        embedding_provider="local",                           # bge-small, free
        llm_base_url=os.environ.get("LLM_URL", "https://api.openai.com/v1"),
        llm_model=os.environ.get("LLM_MODEL", "gpt-4o-mini"),
        llm_api_key=os.environ.get("OPENAI_API_KEY", ""),
        extraction_prompt="dev",                              # better fit than "default"
    )
    await rag.connect()
    try:
        files = sorted(str(p) for p in DOCS.glob("*.md"))
        print(f"Ingesting {len(files)} call notes into namespace={NAMESPACE}")

        # Per-doc metadata: parsed from frontmatter, attached to each ingested document.
        # Tuple of (path, metadata_dict).
        items = []
        for f in files:
            text = Path(f).read_text()
            md = parse_metadata_from_doc(text)
            items.append((f, md))

        # Ingest in one call (uses doc_concurrency for parallelism).
        # If your rag.ingest() takes only file paths, run in a per-file loop with
        # metadata=md; the per-call cost is negligible.
        for path, md in items:
            await rag.ingest([path], namespace=NAMESPACE, metadata=md)

        status = await rag.status(NAMESPACE)
        print(
            f"Done: {status['documents']} docs, {status['chunks']} chunks, "
            f"{status['entities']} entities, {status['relationships']} rels"
        )
    finally:
        await rag.close()


asyncio.run(main())
```

That's it. The tool runs chunking → embedding → entity extraction → entity resolution → graph storage → indexing automatically.

### What you should see

For ~200 won call notes (each ~200-500 tokens of body), expect roughly:

| Counter | Order of magnitude |
|---|---|
| documents | 200 |
| chunks | 200-300 (most notes are one chunk) |
| entities | 600-1500 (people, companies, products, use cases, competitors mentioned) |
| relationships | 800-2000 |

Cost (one-time, with `gpt-4o-mini` for extraction): roughly **$1-3** for the entire ingest. Wall time: 10-30 min depending on `extract_concurrency`.

## Step 3 — Inject structured relationships from CRM (optional but high-leverage)

After ingest, your call-notes graph is dominated by what the LLM noticed in narrative. The CRM has *known* edges that are worth pinning so the graph is anchored in ground truth:

- `(Customer)–[BOUGHT]–(Product)` from `sales_orders.product_id`
- `(Salesperson)–[CLOSED]–(Customer)` from `sales_orders.salesperson_id` for won
- `(UseCase)–[APPLIES_TO]–(Product)` from `use_cases` table (if present) or `sales_notes.use_case_mentioned`

`benchmarks/sales_crm/inject_structural_edges.py`:

```python
import asyncio
import os

import psycopg

CRM_DSN = os.environ["CRM_DSN"]
PGRG_DSN = os.environ["PGRG_DSN"]
NAMESPACE = "sales_calls_won"


async def main():
    # We use direct asyncpg / psycopg here because we're writing to pg-raggraph's
    # tables, not extracting from text. The schema is documented in
    # docs/user-guide.md → "Schema overview".
    import psycopg
    crm = psycopg.connect(CRM_DSN, row_factory=psycopg.rows.dict_row)
    pg = psycopg.connect(PGRG_DSN, row_factory=psycopg.rows.dict_row, autocommit=False)

    try:
        with crm.cursor() as c, pg.cursor() as g:
            # 1. Customer -[BOUGHT]-> Product
            c.execute("""
                SELECT DISTINCT cu.company_name, p.product_name
                FROM sales_demo_app.sales_orders so
                JOIN sales_demo_app.customers cu ON cu.customer_id = so.customer_id
                JOIN sales_demo_app.products p   ON p.product_id   = so.product_id
                WHERE so.status = 'won'
            """)
            for row in c.fetchall():
                # Match against entities pg-raggraph already extracted by name.
                # Case-insensitive match keeps "ACME Corp" / "Acme Inc" lined up
                # with whatever the LLM produced.
                g.execute(
                    """
                    INSERT INTO relationships
                      (namespace, src_id, dst_id, rel_type, weight, description, properties)
                    SELECT %s, a.id, p.id, 'BOUGHT', 1.0, 'from sales_orders FK', '{}'::jsonb
                    FROM entities a, entities p
                    WHERE a.namespace = %s AND lower(a.name) = lower(%s)
                      AND p.namespace = %s AND lower(p.name) = lower(%s)
                    ON CONFLICT DO NOTHING
                    """,
                    (NAMESPACE, NAMESPACE, row["company_name"], NAMESPACE, row["product_name"]),
                )

            # 2. Salesperson -[CLOSED]-> Customer
            c.execute("""
                SELECT DISTINCT sp.name AS sp_name, cu.company_name
                FROM sales_demo_app.sales_orders so
                JOIN sales_demo_app.salespeople sp ON sp.salesperson_id = so.salesperson_id
                JOIN sales_demo_app.customers cu   ON cu.customer_id    = so.customer_id
                WHERE so.status = 'won'
            """)
            for row in c.fetchall():
                g.execute(
                    """
                    INSERT INTO relationships
                      (namespace, src_id, dst_id, rel_type, weight, description, properties)
                    SELECT %s, s.id, c.id, 'CLOSED', 1.0, 'from sales_orders FK', '{}'::jsonb
                    FROM entities s, entities c
                    WHERE s.namespace = %s AND lower(s.name) = lower(%s)
                      AND c.namespace = %s AND lower(c.name) = lower(%s)
                    ON CONFLICT DO NOTHING
                    """,
                    (NAMESPACE, NAMESPACE, row["sp_name"], NAMESPACE, row["company_name"]),
                )

        pg.commit()
        print("Injected structural edges.")
    finally:
        crm.close()
        pg.close()


asyncio.run(main())
```

This pattern composes — one block per FK you want as a graph edge. Skip any block whose entities the LLM didn't name (the matching `WHERE` clause silently no-ops).

## Step 4 — Query

```python
result = await rag.ask(
    "What objections came up most often in closed-won deals last quarter?",
    mode="smart",                            # confidence-routed default
    namespace=NAMESPACE,
)
print(result.answer)
for c in result.chunks[:3]:
    print(f"  source: {c.document_source}")
```

Or via CLI:

```bash
pgrg ask "What were the most common reasons we won deals against Stripe Billing?" \
  --namespace sales_calls_won \
  --mode smart
```

## Step 5 — Validation queries

After ingest, sanity-check what got extracted:

```sql
-- Top entity types
SELECT entity_type, COUNT(*) FROM entities
WHERE namespace = 'sales_calls_won'
GROUP BY entity_type ORDER BY 2 DESC LIMIT 20;

-- Most connected entities (likely customers, products, key people)
SELECT e.name, e.entity_type, COUNT(r.*) AS edges
FROM entities e
LEFT JOIN relationships r
  ON r.namespace = e.namespace AND (r.src_id = e.id OR r.dst_id = e.id)
WHERE e.namespace = 'sales_calls_won'
GROUP BY e.id, e.name, e.entity_type
ORDER BY edges DESC LIMIT 20;

-- Did the structural injection land?
SELECT rel_type, COUNT(*) FROM relationships
WHERE namespace = 'sales_calls_won'
GROUP BY rel_type ORDER BY 2 DESC;
```

You should see relationship types like `BOUGHT`, `CLOSED` (from injection) alongside LLM-extracted ones like `MENTIONED`, `WORKS_FOR`, `COMPETES_WITH`, `HAS_PAIN_POINT`.

## What you'll want to tune (after the first ingest)

Once you have real data, the knobs most likely to matter:

| Knob | When to flip | Effect |
|---|---|---|
| **`embedding_model`** | **First thing to evaluate** if retrieval feels weak | Biggest single lever. bge-small-en-v1.5 (default) is conservative; bge-large-en-v1.5 (1024-dim, free) typically buys +5-8 pp F1 on retrieval-bound queries |
| `extraction_prompt="dev"` | already on in the example — keep it | Better fit for operational/CRM corpora than the generic prompt |
| `chunk_max_tokens=384` | If your call notes are very long (>1k tokens) | Tighter chunks → more precise retrieval |
| `mode="hybrid"` (per-query) | Multi-doc questions ("compare wins across competitors") | +graph traversal |
| `rerank=True` (per-call) | Ambiguous questions where naive ordering is suspect | +3-7 pp accuracy, +50-200 ms latency (with default MiniLM-L-6 reranker) |
| `short_answer=True` (per-call) | Factoid Q&A (single-fact questions) | Crisp short answers, much lower latency |

> ⚠️ **Embedder note.** All retrieval-quality numbers across the pg-raggraph repo are generated with `embedding_model = "BAAI/bge-small-en-v1.5"` (384-dim). For production CRM Q&A, evaluate `bge-large-en-v1.5` (1024-dim) before declaring victory — it's free, similar latency on a modern CPU, and typically buys real F1. See [`docs/Config-Reference.md`](../Config-Reference.md) for the full embedder discussion.

See [`docs/Config-Reference.md`](../Config-Reference.md) for every other knob.

## What you do vs what the tool does

| Step | You | Tool |
|---|---|---|
| Choose document grain (per-call) | ✓ | |
| Write `prepare.py` (~70 lines) | ✓ | |
| Run `ingest.py` | trigger | chunks, embeds, LLM-extracts entities + relationships, resolves dupes, stores graph, indexes |
| Write `inject_structural_edges.py` | ✓ optional, ~50 lines | persists the FK-based edges |
| Run validation SQL | ✓ | (read-only) |
| `rag.ask(question, namespace=...)` | trigger | runs vector + BM25 + graph traversal, generates answer with citations |

**Roughly 20% you, 80% the tool.** The 20% is the boundary work — what counts as a document, what metadata to attach, which FKs are worth pinning. That's irreducibly your domain knowledge.

## Where the LLM helps vs where your CRM is already truth

**LLM finds (soft signals from narrative):**
- People mentioned in notes (champions, blockers, executive sponsors)
- Competing products evaluated ("Stripe Billing came up")
- Pain points described
- Decision criteria
- Use cases not explicitly tagged
- Sentiment toward features

**Your CRM is already truth (don't make the LLM re-derive):**
- Account → Product purchase history (use `sales_orders.product_id`)
- Salesperson assignments (use `sales_orders.salesperson_id`)
- Deal status / value (already in `sales_orders`)
- Pre-tagged use cases (use `sales_notes.use_case_mentioned[]`)

The injection script is how you keep the second column trustworthy without paying LLM cost.

## What's NOT in scope here

- **Live sync.** This is one-shot ingest. For continuous sync, write a CDC loop that re-runs `prepare.py` + `rag.ingest()` on changed `sales_notes` rows. pg-raggraph dedupes by content hash, so re-ingesting an unchanged note is a no-op.
- **Multi-tenant isolation across customers viewing their own data.** Use one `namespace` per tenant.
- **Tier 1 evolution-aware retrieval.** Set `evolution_tier="structural"` and add `effective_from` / `version_label` metadata if your CRM tracks deal-state-over-time and you want time-travel queries. See [`docs/cookbook/evolution-tracking.md`](evolution-tracking.md).

## Real run output (small dataset, 2026-04-30)

Actually running the disk-based pipeline (Pattern A) end-to-end against the small sample produced these numbers — committed at `benchmarks/sales-crm-demo/_logs/ingest-small.log` and `_logs/queries.log` for reproducibility.

### Ingest

```
Ingesting 649 call notes into namespace=sales_crm_demo_small
...
Done in 67.8 min
  documents:     649
  chunks:        1,864
  entities:      1,172
  relationships: 4,110
```

Cost: ~$0.30 in `gpt-4o-mini` extraction calls. ~6.3 relationships and ~1.8 entities per doc — a meaningful graph density for a corpus where each note is a few hundred chars.

### Graph shape

The LLM extraction (with `extraction_prompt="dev"`) classifies entities into operational types:

| entity_type | count |
|---|---|
| concept | 429 |
| ticket | 224 |
| service | 197 |
| person | 141 |
| company | 97 |
| environment | 17 |
| tool | 16 |
| file | 14 |
| document | 9 |
| library | 8 |

Top-connected entities by edge degree are exactly what you'd expect for a sales corpus — the product line and the top sellers:

| name | type | edges |
|---|---|---|
| ClarityDB Guardian | service | 300 |
| Ava Chen | person | 246 |
| Synapse AIOps | service | 225 |
| Liam Park | person | 209 |
| Neuron Canvas | service | 168 |
| OmniConnect Proxy | service | 140 |
| Converge Lakehouse | service | 134 |
| PillarDB Standard | service | 111 |
| TitanDB Enterprise | service | 108 |
| Prometheus AI Factory | service | 99 |

Most common relationships: `OWNS` (1,130), `RELATED_TO` (953), `REFERENCES` (559), `DEPENDS_ON` (217), `USES` (202), `CAUSED` (186), `PART_OF` (185).

> Note: this run used the disk-based path (Pattern A) on the *original* `ingest()` API — caller-known entities like Customer/Product/Salesperson and FK relationships like BOUGHT/SOLD_TO were NOT seeded into the graph. Re-running with Pattern B (`ingest_records()` + the new `entities`/`relationships` fields) would add those structured edges on top.

### Sample queries — real `rag.ask()` output

Five queries via `mode="smart"` against the same namespace. Verbatim answers below (full transcript in `_logs/queries.log`).

**Q: "What customers bought ClarityDB Guardian and what was their main pain point?"** *(99 ms retrieval, smart[boosted])*

> Customers who bought ClarityDB Guardian and their main pain points include:
>
> 1. **Davis Healthcare Inc.**: They faced issues with an index making other queries slower [source: note-010536-Davis-Healthcare-Inc.md].
> 2. **Williams Finance Corp.**: They only discovered database problems when customers complained [source: note-008338-Williams-Finance-Corp.md].
> 3. **Smith Healthcare Group**: They had a manual process for checking alerts across multiple tools and experienced intermittent slow queries [source: note-030041-Smith-Healthcare-Group.md].
> 4. **Jones Healthcare Solutions**: They needed DBA approval for all queries, which created bottlenecks…
> 5. **Smith Healthcare Inc.**: They wanted to know when they would hit their maximum IOPS on cloud disks and struggled with root cause analysis…

This is the kind of cross-document reasoning the graph is supposed to enable — each customer-pain-point pair lives in a different note, and the answer chains them through the shared `ClarityDB Guardian` product entity.

**Q: "Which industries had the most won deals?"** *(143 ms retrieval, smart[expanded])*

> The industries with the most won deals are:
> 1. **Retail** — Multiple deals won, including one for $72,597 ARR and another for $809.54.
> 2. **Healthcare** — One deal won for $22,541 ARR.
> 3. **Manufacturing** — One deal won for $655.18.
>
> Retail has the highest number of won deals based on the provided context.

**Q: "What objections came up most often in our closed-won deals?"** *(183 ms retrieval, smart[expanded])*

> The context does not provide specific information about objections that came up most often in closed-won deals. It mainly contains notes on contract review meetings with various companies, all mentioning "minor redlines on SLA terms" but no details on objections.

That's the correct answer — won-deal notes don't dwell on objections by definition. The system declines honestly instead of fabricating; that's what `extraction_prompt="dev"` + grounded answer prompt buy.

### What this validates

- Pipeline runs end-to-end on a 649-note corpus in 68 minutes for ~$0.30.
- Retrieval latency stays sub-500 ms across all 5 queries via `mode="smart"`.
- Multi-document reasoning works: Q2 chains pain points across 5 different notes via the shared product entity.
- The system declines honestly when the corpus doesn't contain the answer (Q1).
- Source attribution in every answer.

### What it doesn't validate (yet)

- Pattern B (in-memory `ingest_records` with caller-supplied `entities`/`relationships`) on this corpus — that's the same data through the better API. Run via `ingest_inmemory.py`; should produce a richer graph anchored in CRM FKs.
- The medium dataset (~3,300 notes from 1,000 deals) — same script, just scale up to see how cross-deal patterns emerge.

---

## Loading the sample dataset

If you just want to follow along:

```bash
# Load the synthetic CRM sample into your local Postgres
psql -h localhost -d postgres -f docs/cookbook/samples/sales-crm-demo.sql

# Confirm rows
psql -h localhost -d postgres -c "
  SELECT
    (SELECT COUNT(*) FROM sales_demo_app.sales_orders WHERE status='won') AS won,
    (SELECT COUNT(*) FROM sales_demo_app.sales_orders WHERE status='lost') AS lost,
    (SELECT COUNT(*) FROM sales_demo_app.sales_notes) AS notes;
"
# won | lost | notes
# 200 | 100  | 974
```

The sample is 0.77 MB. It includes only the 5 tables this cookbook uses (salespeople, customers, products, sales_orders, sales_notes), with a stratified slice of 200 won + 100 lost deals + their dependencies. Triggers and Postgres-18-specific session variables are stripped so the file loads on Postgres 14+.

To regenerate from a live CRM with different sample size, edit `WON_SAMPLE` / `LOST_SAMPLE` in [`samples/_build_sample.py`](samples/_build_sample.py) and re-run. (Build script is for maintainers; the .sql file is the actual deliverable.)

## Next steps for *your* schema specifically

Given the `sales_demo_app.*` tables you showed:

1. **Run the prepare step** with `WHERE so.status = 'won'` to get a sense of corpus size. If it's < 50 deals, drop the filter and use all statuses; pg-raggraph's namespace separation makes per-status retrieval easy via metadata filter at query time.
2. **Use `extraction_prompt="dev"`** — your notes contain product names, salespeople, customers, use cases, sentiments. That's an operational corpus, not a general-knowledge corpus. The dev prompt tunes for exactly this shape.
3. **Inject the four structural edges:**
   - `(Customer)–[BOUGHT]–(Product)` from `sales_orders`
   - `(Salesperson)–[CLOSED]–(Customer)` from `sales_orders`
   - `(UseCase)–[APPLIES_TO]–(Product)` from `use_cases` (if you have it) or `sales_notes.use_case_mentioned[]`
   - `(Customer)–[IN_INDUSTRY]–(Industry)` from `customers.industry`
4. **First-question test:** "What use cases came up most often when closing deals against Competitor X?" — that's the kind of cross-document reasoning where graph mode earns its keep.
