# Chunkshop User Guide

Use this guide when Chunkshop is the front door for ingestion and pg-raggraph is the graph retrieval layer. The short version:

- Use `chunk_strategy="chunkshop:<strategy>"` when you only want Chunkshop's chunker.
- Use `pre_chunked` or `pgrg ingest-chunkshop-table` when Chunkshop already wrote chunks and embeddings to Postgres.
- Use `--with-code-edges` when Chunkshop also produced `code_edges` and you want those edges in pg-raggraph's graph.

## Prerequisites

Install pg-raggraph with the optional Chunkshop extra:

```bash
pip install 'pg-raggraph[chunkshop]'
```

For source checkouts:

```bash
uv sync --extra chunkshop
```

The package floor is `chunkshop>=0.6.1` (on PyPI). This guarantees the 0.6 code chunker config classes, the `code_edges` / `code_relationships` surfaces, and the `code_summary` extractor that the `chunkshop:code_aware` / `chunkshop:symbol_aware` strategies and the code-edge import rely on.

## Choose an Integration Pattern

| Need | Use | Why |
|---|---|---|
| Better prose chunking without changing the rest of pg-raggraph | Pattern D, `chunk_strategy="chunkshop:hierarchy"` | One-line change. pg-raggraph still embeds, extracts entities, and stores the graph. |
| Python/code symbol chunking during normal pg-raggraph ingest | Pattern D, `chunk_strategy="chunkshop:code_aware"` or `chunkshop:symbol_aware` | Keeps pg-raggraph in charge while preserving code-specific chunk metadata. |
| Chunkshop already owns connectors, parsers, chunking, embedding, and extractors | Pattern C, bridge Chunkshop's Postgres table | Avoids re-chunking and re-embedding. pg-raggraph adds graph retrieval. |
| Chunkshop produced a code relationship table | Pattern C plus `code_edges` import | Adds `CODE_SYMBOL` entities and `CALLS` / `INHERITS` / `IMPLEMENTS` relationships. |

## Pattern D: Chunker-Only

Pattern D runs a Chunkshop chunker inside pg-raggraph ingest. You still call the usual SDK or CLI ingest paths.

```python
from pg_raggraph import GraphRAG

rag = GraphRAG(
    dsn="postgresql://postgres:postgres@localhost:5434/pg_raggraph",
    namespace="docs",
    chunk_strategy="chunkshop:hierarchy",
)
await rag.connect()
await rag.ingest(["./docs"], namespace="docs")
```

Supported strategy names:

| Strategy | Best fit |
|---|---|
| `chunkshop:hierarchy` | Markdown, docs, heading-structured prose. |
| `chunkshop:sentence_aware` | Long prose without reliable headings. |
| `chunkshop:semantic` | Topic-boundary splits, heavier than sentence or hierarchy. |
| `chunkshop:fixed_overlap` | Predictable windows with overlap. |
| `chunkshop:neighbor_expand` | Chunks that need nearby context attached. |
| `chunkshop:code_aware` | Python AST-aware chunks. Requires Chunkshop 0.6 code chunkers. |
| `chunkshop:symbol_aware` | Multi-language symbol-bounded chunks with FQN and `node_id` metadata. Requires Chunkshop 0.6 code chunkers. |

If you pick a Chunkshop strategy that is not installed in your local Chunkshop build, pg-raggraph raises a `ValueError` listing supported strategies.

## Pattern C: Import a Chunkshop Postgres Table

Pattern C is for full Chunkshop pipelines. Chunkshop writes a Postgres + pgvector sink table, then pg-raggraph imports that table through the `pre_chunked` ingest seam.

The Chunkshop table must expose these columns:

| Column | Required | Purpose |
|---|---:|---|
| `doc_id` | yes | Groups rows back into pg-raggraph records. |
| `seq_num` | yes | Orders chunks within each document. |
| `original_content` | yes | Stored as `chunks.content`; also reconstructs record `text`. |
| `embedded_content` | no | Stored as `chunks.embedded_content`; falls back to `original_content`. |
| `embedding` | yes | Passed through directly; dimension must match `GraphRAG(embedding_dim=...)`. |
| `metadata` | no | Stored on each pg-raggraph chunk. |
| `tags` | no | Added to chunk metadata as `tags`. |
| `source` | no | Added to chunk metadata as `chunkshop_source`. |

### CLI Import

```bash
pgrg --db "$PGRG_DSN" ingest-chunkshop-table \
  --schema chunkshop_docs \
  --table chunks \
  --namespace docs_graph \
  --source-prefix chunkshop \
  --skip-llm
```

Use `--skip-llm` when Chunkshop metadata is enough and you do not want pg-raggraph to run entity extraction. Omit it when you want pg-raggraph to extract entities and relationships from the reconstructed document text.

If Chunkshop wrote to a different database, pass it separately:

```bash
pgrg --db "$PGRG_DSN" ingest-chunkshop-table \
  --chunkshop-dsn "$CHUNKSHOP_DSN" \
  --schema chunkshop_docs \
  --table chunks \
  --namespace docs_graph
```

### SDK Import

```python
from pg_raggraph import GraphRAG
from pg_raggraph.chunkshop_bridge import fetch_records_from_table

records = fetch_records_from_table(
    "postgresql://postgres:postgres@localhost:5434/pg_raggraph",
    schema="chunkshop_docs",
    table="chunks",
    source_prefix="chunkshop",
    skip_llm=True,
)

rag = GraphRAG(
    dsn="postgresql://postgres:postgres@localhost:5434/pg_raggraph",
    namespace="docs_graph",
)
await rag.connect()
await rag.ingest_records(records, namespace="docs_graph")
```

