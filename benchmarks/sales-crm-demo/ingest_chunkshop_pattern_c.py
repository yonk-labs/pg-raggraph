"""Bridge: chunkshop's pgvector output → pg-raggraph (Pattern C).

The full chunkshop pipeline (chunker + embedder + optional metadata
extractor) populates its own table; this script reads that table and
feeds pg-raggraph via ``ingest_records(pre_chunked=...)`` so the
chunks/embeddings pass through *without* redundant re-embedding.

Pre-requisite: run chunkshop first.

    chunkshop ingest --config docs/cookbook/samples/chunkshop-crm-pattern-c.yaml

What this script does:
  1. Read chunkshop_demo.sales_crm_chunks grouped by doc_id.
  2. For each doc, parse the markdown frontmatter (written by
     prepare.py) to recover the structured fields — customer name,
     product, salesperson, sentiment, FK ids — that the LLM doesn't
     need to re-derive.
  3. Build pg-raggraph records: text (reconstructed for LLM extraction),
     source_id, metadata, caller-known entities + relationships, AND
     pre_chunked (chunkshop's chunks + embeddings) so pg-raggraph
     skips its own chunker + embedder.
  4. Call rag.ingest_records().

Net result: chunkshop owns chunking + embedding; pg-raggraph owns the
entity-relationship graph + retrieval modes. Each tool does what it's
best at; no work duplicated.
"""

from __future__ import annotations

import asyncio
import os
import re
from collections import defaultdict

import psycopg

from pg_raggraph import GraphRAG

PGRG_DSN = os.environ.get(
    "PGRG_DSN", "postgresql://postgres:postgres@localhost:5434/pg_raggraph"
)
NAMESPACE = os.environ.get("PGRG_NAMESPACE", "sales_crm_pattern_c")
CHUNKSHOP_TABLE = os.environ.get(
    "CHUNKSHOP_TABLE", "chunkshop_demo.sales_crm_chunks"
)


# ---------------------------------------------------------------------------
# Frontmatter parser. The markdown that prepare.py wrote has a stable shape:
#
#   # Sales call note — <Company> / <Product> / YYYY-MM-DD
#
#   **Customer:** Company (Industry · City, State, Country)
#   **Deal:** Order #N (status, $value, closed YYYY-MM-DD)
#   **Product:** Product (Category)
#   **Salesperson:** Name
#   **Note type:** ...
#   **Sentiment:** ...
#   **Use cases:** a, b, c
#
#   ## Notes
#   ...
#
# We pull what we need to seed the graph with caller-known structure.
# ---------------------------------------------------------------------------

_FRONTMATTER_KEYS = {
    "customer", "deal", "product", "salesperson",
    "note_type", "sentiment", "use_cases",
}


def _parse_frontmatter(text: str) -> dict:
    md = {}
    for line in text.splitlines():
        m = re.match(r"^\*\*([^:]+):\*\*\s*(.+)$", line)
        if m:
            key = m.group(1).strip().lower().replace(" ", "_")
            md[key] = m.group(2).strip()
        if line.startswith("## Notes"):
            break
    return md


_DEAL_RE = re.compile(r"^Order\s+#(\d+)\s*\((\w+)")
_CUST_RE = re.compile(r"^([^(]+)\s*\(")


def _company_from_md(md: dict) -> str | None:
    val = md.get("customer", "")
    m = _CUST_RE.match(val)
    return m.group(1).strip() if m else (val or None)


def _product_from_md(md: dict) -> str | None:
    val = md.get("product", "")
    m = _CUST_RE.match(val)
    return m.group(1).strip() if m else (val or None)


def _order_id_from_md(md: dict) -> int | None:
    val = md.get("deal", "")
    m = _DEAL_RE.match(val)
    return int(m.group(1)) if m else None


def _build_record(doc_id: str, doc_chunks: list[dict]) -> dict:
    """Merge a doc's chunkshop chunks into one ingest_records record."""
    doc_chunks = sorted(doc_chunks, key=lambda c: c["seq_num"])
    full_text = "\n\n".join(c["original_content"] for c in doc_chunks)
    md = _parse_frontmatter(full_text)

    company = _company_from_md(md)
    product = _product_from_md(md)
    salesperson = md.get("salesperson", "").strip() or None
    sentiment = md.get("sentiment", "").strip() or None
    note_type = md.get("note_type", "").strip() or None
    use_cases_str = md.get("use_cases", "").strip()
    use_cases = [u.strip() for u in use_cases_str.split(",") if u.strip()] if use_cases_str else []
    order_id = _order_id_from_md(md)

    entities = []
    if company:
        entities.append({"name": company, "entity_type": "Customer"})
    if product:
        entities.append({"name": product, "entity_type": "Product"})
    if salesperson:
        entities.append({"name": salesperson, "entity_type": "Salesperson"})
    for uc in use_cases:
        entities.append({"name": uc, "entity_type": "UseCase"})

    relationships = []
    if company and product:
        relationships.append({
            "src": company, "dst": product, "rel_type": "BOUGHT",
            "description": f"order #{order_id}" if order_id else "",
        })
    if salesperson and company:
        relationships.append({
            "src": salesperson, "dst": company, "rel_type": "SOLD_TO",
        })
    for uc in use_cases:
        if company:
            relationships.append({
                "src": company, "dst": uc, "rel_type": "HAS_USE_CASE",
            })

    pre_chunked = [
        {
            "content": c["original_content"],
            "embedded_content": c["embedded_content"] or c["original_content"],
            "embedding": list(c["embedding"]),  # pgvector → python list
            "metadata": dict(c.get("metadata") or {}),
        }
        for c in doc_chunks
    ]

    return {
        "text": full_text,
        "source_id": f"chunkshop:{doc_id}",
        "metadata": {
            "order_id": order_id,
            "company": company,
            "product": product,
            "salesperson": salesperson,
            "sentiment": sentiment,
            "note_type": note_type,
            "use_cases_mentioned": use_cases,
            "chunkshop_doc_id": doc_id,
        },
        "entities": entities,
        "relationships": relationships,
        "pre_chunked": pre_chunked,
    }


async def main() -> None:
    print(f"Reading chunkshop table: {CHUNKSHOP_TABLE}")
    print(f"pg-raggraph target: namespace={NAMESPACE}")

    # Pull chunkshop's chunks. Embedding column comes back as pgvector;
    # psycopg materializes it as list[float] via pgvector.psycopg.
    sql = f"""
        SELECT doc_id, seq_num, original_content, embedded_content,
               metadata, embedding::float4[]::float4[] AS embedding
        FROM {CHUNKSHOP_TABLE}
        ORDER BY doc_id, seq_num
    """
    rows: list[dict] = []
    with psycopg.connect(PGRG_DSN, row_factory=psycopg.rows.dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchall()
    print(f"Loaded {len(rows)} chunkshop chunks")

    by_doc: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_doc[r["doc_id"]].append(r)
    print(f"Grouped into {len(by_doc)} documents")

    records = [_build_record(doc_id, chunks) for doc_id, chunks in by_doc.items()]

    rag = GraphRAG(
        dsn=PGRG_DSN,
        namespace=NAMESPACE,
        embedding_provider="local",
        embedding_dim=384,                      # MUST match chunkshop's embedder
        # chunk_strategy is irrelevant when pre_chunked is set per record.
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
