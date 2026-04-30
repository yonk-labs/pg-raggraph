# Proposal: declarative ingest configuration

> **Status:** Forward-looking draft (2026-04-30). Captured from a user ask: *"should we be allowing users to define the relationships they want/need up front? like configure it in yaml? also less code to write the better for users."* Not committed for execution.

## TL;DR

The CRM cookbook example is ~50 lines of mostly-boilerplate Python: SQL → format_doc → row_to_record → ingest_records. Most of that is mechanical mapping that should be one config file. Three options to evaluate, ranked by user-friction:

1. **YAML config + `pgrg ingest --config foo.yaml`** — most declarative, language-agnostic, runnable from cron/CI without writing Python. ~5 lines instead of 50 for the user.
2. **Python builder (`SQLSourceIngest`)** — type-hinted, IDE-autocomplete, importable. ~10 lines. Doesn't need a YAML parser or template engine.
3. **Both — YAML parses to the Python builder** — best of both worlds. The builder is the runtime; the YAML is a thin frontend.

Recommended: **build option 2 first** (it's the runtime the YAML would compile to), **then layer option 1 on top**.

## What "less code to write" looks like

### Today (the cookbook example, ~50 lines)

```python
import asyncio, os, psycopg
from pg_raggraph import GraphRAG

CRM_DSN  = os.environ["CRM_DSN"]
PGRG_DSN = os.environ["PGRG_DSN"]

SQL = """SELECT sn.note_id, sn.note_text, sn.note_type, sn.sentiment,
                so.order_id, so.status, so.win_reason,
                c.company_name, c.industry, p.product_name,
                sp.name AS salesperson_name
         FROM sales_demo_app.sales_notes sn
         JOIN sales_demo_app.sales_orders so ON so.order_id = sn.order_id
         LEFT JOIN sales_demo_app.customers c ON c.customer_id = so.customer_id
         LEFT JOIN sales_demo_app.products p  ON p.product_id  = so.product_id
         LEFT JOIN sales_demo_app.salespeople sp ON sp.salesperson_id = sn.salesperson_id
         WHERE so.status = 'won'"""

def format_doc(row): ...   # 15 lines of f-strings
def row_to_record(row): return {
    "text": format_doc(row),
    "source_id": f"sales_note:{row['note_id']}",
    "metadata": {"order_id": row["order_id"], ...},   # 10 keys
    "entities": [...],      # 3-4 entity dicts
    "relationships": [...], # 2-3 rel dicts
}

async def main():
    with psycopg.connect(CRM_DSN) as conn:
        rows = conn.execute(SQL).fetchall()
    records = [row_to_record(r) for r in rows]
    rag = GraphRAG(dsn=PGRG_DSN, namespace="sales_calls", ...)
    await rag.connect()
    await rag.ingest_records(records, namespace="sales_calls")
    await rag.close()

asyncio.run(main())
```

### Option 1 — YAML

```yaml
# crm-ingest.yaml
namespace: sales_calls
source:
  dsn: ${CRM_DSN}
  query: |
    SELECT sn.note_id, sn.note_text, sn.note_type, sn.sentiment,
           so.order_id, so.status, so.win_reason,
           c.company_name, c.industry, p.product_name,
           sp.name AS salesperson_name
    FROM sales_demo_app.sales_notes sn
    JOIN sales_demo_app.sales_orders so ON so.order_id = sn.order_id
    LEFT JOIN sales_demo_app.customers c ON c.customer_id = so.customer_id
    LEFT JOIN sales_demo_app.products p  ON p.product_id  = so.product_id
    LEFT JOIN sales_demo_app.salespeople sp ON sp.salesperson_id = sn.salesperson_id
    WHERE so.status = 'won'

source_id: "sales_note:{{ note_id }}"

text: |
  # Sales call note — {{ company_name }} / {{ product_name }}

  **Customer:** {{ company_name }} ({{ industry }})
  **Deal:** Order #{{ order_id }} ({{ status }})
  **Salesperson:** {{ salesperson_name }}

  ## Notes

  {{ note_text }}

metadata:
  order_id:    "{{ order_id }}"
  status:      "{{ status }}"
  sentiment:   "{{ sentiment }}"
  note_type:   "{{ note_type }}"

entities:
  - name: "{{ company_name }}"
    entity_type: Customer
    description: "{{ industry }}"
  - name: "{{ product_name }}"
    entity_type: Product
  - name: "{{ salesperson_name }}"
    entity_type: Salesperson

relationships:
  - {src: "{{ company_name }}",     dst: "{{ product_name }}",  rel_type: BOUGHT}
  - {src: "{{ salesperson_name }}", dst: "{{ company_name }}",  rel_type: SOLD_TO}

ingest:
  llm_model: gpt-4o-mini
  extraction_prompt: dev
```

```bash
pgrg ingest --config crm-ingest.yaml
```

That's it. One file, one CLI command. No Python.

### Option 2 — Python builder

```python
from pg_raggraph.declarative import SQLSourceIngest

ingest = SQLSourceIngest(
    crm_dsn=os.environ["CRM_DSN"],
    pgrg_dsn=os.environ["PGRG_DSN"],
    namespace="sales_calls",
    query="SELECT ... FROM sales_demo_app.sales_notes sn JOIN ...",
    source_id="sales_note:{note_id}",
    text_template="""
        # Sales call note — {company_name} / {product_name}
        ...
        ## Notes
        {note_text}
    """,
    metadata_keys=["order_id", "status", "sentiment", "note_type"],
    entities=[
        {"name": "{company_name}",     "entity_type": "Customer"},
        {"name": "{product_name}",    "entity_type": "Product"},
        {"name": "{salesperson_name}", "entity_type": "Salesperson"},
    ],
    relationships=[
        {"src": "{company_name}",     "dst": "{product_name}",
         "rel_type": "BOUGHT"},
        {"src": "{salesperson_name}", "dst": "{company_name}",
         "rel_type": "SOLD_TO"},
    ],
    llm_model="gpt-4o-mini",
    extraction_prompt="dev",
)
await ingest.run()
```

Same shape, type-hinted, no new file format.

### Comparison

| Dimension | YAML config | Python builder | Today (raw `ingest_records`) |
|---|---|---|---|
| Lines of code (or config) | ~25 | ~25 | ~50-70 |
| Cron / CI runnable | direct (one CLI cmd) | Python wrapper | Python wrapper |
| Type checking | runtime only (after parse) | static (mypy/pyright) | static |
| IDE autocomplete | none | yes | yes |
| Multi-source / fan-out | trivial: another YAML | another builder | rewrite the loop |
| Templating engine | needed (Jinja2) | str.format | str.format |
| New surface area | YAML schema + parser + CLI | one class | none |
| Right user | data engineer, ops, non-Python | Python developer | low-level use cases |

## Implementation outline

### Phase 1 — Python builder (~1 week)

New module `src/pg_raggraph/declarative.py`:

```python
@dataclass
class SQLSourceIngest:
    crm_dsn: str
    pgrg_dsn: str
    namespace: str
    query: str
    source_id: str            # str.format template
    text_template: str        # str.format template
    metadata_keys: list[str] = field(default_factory=list)
    entities: list[dict] = field(default_factory=list)        # str.format templates
    relationships: list[dict] = field(default_factory=list)
    llm_model: str | None = None
    extraction_prompt: str = "default"
    # ... other GraphRAG kwargs

    async def run(self) -> None:
        rows = await self._fetch_rows()
        records = [self._row_to_record(r) for r in rows]
        async with self._rag() as rag:
            await rag.ingest_records(records, namespace=self.namespace)

    def _row_to_record(self, row): ...   # str.format substitution
```

Effort: ~200 lines + tests. No new dependencies.

### Phase 2 — YAML frontend (~1 week, conditional)

Only worth building if there's user demand for non-Python configurability. Adds:

- YAML schema (`pyproject.toml` plugin or custom validator)
- Jinja2 dependency (or stick with str.format for simplicity)
- `pgrg ingest --config foo.yaml` CLI command
- Compiles to a `SQLSourceIngest` instance from Phase 1

Effort: ~150 lines + Jinja2 + CLI plumbing.

## Other source kinds

The same shape generalizes:

```yaml
# Files on disk
source: {kind: glob, pattern: "./call_notes/*.md"}

# Single-table iteration with no SQL
source: {kind: table, dsn: ..., schema: ..., table: ..., where: "status='won'"}

# HTTP API
source: {kind: http, url: ..., paginate: ...}
```

Don't build all four. Start with `kind: sql` (covers 80% of database-backed users) and add others as concrete demand appears.

## Tradeoffs

**Pro: dramatic UX win for the dominant CRM/ERP/Postgres-source case.** ~50 lines of boilerplate becomes ~5-25 lines depending on builder vs YAML.

**Pro: composable.** Same builder can wrap any source — SQL today, files tomorrow, HTTP next quarter. Single mental model.

**Pro: doesn't break existing API.** `ingest_records()` stays the runtime surface. Builders are convenience on top.

**Con: more surface to maintain.** Templating engines, YAML schema, CLI commands. Each gets bug reports.

**Con: hides the underlying library.** A user who needs to debug a record's `entities` list has to mentally compile through the template. We mitigate with `--dry-run` mode that prints the generated records before ingesting.

**Con: edge cases.** SQL queries that need parameter binding, conditional entity lists ("only emit Salesperson if salesperson_id is not null"), multi-row joins where one record needs data from N rows. The simplest declarative grammar can't express these. Either limit to the common 80% case or add a `transform` Python hook for the gnarly cases — which kind of defeats the "less code" point.

## Recommendation

Build Phase 1 (Python builder) when there's a second cookbook to write. Two real CRM-style users would tell us what shape the builder needs.

**Don't pre-build YAML.** It's the same data with a different parser; defer until demand emerges from a non-Python user.

Until then, the existing `ingest_records()` API + the cookbook Pattern B example is the right teaching surface — readers learn how the records actually flow before getting handed a builder that hides them.

## What this proposal is NOT

- Not a replacement for `ingest_records()`. The builder/YAML are convenience layers; the underlying API is still the contract.
- Not advocacy for a config-file-driven product. The Python API stays the primary surface.
- Not committed for execution. Marker for "when a second user wants to do the CRM thing."
