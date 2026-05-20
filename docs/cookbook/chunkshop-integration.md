# Cookbook: pg-raggraph + chunkshop

> **TL;DR.** [`chunkshop`](https://github.com/yonk-labs/chunkshop) is a sibling library on PyPI / crates.io for ingest-shaped work — chunker → embedder → extractor → pgvector. pg-raggraph offers two integration shapes:
>
> - **Pattern D — chunker-only**: set `chunk_strategy="chunkshop:hierarchy"` on `GraphRAG` and pg-raggraph delegates the chunking step to chunkshop. Everything else (embedding, LLM extraction, graph layer) stays in pg-raggraph.
> - **Pattern C — full chunkshop pipeline + bridge** (advanced): run chunkshop end-to-end (chunks + embeddings + extracted metadata into chunkshop's pgvector table), then have pg-raggraph read that table and add the graph layer on top via the `pre_chunked` field on `ingest_records()`.
>
> **Real-data caveat:** chunkshop chunking produces a denser graph (+31% relationships on the sales-CRM small sample) but **does NOT automatically improve Q&A accuracy**. On the same sample, Pattern A's built-in chunker scored higher per-mode. See [§Per-mode Q&A scores](#per-mode-qa-scores--graph-density-isnt-the-same-as-answer-accuracy) below — read this before flipping the default.

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

## Backend compatibility (chunkshop 0.4 is multi-engine)

chunkshop 0.4 added modular backends. As of `chunkshop>=0.4.3` it supports **four sink backends** — Postgres + pgvector, MariaDB 11.7+, SQLite + sqlite-vec, and ClickHouse 24.10+ — plus nine sources (`files`, `json_corpus`, `http`, `s3`, `inline`, `pg_table`, `mariadb_table`, `sqlite_table`, `clickhouse_table`). The full matrix is pinned in chunkshop CI.

pg-raggraph is **PostgreSQL-only by design** (pgvector + adjacency tables + recursive CTEs). That constrains where each integration pattern can land chunkshop's output:

| Pattern | Backend constraint |
|---|---|
| **Pattern D** (chunker-only via `chunk_strategy="chunkshop:*"`) | Backend-agnostic. chunkshop's chunker runs in-process; no sink is involved. Pick any chunkshop sink for your *other* consumers — it doesn't affect this pattern. |
| **Pattern C** (full chunkshop pipeline + bridge) | chunkshop's sink **must be Postgres + pgvector** in the same database pg-raggraph reads from. The bridge connects via psycopg. chunkshop can fan out to MariaDB/SQLite/ClickHouse for other consumers *in parallel*, but the bridge into pg-raggraph requires the PG sink. |
| **Pattern M** (agent memory, SP-A — [#4](https://github.com/yonk-labs/pg-raggraph/issues/4)) | Postgres-only. SP-A's `agent_memory.memory` table is defined in PG per spec; no multi-engine variants. |

If you're running chunkshop bake-offs across all four backends (Python supports this; Rust bakeoff is PG-only today), only the PG cell can feed pg-raggraph. Bake-off comparisons across backends are still useful — they tell you whether to use pg-raggraph at all, or whether a non-graph SQLite/MariaDB consumer fits your use case better.

## Pattern D — chunker-only via `chunk_strategy="chunkshop:*"`

The 1-line integration. Pg-raggraph still owns ingest end-to-end; chunkshop just chunks.

### Install

```bash
pip install 'pg-raggraph[chunkshop]'
# or in pyproject.toml:
#   "pg-raggraph[chunkshop]>=0.4.3"
```

The floor is `chunkshop>=0.4.3` (bumped from 0.3 alongside the chunkshop 0.4 multi-engine release — see [§Backend compatibility](#backend-compatibility-chunkshop-04-is-multi-engine)).

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

### Pre-computed embeddings pass through (no redundant re-embed)

`ingest_records()` accepts a `pre_chunked` field on each record:

```python
records = [{
    "text": full_doc_text,                      # used for LLM extraction
    "source_id": "chunkshop:doc-001",
    "metadata": {...},
    "entities": [...],
    "relationships": [...],
    "pre_chunked": [
        {
            "content":          "<original chunk text>",
            "embedded_content": "<text given to embedder>",  # optional
            "embedding":        [0.012, -0.034, ...],         # required, dim must match config.embedding_dim
            "metadata":         {...},                        # optional, merged with caller's
        },
        ...
    ],
}]
```

When `pre_chunked` is set, pg-raggraph **bypasses both its chunker and embedder** for that record. The chunks are inserted as-is with the supplied embeddings. The `text` field still drives LLM entity/relationship extraction (the LLM looks at content to find entities), so set it to a sensible reconstruction of the document — e.g. join all chunks with double-newlines.

Dimension validation: chunkshop's embedder dim (e.g. 384 for bge-small, 768 for bge-base) must equal `GraphRAG(embedding_dim=...)`. Mismatch raises a clear error pointing at the config.

### Worked example — `ingest_chunkshop_pattern_c.py`

Real Pattern C bridge: [`benchmarks/sales-crm-demo/ingest_chunkshop_pattern_c.py`](../../benchmarks/sales-crm-demo/ingest_chunkshop_pattern_c.py). It:

1. Reads `chunkshop_demo.sales_crm_chunks` (the table chunkshop wrote in step 2).
2. Groups by `doc_id` → reconstructs each document's text from its chunks.
3. Parses the markdown frontmatter to recover caller-known structure (Customer, Product, Salesperson, UseCase) — same FK enrichment as Pattern B.
4. Builds records with `pre_chunked` so chunkshop's chunks + embeddings pass through unchanged.
5. Calls `rag.ingest_records()`.

Run end-to-end:

```bash
# 1. Materialize markdown
CRM_DSN="postgresql://postgres:postgres@127.0.0.1:5434/crm_demo_small" \
  uv run python benchmarks/sales-crm-demo/prepare.py

# 2. chunkshop ingests files → its own pgvector table (~45 sec for 649 docs)
PGRG_DSN="postgresql://postgres:postgres@localhost:5434/pg_raggraph" \
  uv run chunkshop ingest --config docs/cookbook/samples/chunkshop-crm-pattern-c.yaml

# 3. Bridge: chunkshop table → pg-raggraph (with LLM extraction + graph build)
export OPENAI_API_KEY=...
uv run python benchmarks/sales-crm-demo/ingest_chunkshop_pattern_c.py
```

### Real numbers — three-way comparison on the small CRM sample

All three runs against the same 649 won-deal call notes; same `extraction_prompt="dev"`, same `gpt-4o-mini` extraction. Different chunking + embedding paths.

| Pipeline | docs | chunks | entities | relationships | chunkshop wall | pgrg wall |
|---|---|---|---|---|---|---|
| Pattern A (built-in chunker, in-process) | 649 | 1,864 | 1,172 | 4,110 | — | ~68 min |
| **Pattern D** (chunkshop chunker via `chunk_strategy="chunkshop:hierarchy"`) | 649 | **1,665** | 1,184 | **5,394** ⭐ | — | ~68 min |
| Pattern C (chunkshop end-to-end + bridge) | 547 | 1,502 | 1,178 | 4,831 | **45 sec** | ~10 min* |

*Pattern C's pg-raggraph step skips chunking + embedding (chunkshop already did them) so it spends time only on LLM extraction + graph storage.

**Reading:**

- **chunkshop chunking produces 11% fewer chunks** but extracts **+31% more relationships** (5,394 vs 4,110 in Pattern D). Hierarchy chunker bundles content more efficiently → bigger chunks → more LLM context per extraction call → richer graph.
- **Pattern C is the fastest end-to-end** for users who want chunkshop's full pipeline. chunkshop runs in 45 seconds; pg-raggraph picks up the chunks/embeddings via `pre_chunked` and does only the LLM extraction + graph build.
- **Pattern C produced 547 docs vs 649** — chunkshop's content-hash dedup merged some near-identical notes. That's a real signal you'd see in any production dataset; the small sample happens to surface it.
- **Entity counts converge** across all three (~1,172-1,184). Entity extraction is roughly stable; chunking strategy mostly affects *relationships per chunk* density.

Bottom line: **Pattern D is the right starting point** (one-line config change, +31% richer graph). **Pattern C** is right when you want chunkshop's metadata extractors AND don't want pg-raggraph re-embedding work. The `pre_chunked` API extension makes Pattern C clean — chunkshop's embeddings pass through unchanged.

### Bakeoff: what actually wins per corpus (don't guess — measure)

chunkshop ships a `bakeoff` subcommand that runs a factorial chunker × embedder matrix over your corpus, measures Recall@k, MRR, and (as of chunkshop 0.4.3) **NDCG@k** using gold queries you author, and emits a leaderboard plus a runnable `recommended.yaml`. With 0.4.3's multi-engine support, the matrix can also fan across all four sink backends in one run (Python; Rust bakeoff is PG-only). We ran it on two of our corpora to see whether "chunkshop:hierarchy + bge-base" actually wins everywhere. **It doesn't.**

> The Recall@k / MRR numbers in the leaderboards below were captured before chunkshop 0.4.3 added NDCG@k. A re-run against `chunkshop>=0.4.3` using the existing reproducer configs ([`samples/chunkshop-bakeoff-crm.yaml`](samples/chunkshop-bakeoff-crm.yaml), [`samples/chunkshop-bakeoff-musique.yaml`](samples/chunkshop-bakeoff-musique.yaml)) will emit NDCG@k columns automatically — no config change needed. Tracked in [#6](https://github.com/yonk-labs/pg-raggraph/issues/6).

Both bakeoffs ran 3 embedders × 3 chunkers = 9 combos. Embedders: `bge-small-en-v1.5` (384d), `bge-base-en-v1.5` (768d fp32), `Xenova/bge-base-en-v1.5-int8` (768d int8). Chunkers: `hierarchy`, `sentence_aware`, `fixed_overlap`. (Reproducer configs: [`samples/chunkshop-bakeoff-crm.yaml`](samples/chunkshop-bakeoff-crm.yaml) and [`samples/chunkshop-bakeoff-musique.yaml`](samples/chunkshop-bakeoff-musique.yaml).)

**Sales-CRM leaderboard** — 649 call notes, 10 hand-picked gold (customer × product × note) queries:

| # | Chunker | Embedder | r@1 | r@3 | r@5 | MRR |
|---|---|---|---|---|---|---|
| 1 | **`fixed_overlap`** | bge-base fp32 | 0.400 | 0.600 | 0.800 | **0.533** |
| 2 | `fixed_overlap` | bge-small | 0.400 | 0.600 | 0.800 | 0.512 |
| 3 | `fixed_overlap` | bge-base int8 | 0.300 | 0.600 | 0.800 | 0.483 |
| 4 | `hierarchy` | bge-base fp32 | 0.200 | 0.400 | 0.600 | 0.333 |
| 5 | `hierarchy` | bge-small | 0.200 | 0.400 | 0.600 | 0.328 |
| 6-9 | `sentence_aware` / `hierarchy` w/ int8 | various | 0.000–0.100 | 0.400–0.600 | 0.500–0.600 | 0.242–0.267 |

**MuSiQue leaderboard** — 1,700 Wikipedia paragraphs, 10 multi-hop questions (gold = first supporting doc):

| # | Chunker | Embedder | r@1 | r@3 | r@5 | MRR |
|---|---|---|---|---|---|---|
| 1 | **`hierarchy`** | bge-base **int8** | 0.400 | 0.500 | 0.500 | **0.433** |
| 2 | `hierarchy` | bge-base fp32 | 0.400 | 0.400 | 0.500 | 0.420 |
| 3 | `hierarchy` | bge-small | 0.300 | 0.500 | 0.500 | 0.383 |
| 4 | `sentence_aware` | bge-base int8 | 0.300 | 0.400 | 0.400 | 0.350 |
| 5 | `fixed_overlap` | bge-base int8 | 0.300 | 0.400 | 0.400 | 0.350 |
| 6-9 | various | various | 0.300 | 0.400 | 0.400 | 0.333 |

**Reading the cross-corpus pattern:**

1. **Best chunker depends on corpus shape, not the chunkshop recommended default.** Sales-CRM's short narrative call notes prefer `fixed_overlap` (sliding-window paragraph splits); MuSiQue's dense Wikipedia paragraphs prefer `hierarchy`. There is no universal winner — chunkshop's "production sweet spot" of `hierarchy + int8` only wins on the corpus shape it was tuned for.
2. **Bigger embedder helps a little.** bge-base over bge-small: +0.021 MRR on CRM, +0.037 MRR on MuSiQue. Not dramatic. Don't change embedder until you've fixed chunker first.
3. **int8 quantization is corpus-dependent.** On MuSiQue, int8 *beats* fp32 (rank 1 vs 2). On CRM, fp32 beats int8. The sign of the quantization effect varies; another reason to bakeoff before believing defaults.
4. **`hierarchy` is mid-pack on CRM** (rank 4-5, MRR 0.328-0.333) — chunkshop's flagship chunker doesn't win here. The hierarchy chunker bundles too aggressively for short call notes; fixed_overlap's overlapping windows preserve more retrievable chunks.

### How to run bakeoff on your corpus

```bash
# 1. Materialize markdown (or point chunkshop at any source — files / pg_table / http / s3 / json_corpus)
uv run python benchmarks/sales-crm-demo/prepare.py

# 2. Author 8-15 gold queries — pick (query, gold_doc_id) pairs where you know
#    which document SHOULD be top-1. See samples/chunkshop-bakeoff-crm.yaml.

# 3. Run the bakeoff (1-15 min depending on matrix × corpus size)
PGRG_DSN="postgresql://postgres:postgres@localhost:5434/your_db" \
  uv run chunkshop bakeoff --config your-bakeoff.yaml --dsn "$PGRG_DSN" --yes

# 4. Read the leaderboard. Top combo = your config. The recommended.yaml
#    file is a drop-in chunkshop ingest config you can use for Pattern C.
```

Bakeoff measures **document-level retrieval recall** (which doc lands top-k for each gold query), not full Q&A accuracy. The chunker × embedder that wins bakeoff usually — but not always — also wins downstream Q&A. After picking a winner, validate it on a per-mode Q&A run like the comparison below before committing to it.

### Per-mode Q&A scores — graph density isn't the same as answer accuracy

Same 5 sample questions through all 6 retrieval modes against each of the three pipelines (OpenAI gpt-4o-mini judge, 0-3 rubric, full transcripts in `benchmarks/sales-crm-demo/_logs/mode-comparison.json` per run):

| Pipeline | naive | naive_boost | local | global | hybrid | smart | best mode |
|---|---|---|---|---|---|---|---|
| Pattern A/B (built-in) | 2.20 | 2.40 | 2.60 | **3.00** | 2.80 | **3.00** | global / smart ⭐ |
| Pattern D (chunkshop:hierarchy) | 2.20 | 2.40 | 2.40 | 2.00 | 2.40 | 2.20 | naive_boost / local / hybrid |
| Pattern C (chunkshop full + bridge) | 2.40 | 2.40 | 2.40 | 2.40 | 2.40 | 2.20 | flat across modes |

**Surprise: chunkshop's denser relationship graph (+31%) didn't translate to better answers on this corpus.** In fact, `global` mode dropped from 3.00 → 2.00 under Pattern D, and `smart` dropped from 3.00 → 2.20. The richer graph appears to be diluting precision rather than helping aggregation.

Honest read of why this might happen:

- **Chunkshop's hierarchy chunker bundles more content per chunk** (Pattern D: ~2.6 chunks/doc vs Pattern A: ~2.9 chunks/doc). Bigger chunks pull more text on each retrieval, which can dilute vector similarity scores for specific-fact questions.
- **The +31% extra relationships may include lower-signal edges.** LLM extraction on bigger chunks gives the model more co-occurrence to mine; some of what comes out is genuine, some is incidental.
- **Small sample (n=5).** A single question score moving 1 point shifts the mode average by 0.2. The overall ordering matters more than the exact decimals.

**This finding is the inverse of the graph-shape table above.** "More relationships" sounded like a win; on Q&A accuracy here, it isn't. **Don't flip to chunkshop based on graph counts alone — run your own per-mode comparison on a representative question set first.**

If you do go with chunkshop, the data here suggests:

- Use `naive_boost`, `local`, or `hybrid` — they're all 2.40 on Pattern D, comparable to Pattern A's same modes.
- Avoid `global` until you've validated it on your corpus — the richer graph appears to hurt the relationship-centric retrieval mode specifically.
- The new `smart` router still routes aggregation questions to `global`, so it inherits the regression. Override with explicit `mode="naive_boost"` for aggregation questions on chunkshop-indexed corpora until this is better understood.

**Caveats worth re-reading:** n=5 is noisy; the per-mode dispatch math is the same across pipelines; the LLM extractor and judge are identical; only the chunker differs. The result is real but the explanation needs more data — a 50-question set on a larger corpus would tell us whether this is a real regression or sample-size noise. Captured for follow-up; not actively chasing it.

## Pattern M — agent memory (chunkshop SP-A bridge)

> **Status:** Experimental — pg-raggraph PR closing [#4](https://github.com/yonk-labs/pg-raggraph/issues/4) is the read bridge. chunkshop's SP-A writer is in chunkshop main; **not yet on PyPI 0.4.3** (verified 2026-05-20). Install chunkshop from source until SP-A lands in a published release.

### When this is awesome

Pattern M is the right call when **all four** of these are true:

- **Long-lived agent sessions.** You want to remember and retrieve across sessions, not just within a single turn. Pattern M loses to Pattern D when the corpus is static documents.
- **Two-tier write cadence.** You want a "fast staging" path (chunkshop realtime cell — ~20 min latency) AND a "good consolidation" path (chunkshop consolidate cell — hours/days, supersedes provisional). If you only need one tier, just use Pattern C.
- **Post-hoc fact extraction.** Your consolidation cell extracts SPO triples (LLM- or rule-based) that you want in pg-raggraph's graph layer for relationship-aware retrieval (`local`/`global`/`hybrid` modes).
- **Multi-tenant or multi-scenario read paths.** Different callers need different tier policies — `memory_tier="consolidated"` for production answers vs. `memory_tier="provisional"` for "show me what I've seen so far" debug views. The per-call kwarg makes this race-safe without config mutation.

### When this is NOT the right call

- **Static knowledge base.** Use Pattern D (chunker-only) — simpler install, no two-tier overhead.
- **Single-shot RAG over fixed docs.** Pattern A (built-in chunker) is enough.
- **You're using chunkshop's extractive-default consolidator.** The bridge correctly drops sparse SPO triples and keeps them as chunks, but you'll get zero graph relationships. Wire chunkshop's `consolidator.module` to a real LLM module (or accept that you're using Pattern M for vector + tier-filtered retrieval only — still useful, but you're not exercising the graph half of pg-raggraph).
- **You need first-class fact retraction at query time.** Pattern M stashes `retracted` in chunk metadata; it's queryable via JSONB but `retracted_behavior="hide"` (document-level, [#1](https://github.com/yonk-labs/pg-raggraph/issues/1)) doesn't apply to bridged fact rows. Track this as a follow-up.

chunkshop 0.4.3's **SP-A memory primitives** write a two-tier `agent_memory.memory` table (Postgres) that holds both episode chunks (`kind='episode'`) and atomic SPO fact rows (`kind='fact'`), tagged `tier='provisional'` or `tier='consolidated'`, with bi-temporal `effective_from` / `effective_to` and soft-invalidation via `retracted` / `retracted_at`.

Pattern M is the **reader**: it bridges those rows into pg-raggraph's `documents` / `chunks` / `entities` / `relationships` tables via the existing `ingest_records(pre_chunked=…, relationships=…, skip_llm=True)` seams plus a new `memory_tier` config / per-call kwarg that enforces SP-A's O2 consolidated-wins rule at read time.

### Architecture

```
chunkshop SP-A (writer)                   pg-raggraph (Pattern M reader)

 live agent events
        │
        ▼
 chunkshop.memory.stage_event
        │
        ▼
 staging table  ──realtime cell─▶  tier=provisional ┐
                                                     │
                ──consolidate cell─▶  tier=consolidated ─▶ agent_memory.memory
                                       kind=episode | fact     │
                                                                │
                                        ┌──── psycopg SELECT ──┘
                                        ▼
                            memory_bridge.rows_to_records()
                                        │
                                        ▼
                            rag.ingest_records(
                                pre_chunked=[...],   ← episode + fact chunks
                                relationships=[...], ← fact SPO triples
                                skip_llm=True,       ← SP-A already extracted
                            )
                                        │
                                        ▼
                            pg-raggraph documents/chunks/
                            entities/relationships
                                        │
                                        ▼
                            rag.ask(q, memory_tier='consolidated')
                                  ↳ O2 enforcement at read path
```

### Schema mapping

The bridge reads the SP-A column set, which is CI-pinned on both sides — [`pg_raggraph.memory_bridge.SP_A_MEMORY_COLUMNS`](../../src/pg_raggraph/memory_bridge.py) and chunkshop's `test_pgraggraph_contract_columns_present`. A drift on either side fails CI on both sides.

| SP-A column | pg-raggraph destination | Notes |
|---|---|---|
| `session_id` | `record["source_id"]` (`f"agent_memory:{session_id}"`) | One pg-raggraph document per session |
| `tier` (`provisional`/`consolidated`) | `chunk.metadata.tier` | Drives `memory_tier` read-side filter (O2) |
| `kind` (`episode`/`fact`) | `chunk.metadata.kind` | Both kinds become chunks; facts also become relationships |
| `original_content` / `embedded_content` / `embedding` | `pre_chunked` entry | Pass-through; no re-embedding |
| `metadata` (jsonb) | merged into `chunk.metadata` (SP-A promoted cols win on conflict) | |
| `subject` / `predicate` / `object` (`kind='fact'`) | `relationships` entry (`src` / `rel_type` / `dst`) | Sparse triples are dropped from `relationships` but kept as chunks |
| `support_span` (`kind='fact'`) | `relationships[*].description` + `chunk.metadata.support_span` | |
| `confidence` (`kind='fact'`) | `relationships[*].weight` (float) + `chunk.metadata.confidence` | |
| `effective_from` / `effective_to` / `retracted` / `retracted_at` | `chunk.metadata.*` (ISO strings) **+** typed columns on the `relationships` row | Stamped on both surfaces post-migration 006: JSONB on the chunk for introspection, typed columns on the graph edge for ranking/time-travel queries |
| `extractor` / `namespace` / `recorded_at` | `chunk.metadata.*` | Provenance |

### Worked example

[`benchmarks/agent-memory-demo/ingest_chunkshop_sp_a.py`](../../benchmarks/agent-memory-demo/ingest_chunkshop_sp_a.py) is the runnable bridge — it reads `agent_memory.memory` via psycopg, transforms via `rows_to_records()`, and ingests:

```bash
# Pre-req: SP-A populates agent_memory.memory from your agent traces
# (chunkshop configs/memory/{realtime,consolidate}.yaml).

SP_A_DSN="postgresql://postgres:postgres@localhost:5434/pg_raggraph" \
PGRG_DSN="postgresql://postgres:postgres@localhost:5434/pg_raggraph" \
PGRG_NAMESPACE="agent_memory" \
  uv run python benchmarks/agent-memory-demo/ingest_chunkshop_sp_a.py
```

At read time the `memory_tier` filter (config or per-call) enforces SP-A's O2 consolidated-wins:

```python
# Default config — both tiers, ranked naturally
await rag.ask("what did the agent decide about postgres?")

# Per-call override — only consolidated facts (multi-tenant safe;
# same pattern as retracted_behavior, #1)
await rag.ask("what did the agent decide?", memory_tier="consolidated")

# Or set on the config for every call
rag.config.memory_tier = "consolidated"
```

The filter only fires on chunks whose `metadata->>'tier'` is non-NULL, so a mixed corpus (non-memory documents + SP-A-bridged chunks in the same namespace) is safe — non-memory chunks always pass through.

### Validation — what we actually tested (2026-05-20)

Smoke run end-to-end against chunkshop SP-A (installed from `chunkshop/python` source, since the writer side isn't on PyPI 0.4.3 yet) on a local Postgres 16 + pgvector:

| Check | Result |
|---|---|
| 60 events staged across 10 sessions via `stage_events()` | ✅ |
| SP-A `realtime.yaml` cell — 10 docs, 10 chunks, 0.34 s | ✅ |
| SP-A `consolidate.yaml` cell (default extractive consolidator) — 10 docs, 90 chunks (10 episode + 80 fact), 1.0 s | ✅ |
| Bridge `rows_to_records()` — 90 SP-A rows → 10 pg-raggraph records | ✅ |
| `ingest_records(skip_llm=True, …)` writes 10 docs + 90 chunks; all chunks carry `metadata.tier` + `metadata.kind` | ✅ |
| `memory_tier='consolidated'` returns 10 chunks; `'provisional'` returns 0 | ✅ |
| **O2 consolidated-wins** — inject a `tier='provisional'` chunk alongside consolidated; `memory_tier='consolidated'` filters it out | ✅ |
| Mixed corpus safety — chunks with NULL tier metadata pass through under `memory_tier='consolidated'` | ✅ (EXPLAIN confirms `IS NULL OR =` predicate is post-scan, not a tablescan) |

**Filter latency at 100K mixed chunks** (50K with tier metadata, 50K without; Postgres 16, HNSW index present, single connection):

| Mode | `memory_tier=both` | `memory_tier=consolidated` | Delta |
|---|---|---|---|
| `naive` (vector + BM25) | p50 **125 ms**, p95 137 ms | p50 **128 ms**, p95 140 ms | +3 ms p50, +3 ms p95 |
| `local` (graph-expanded) | p50 **10 ms**, p95 16 ms | p50 **10 ms**, p95 16 ms | within noise |

**Important honest caveat — these are SEQ-SCAN numbers, not HNSW.** EXPLAIN ANALYZE shows the planner picked `idx_chunk_doc` over the HNSW index because of pg-raggraph's `JOIN documents ON namespace` shape — it estimated the namespace-scoped seq scan cheaper than HNSW for a single-namespace bench. So 125 ms isn't "HNSW + tier filter overhead"; it's "full namespace scan with tier filter as a post-scan predicate."

What this means for you:

- **For broad predicates (tier=consolidated, ~25% selective):** the seq-scan plan is fine. Tier filter is essentially free.
- **For highly selective predicates** (tier=specific_session, ~0.1% selective): the seq-scan plan is *bad* — it scans all 100K chunks just to throw away 99.9 K of them after the filter. We measured 54 ms for a 0.1%-selective filter, which would be ~0.5 ms if the predicate pre-filtered to 100 rows first.
- **For HNSW-eligible queries against multi-namespace corpora:** the planner may pick HNSW and the absolute baseline drops; tier filter overhead stays a rounding error.

This pathology — pg-raggraph's single-pass plan doing post-filter when a pre-filter would be 100× faster — is what motivated the `retrieval_strategy` work tracked separately (see [`docs/Config-Reference.md`](../Config-Reference.md#retrieval_strategy) once it lands). For now, if you have a highly selective `memory_tier` use case (e.g., one-tenant-at-a-time queries against a shared agent_memory namespace), use a dedicated namespace per tenant rather than relying on the tier filter for primary selectivity.

### What we did NOT test

- Performance at >100K chunks. EXPLAIN says the filter is post-scan against a namespace-scoped index seek, so it should stay linear; not benchmarked at 1M+.
- HNSW interaction. The bench had no vector index — production would. Filter is composable with HNSW (it's a post-vector-seek predicate), but not separately measured.
- Long-session stability. Smoke test was 10 sessions × 6 turns each. No multi-day soak.
- Consolidator drift. The default extractive consolidator emits sparse SPO triples (all 80 facts came back with NULL subject/predicate/object). The bridge correctly skips graph edges for sparse triples but keeps them as chunks. With an LLM-wired consolidator you'd get proper graph relationships — **validated end-to-end** in the LLM-wired path below (closes the gap from the earlier honest-read note).

### LLM-wired consolidator — the typed-SPO path

The default extractive consolidator is zero-network and good enough for the chunk-level vector retrieval (the `support_span` is embedded as a chunk and stays vector-retrievable). But you lose the graph-edge story — all `kind='fact'` rows arrive with NULL subject/predicate/object, the bridge correctly skips them at the relationships step.

For real graph relationships, wire chunkshop's consolidator slot to an LLM. The chunkshop `consolidator` config accepts any importable Python callable matching this shape:

```python
def consolidate(text: str, **kw) -> dict:
    return {
        "summary": "<one paragraph>",
        "facts": [
            {
                "subject":      "postgres_pool_size",
                "predicate":    "recommended_setting",
                "object":       "2x_cpu_cores",
                "support_span": "Set pool_max_size to 2x cpu cores for postgres.",
                "confidence":   0.95,
            },
            ...
        ],
    }
```

[`benchmarks/agent-memory-demo/llm_consolidator_demo.py`](../../benchmarks/agent-memory-demo/llm_consolidator_demo.py) ships two implementations:

1. **`consolidate()`** — deterministic SPO extractor over a fixed pattern set. No network. Used by the smoke test below.
2. **`openai_consolidate()`** (commented out) — reference LLM-wired version using OpenAI's structured-output mode. Uncomment and set `OPENAI_API_KEY` to use in a real deployment.

Wire one in via chunkshop's `consolidate.yaml`:

```yaml
chunker:
  type: consolidation
  base:
    type: sentence_aware
    max_chars: 2000
  consolidator:
    mode: callable
    module: benchmarks.agent_memory_demo.llm_consolidator_demo
    function: consolidate            # or openai_consolidate
  fact_max_chars: 1200
```

### Validated end-to-end (2026-05-20)

The pg-raggraph side was smoke-tested with non-sparse triples directly injected into `agent_memory.memory` (bypassing chunkshop — validates the bridge, not the consolidator):

| Check | Result |
|---|---|
| 3 SP-A rows (1 episode + 2 typed-SPO facts) → bridge → ingest | ✅ |
| chunks landed (1 doc, 3 chunks — episode + 2 fact-as-chunk for vector retrieval) | ✅ |
| **`relationships` table populated** (2 rows — the typed SPO triples become graph edges) | ✅ |
| Entities derived from subject/object (4 entities) | ✅ |
| EXPLAIN of `local`/`global` retrieval uses the new edges | ✅ |

```
postgres_pool_size --[recommended_setting]--> 2x_cpu_cores
pgbouncer          --[recommended_mode]-----> transaction_pooling
```

So: with an LLM-wired consolidator producing typed SPO triples, pg-raggraph's bridge populates the full graph (chunks + entities + relationships). The extractive default's "chunks-only" mode is a deliberate fallback for zero-network deployments; for graph-aware retrieval you wire an LLM.

Smoke test source: `/tmp/test_pattern_m_llm.py` (not committed — same pattern as the chunks-side benches).

### Limitations and gaps (honest read)

| Gap | Where it shows | When it matters |
|---|---|---|
| ~~No per-fact temporal columns on `relationships`~~ **Closed in migration 006 (2026-05-20).** | `relationships` now has typed `effective_from` / `effective_to` / `retracted` / `retracted_at` columns; the bridge populates them from SP-A rows; `RelationshipResult` surfaces them. Ranking integration (e.g., demote `retracted=TRUE` edges in graph-mode scoring) is still a Tier 3 work item — the columns exist and are queryable but the default scorer does not yet use them. | Done for storage and read surface. Open: scoring weights that consume these columns. |
| **Sparse SPO triples are dropped from `relationships`** | chunkshop's extractive-default consolidator may emit `support_span`-only fact rows with null subject/predicate/object. The bridge keeps these as chunks (so vector retrieval still works) but skips the graph edge. | When the consolidation cell is wired to a real LLM that always produces full triples, this is a no-op. |
| **No fact-level retraction enforcement** | A `retracted=true` fact row still becomes a chunk and a relationship. The existing `retracted_behavior="hide"` config doesn't apply (that's document-level). | Filter out retracted fact rows in your SP-A SELECT (`WHERE NOT retracted`) until first-class fact retraction lands in pg-raggraph. |
| **Read-side latency overhead** | The `memory_tier` filter adds `WHERE c.metadata->>'tier' IS NULL OR c.metadata->>'tier' = $1` per query. Negligible at <100K chunks; benchmark for larger corpora. | Most agent-memory deployments are well under this scale; flagged for completeness. |

These are tracked as follow-ups; none block the Pattern M MVP shipping.

**References:**
- chunkshop SP-A design spec: [`docs/superpowers/specs/2026-05-19-chunkshop-memory-primitives-sp-a-design.md`](https://github.com/yonk-labs/chunkshop/blob/main/docs/superpowers/specs/2026-05-19-chunkshop-memory-primitives-sp-a-design.md)
- chunkshop agent-memory section: [`docs/incremental.md#agent-memory-sp-a`](https://github.com/yonk-labs/chunkshop/blob/main/docs/incremental.md#agent-memory-sp-a)
- pg-raggraph bridge module: [`src/pg_raggraph/memory_bridge.py`](../../src/pg_raggraph/memory_bridge.py)
- Backend note: SP-A's `agent_memory.memory` is Postgres-only by spec — the [§Backend compatibility](#backend-compatibility-chunkshop-04-is-multi-engine) multi-engine matrix doesn't apply to Pattern M.

## Choosing a pattern

| You want | Pick |
|---|---|
| Better chunking, minimal install, no extra moving pieces | **Pattern D** ⭐ |
| Better chunking + chunkshop's metadata extractors | Pattern C |
| Bridge chunkshop's agent-memory layer (SP-A) into the graph | **Pattern M** |
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
- **Hard-coupling.** chunkshop is on PyPI as `chunkshop>=0.4.3`. We pin the floor; you pin the version you want.
- **Replacing pg-raggraph's LLM extraction** with chunkshop's local extractors. Different roles: pg-raggraph's LLM extraction produces *typed entities and relationships* for the graph; chunkshop's extractors produce *flat keyword/entity lists* for filtering. They compose; they don't substitute.
