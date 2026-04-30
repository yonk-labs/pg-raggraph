# Cookbook: pg-raggraph + chunkshop

> **TL;DR.** [`chunkshop`](https://github.com/yonk-labs/chunkshop) is a sibling library on PyPI / crates.io for ingest-shaped work — chunker → embedder → extractor → pgvector. pg-raggraph treats it as **optional but recommended** for the chunking step (and, if you want it, the metadata-extraction step). Two integration shapes:
>
> - **Pattern D — chunker-only** (recommended starting point): set `chunk_strategy="chunkshop:hierarchy"` on `GraphRAG` and pg-raggraph delegates the chunking step to chunkshop. Everything else (embedding, LLM extraction, graph layer) stays in pg-raggraph.
> - **Pattern C — full chunkshop pipeline + bridge** (advanced): run chunkshop end-to-end (chunks + embeddings + extracted metadata into chunkshop's pgvector table), then have pg-raggraph read that table and add the graph layer on top.

## Why integrate with chunkshop at all?

pg-raggraph ships with a built-in chunker (`chunk_strategy="auto"`, `"hierarchy"`). It works. chunkshop usually works *better* because:

- **More chunker strategies.** chunkshop's registry currently exposes `hierarchy`, `sentence_aware`, `semantic`, `fixed_overlap`, `neighbor_expand`, `summary_embed`, `hierarchical_summary`. We expose the first five via `chunk_strategy="chunkshop:<name>"`.
- **Tuned defaults.** chunkshop's defaults come out of its own factorial benchmarks across multiple corpora (legal, medical, code). The `hierarchy` chunker with `prefix_heading=True` and `max_chars=2000` is the production sweet spot for markdown-shaped inputs.
- **Optional metadata extractors.** chunkshop ships RAKE keywords, KeyBERT phrases, spaCy entities, and language detection as opt-in extractors. None of these are LLM-based; all are local + free. pg-raggraph doesn't have native versions of these.
- **Pre-quantized embedders** (in Pattern C). chunkshop ships int8 quantized variants of bge-small/base by default — ~2× faster ingest than fp32 with negligible accuracy loss per chunkshop's own factorial bench.

The downsides are honest:

- **One more dependency** (~50 MB of Python plus the embedder model cache).
- **Two tools to learn** if you go full Pattern C — chunkshop's YAML format on top of pg-raggraph's API.
- **The built-in chunker is genuinely fine** for many corpora. If you don't have a clear reason to switch, don't.

## Pattern D — chunker-only via `chunk_strategy="chunkshop:*"`

The 1-line integration. Pg-raggraph still owns ingest end-to-end; chunkshop just chunks.

### Install

```bash
pip install 'pg-raggraph[chunkshop]'
# or in pyproject.toml:
#   "pg-raggraph[chunkshop]>=0.3"
```

The dep is **optional** — pg-raggraph imports chunkshop lazily, only if you use a `chunkshop:*` strategy. If you don't install the extra and don't pass a chunkshop strategy, nothing changes.

### Use

```python
from pg_raggraph import GraphRAG

rag = GraphRAG(
    dsn="postgresql://localhost/mydb",
    namespace="sales_calls",
    chunk_strategy="chunkshop:hierarchy",   # ← the one line that matters
    # ...everything else as usual
)
await rag.connect()
await rag.ingest_records(records, namespace="sales_calls")
```

Supported strategies (set as `chunk_strategy="chunkshop:<name>"`):

| Strategy | What it does | When to pick |
|---|---|---|
| `chunkshop:hierarchy` | Heading-prefixed chunks. Best on markdown / structured docs. | Default recommendation — markdown, technical docs, sales call notes with frontmatter |
| `chunkshop:sentence_aware` | Sentence-respecting hard splits. | Prose corpora without strong heading structure |
| `chunkshop:semantic` | Splits on semantic boundary detection (uses MiniLM under the hood). | Long-form content where you want chunks to break at topic shifts. Note: heavier than the others. |
| `chunkshop:fixed_overlap` | Sliding-window word splits. | When you want plain windowing with overlap, not structure-aware. |
| `chunkshop:neighbor_expand` | Hierarchy chunks expanded with neighbor context. | When chunks need surrounding context for retrieval to make sense. |

### Worked example: sales-CRM with chunkshop chunking

[`benchmarks/sales-crm-demo/ingest_chunkshop.py`](../../benchmarks/sales-crm-demo/ingest_chunkshop.py) is the exact same pipeline as `ingest_inmemory.py` (Pattern B) with `chunk_strategy="chunkshop:hierarchy"` instead of the default. Run it and compare the resulting graph shape against the original:

```bash
# Pattern B (built-in chunker, namespace: sales_crm_demo_small)
PGRG_NAMESPACE=sales_crm_demo_small uv run python benchmarks/sales-crm-demo/ingest.py

# Pattern D (chunkshop:hierarchy, namespace: sales_crm_chunkshop)
uv run python benchmarks/sales-crm-demo/ingest_chunkshop.py
```

Then sanity-check graph shape side-by-side:

```sql
SELECT 'pgrg-builtin' AS pipeline,
       (SELECT COUNT(*) FROM documents WHERE namespace='sales_crm_demo_small') AS docs,
       (SELECT COUNT(*) FROM chunks c JOIN documents d ON c.document_id=d.id
        WHERE d.namespace='sales_crm_demo_small') AS chunks,
       (SELECT COUNT(*) FROM entities WHERE namespace='sales_crm_demo_small') AS entities,
       (SELECT COUNT(*) FROM relationships WHERE namespace='sales_crm_demo_small') AS rels
UNION ALL
SELECT 'chunkshop:hier',
       (SELECT COUNT(*) FROM documents WHERE namespace='sales_crm_chunkshop'),
       (SELECT COUNT(*) FROM chunks c JOIN documents d ON c.document_id=d.id
        WHERE d.namespace='sales_crm_chunkshop'),
       (SELECT COUNT(*) FROM entities WHERE namespace='sales_crm_chunkshop'),
       (SELECT COUNT(*) FROM relationships WHERE namespace='sales_crm_chunkshop');
```

Real numbers from this corpus land in [`docs/cookbook/sales-crm-ingestion.md`](sales-crm-ingestion.md) once both runs complete.

## Pattern C — full chunkshop pipeline + pg-raggraph as graph layer

This is the integration shape that uses chunkshop's **full** value: not just the chunker, but the embedder *and* the metadata extractors. chunkshop runs end-to-end and writes its output into a pgvector table; pg-raggraph reads that table and adds the entity/relationship graph on top.

```
                                                                ┌────────────────┐
                                                                │  chunkshop     │
                                                                │  YAML config   │
                                                                └────────┬───────┘
                                                                         │
                                                                         ▼
                                                            chunkshop ingest
                                                            (chunker + embedder + extractor)
                                                                         │
                                                                         ▼
┌─────────────────────────────┐                              ┌──────────────────────┐
│ Source schema (your CRM /   │  ──── chunkshop YAML ──→     │ chunkshop output     │
│ ERP / file glob / etc.)     │                              │ table (pgvector)     │
└─────────────────────────────┘                              │  • original_content  │
                                                             │  • embedded_content  │
                                                             │  • embedding         │
                                                             │  • metadata (RAKE,   │
                                                             │    spaCy, langdet)   │
                                                             └──────────┬───────────┘
                                                                        │
                                                                        ▼
                                                           ┌─────────────────────┐
                                                           │ Bridge script       │
                                                           │ reads chunkshop out │
                                                           │ → ingest_records    │
                                                           │   (with caller-     │
                                                           │   known FK rels)    │
                                                           └──────────┬──────────┘
                                                                      ▼
                                                           ┌─────────────────────┐
                                                           │  pg-raggraph        │
                                                           │  documents/chunks/  │
                                                           │  entities/rels/     │
                                                           │  + Tier 1 features  │
                                                           └─────────────────────┘
```

### When to pick Pattern C

- You want **chunkshop's metadata extractors** (RAKE keywords, KeyBERT phrases, spaCy entities, language detection) on every chunk's metadata.
- You're already running chunkshop end-to-end for some other downstream consumer (e.g., dashboards directly on the pgvector table) and you want pg-raggraph to read the same source of truth.
- You want **int8 quantized embeddings** baked in (chunkshop's default fastembed registry includes pre-quantized variants).

### Sketch — the bridge script

```python
"""Read chunkshop's pgvector output table and feed pg-raggraph."""
import asyncio, os, psycopg
from pg_raggraph import GraphRAG

CHUNKSHOP_TABLE = "chunkshop.crm_chunks"   # set in your chunkshop YAML's target.table
PGRG_NAMESPACE  = "sales_calls"

# Read chunkshop's chunked + embedded + extracted output.
# Group by doc_id so each pg-raggraph "record" is a full document.
SQL = f"""
SELECT doc_id,
       string_agg(original_content, E'\\n\\n' ORDER BY seq_num) AS reconstructed_text,
       jsonb_agg(metadata ORDER BY seq_num) AS chunk_metadatas
FROM {CHUNKSHOP_TABLE}
GROUP BY doc_id
"""

async def main():
    rag = GraphRAG(
        dsn=os.environ["PGRG_DSN"],
        namespace=PGRG_NAMESPACE,
        # chunkshop already chunked. We could re-chunk via chunkshop:hierarchy
        # to keep boundaries identical, OR use chunk_strategy="auto" and let
        # pg-raggraph pick. Either way embeddings get re-computed by pg-raggraph
        # (today). See "Future: pre-computed embedding pass-through" below.
        chunk_strategy="chunkshop:hierarchy",
        llm_model="gpt-4o-mini",
        # ...etc
    )
    await rag.connect()
    with psycopg.connect(os.environ["CHUNKSHOP_DSN"], row_factory=psycopg.rows.dict_row) as conn:
        rows = list(conn.execute(SQL).fetchall())

    records = [{
        "text": row["reconstructed_text"],
        "source_id": f"chunkshop:{row['doc_id']}",
        "metadata": {
            # Hoist chunkshop's per-chunk extractor output (rake_keywords,
            # spacy_entities, etc.) into the document's metadata.
            "chunkshop_chunk_metadata": row["chunk_metadatas"],
        },
        # Caller-known FK relationships still apply on top — see the
        # sales-crm cookbook Pattern B example.
    } for row in rows]

    await rag.ingest_records(records, namespace=PGRG_NAMESPACE)
    await rag.close()

asyncio.run(main())
```

### Honest limitation: embeddings get re-computed today

In Pattern C, chunkshop already produced embeddings — but pg-raggraph's `ingest_records()` re-embeds every chunk. That's wasted work on Pattern C ingests.

A future pg-raggraph API extension would let `ingest_records()` accept pre-computed embeddings on each chunk and skip the embedding step. Captured as a backlog item; not built today. Until then, Pattern C is "uses chunkshop's chunking + extractor metadata, redundantly re-embeds." The redundant embedding cost is ~ a few seconds per 1000 chunks on bge-small CPU — acceptable for most ETL jobs but worth knowing.

## Choosing a pattern

| You want | Pick |
|---|---|
| Better chunking, minimal install, no extra moving pieces | **Pattern D** ⭐ |
| Better chunking + chunkshop's metadata extractors | Pattern C |
| Just-want-it-to-work | Default `chunk_strategy="auto"` (no chunkshop) |
| Maximum reproducibility with chunkshop's own benchmarks | Pattern C with the same YAML chunkshop uses for its bake-offs |

## Configuration reference

The new chunk_strategy values land in [`docs/Config-Reference.md`](../Config-Reference.md) under `chunk_strategy`. Default stays `"auto"` (no chunkshop). Setting any `"chunkshop:*"` value triggers the lazy import and will error with an install hint if the extra wasn't installed.

```python
PGRGConfig(
    chunk_strategy="chunkshop:hierarchy",  # opts in
    chunk_max_tokens=512,                  # tracked → chunkshop max_chars (≈ 4× tokens)
    chunk_overlap_tokens=50,               # tracked → chunkshop overlap_chars (where applicable)
)
```

## What's NOT in scope here

- **Replacing pg-raggraph's chunker** with chunkshop. The built-in stays the default; chunkshop is opt-in.
- **Replacing pg-raggraph's embedder.** pg-raggraph's `embedding_provider` is independent of `chunk_strategy`. Pattern C re-embeds; Pattern D uses pg-raggraph's embedder.
- **Hard-coupling.** chunkshop is on PyPI as `chunkshop>=0.3`. We pin the floor; you pin the version you want.
- **Replacing pg-raggraph's LLM extraction** with chunkshop's local extractors. Different roles: pg-raggraph's LLM extraction produces *typed entities and relationships* for the graph; chunkshop's extractors produce *flat keyword/entity lists* for filtering. They compose; they don't substitute.