When you already have rows in memory, use `rows_to_records(rows)` instead of fetching from Postgres.

## Import Code Edges

Chunkshop 0.6 can emit code symbol relationships into `<schema>.code_edges`. pg-raggraph can import those as graph facts.

Expected `code_edges` columns:

| Column | Purpose |
|---|---|
| `project_id` | Optional filter and provenance. |
| `edge_type` | Relationship type such as `CALLS`, `INHERITS`, or `IMPLEMENTS`. |
| `src_fqn` / `dst_fqn` | Source and target fully qualified symbols. |
| `src_node_id` / `dst_node_id` | Chunkshop symbol node ids. |
| `confidence` | Edge confidence; filter with `--min-confidence`. |
| `evidence` | JSONB evidence, including snippets or resolution details. |

CLI:

```bash
pgrg --db "$PGRG_DSN" ingest-chunkshop-table \
  --schema chunkshop_code \
  --table kb_code \
  --namespace code_graph \
  --with-code-edges \
  --project-id kb_code \
  --min-confidence 0.7 \
  --skip-llm
```

SDK:

```python
from pg_raggraph.chunkshop_bridge import (
    attach_code_edges,
    fetch_code_edges_from_table,
    fetch_records_from_table,
)

records = fetch_records_from_table(
    dsn,
    schema="chunkshop_code",
    table="kb_code",
    skip_llm=True,
)
entities, relationships = fetch_code_edges_from_table(
    dsn,
    schema="chunkshop_code",
    project_id="kb_code",
    min_confidence=0.7,
)
if records and (entities or relationships):
    records[0].setdefault("entities", []).extend(entities)
    records[0].setdefault("relationships", []).extend(relationships)
await rag.ingest_records(records, namespace="code_graph")
```

`attach_code_edges(records, rows)` is the convenience helper when you have raw `code_edges` rows instead of the already-converted `(entities, relationships)` tuple.

Imported code edges create `CODE_SYMBOL` entities. Relationship `properties` preserve `project_id`, Chunkshop node ids, and the evidence JSON. Known entity `properties` are also persisted and merged by name. When the imported chunks carry a per-symbol `summary` (Chunkshop's `symbol_aware` chunker plus the `code_summary` extractor, surfaced as `metadata.fqn` + `metadata.summary`), the matching `CODE_SYMBOL` entity's description is set to that summary instead of the generic `Code symbol {fqn}`.

## Querying the Code Graph (`code-impact`)

Once code edges are imported, query the call graph by symbol FQN:

```bash
pgrg --db "$PGRG_DSN" code-impact pkg.module.func -n code_graph --depth 2
```

This prints the symbol's **callers** (who depends on it) and **callees** (what it calls), with evidence snippets, walking up to `--depth` hops (default 1). Add `--json` for scripting, and `--min-confidence` to drop low-weight edges. A missing symbol exits non-zero.

From Python:

```python
impact = await rag.code_impact("pkg.module.func", depth=2)
for edge in impact.callers:
    print(edge.fqn, edge.rel_type, edge.evidence, edge.depth)
```

`code_impact` returns a `CodeImpact` dataclass (`fqn`, `found`, `callers`, `callees`); each edge is a `CodeEdge` (`fqn`, `rel_type`, `evidence`, `depth`). It traverses the same `relationships` graph the code-edge import populated, so symbols enriched with a `code_summary` description show that summary in their entity record.

## Verify an Import

Check counts:

```bash
pgrg --db "$PGRG_DSN" status --namespace code_graph
```

Inspect imported chunk metadata:

```sql
SELECT c.content,
       c.metadata->>'chunkshop_doc_id' AS doc_id,
       c.metadata->>'chunkshop_seq_num' AS seq_num,
       c.metadata->>'symbol_name' AS symbol_name
FROM chunks c
JOIN documents d ON d.id = c.document_id
WHERE d.namespace = 'code_graph'
ORDER BY d.id, (c.metadata->>'chunkshop_seq_num')::int
LIMIT 20;
```

Inspect imported code relationships:

```sql
SELECT s.name AS src,
       r.rel_type,
       t.name AS dst,
       r.properties
FROM relationships r
JOIN entities s ON s.id = r.src_id
JOIN entities t ON t.id = r.dst_id
WHERE r.namespace = 'code_graph'
ORDER BY r.id
LIMIT 20;
```

## Troubleshooting

| Symptom | Fix |
|---|---|
| `missing required option '--schema'` | Pass the schema where Chunkshop wrote the sink table. |
| `No Chunkshop rows found.` | Check `--chunkshop-dsn`, `--schema`, and `--table`; pg-raggraph imports only rows visible to that DSN. |
| `embedding has dim ... but config.embedding_dim=...` | Match `GraphRAG(embedding_dim=...)` to the Chunkshop embedder. bge-small is usually 384, bge-base is usually 768. |
| `chunkshop row has NULL embedding` | Pattern C requires embeddings because pg-raggraph bypasses its embedder for `pre_chunked` imports. Re-run Chunkshop with an embedder enabled. |
| `code_edges row must include non-empty src_fqn and dst_fqn` | Regenerate Chunkshop code edges or filter malformed rows before import. |
| `chunkshop:code_aware` is unsupported | Install a Chunkshop build that includes the 0.6 code chunker config classes. |

## Test Commands

Run the focused tests for this integration:

```bash
uv run pytest tests/unit/test_chunking.py \
  tests/unit/test_chunkshop_bridge.py \
  tests/unit/test_cli_chunkshop.py \
  tests/integration/test_chunkshop_bridge.py -q
```

Run the broader local suite:

```bash
docker compose up -d postgres
uv run pytest tests/unit -q
uv run pytest tests/integration -q
```
