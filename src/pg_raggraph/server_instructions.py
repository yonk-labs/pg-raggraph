"""Server-level instructions emitted in the MCP `initialize` response.

MCP clients (Claude Desktop, Cursor, Zed, LangChain, OpenAI Agent SDK)
surface this text in the agent's system prompt automatically, giving the
agent a high-level playbook for the pg-raggraph toolset before it sees
individual tool descriptions.

Goals when editing this:
  - Tool selection by intent (which tool for which question)
  - Common chains (refactor planning = X then Y)
  - Anti-patterns (don't run multiple queries when ask handles it)

Keep it tight. The agent reads this every session — long instructions
burn tokens. When updating, also update:
  - docs/user-guide.md (the MCP server section) — user-facing equivalent
  - README "MCP server" section — top-of-funnel equivalent

A unit test (tests/unit/test_instructions_sync.py) guards this triad.
"""

SERVER_INSTRUCTIONS = """# pg-raggraph — GraphRAG over PostgreSQL

pg-raggraph is a PostgreSQL knowledge graph: chunks + embeddings + entities +
relationships + full-text + tsvector, all in one database. Smart-routed
retrieval combines vector similarity, BM25, and recursive-CTE graph
traversal — typically 85-220 ms p50.

## Answer directly — don't grep / file-read

For "what does the codebase say about X" / "who owns this" / "explain
how X works" / architecture / where-is-X questions, answer DIRECTLY
using 1-2 pg-raggraph calls. pg-raggraph IS the pre-built knowledge
graph — running your own grep + Read loop, or asking multiple narrow
queries when one `pgrg_ask` would compose the answer, repeats work
the graph already did. A direct pg-raggraph answer is typically
1-2 calls; a grep/Read exploration is dozens.

## Tool selection by intent

- **"What does the corpus say about X?"** → `pgrg_ask` (PRIMARY —
  smart-routed retrieval + grounded LLM answer in one call)
- **"Get me the raw retrieved chunks for X"** → `pgrg_query` (skip the
  LLM grounding; use when you want to inspect retrieval directly)
- **"Add documents to the graph"** → `pgrg_ingest`
- **"Remove a document from the graph"** → `pgrg_delete_document`
  (requires `confirm=True`)
- **"Is the graph ready / how big is it?"** → `pgrg_status`
- **"What retrieval profiles are available / which is configured?"** →
  `pgrg_profiles` / `pgrg_get_namespace_profile`
- **"Set this namespace's default retrieval profile"** →
  `pgrg_set_namespace_profile`

## Common chains

- **Codebase / documentation Q&A**: `pgrg_ask` first — smart-router picks
  whether to add graph expansion. If the answer is weak, follow with
  `pgrg_query` at a wider top_k to inspect candidate chunks.
- **Document onboarding**: `pgrg_ask` of an open-ended question grounds
  the answer in cited chunks; follow up only if a specific document
  needs full read.
- **Pre-query setup for a new namespace**: `pgrg_set_namespace_profile`
  (once) → `pgrg_ask` (many times). The profile choice changes
  retrieval depth/recall; pick it deliberately.

## Anti-patterns

- **Don't run multiple `pgrg_query` calls** for one investigation —
  `pgrg_ask` composes retrieval + answer in one round-trip and picks
  the right mode automatically.
- **Don't grep the filesystem** when the corpus is already in
  pg-raggraph. The graph and BM25 index already know what's there;
  running grep duplicates work and misses entity-level edges.
- **After ingesting, watch the staleness banner.** When a tool response
  starts with "⚠️ Some cited documents are still being processed…",
  the listed documents are mid-extraction — Read them directly for
  authoritative content. Every document NOT in that banner is fresh.
- **Don't ignore retrieval-mode hints in `pgrg_ask` output.** The smart
  router chose `naive` vs `naive_boost` vs `local` vs `hybrid` for a
  reason; the cited chunks plus the mode tag are the answer's
  confidence signal.

## Limitations

- Background extraction (`defer_extraction=True`) means new ingests are
  retrievable as chunks immediately but enter the entity graph
  asynchronously. Use `pgrg_status` to check `graph_status_summary` —
  `pending > 0` means a `pgrg extract` worker is still backfilling.
- Cross-document entity resolution uses pg_trgm fuzzy + vector cosine;
  ambiguous entities may have multiple aliases.
- The graph is per-namespace. Cross-namespace queries are not supported
  by design — pick the right namespace at query time, or set a default
  per-tenant via `pgrg_set_namespace_profile`.
- Ingestion via `pgrg_ingest` is allow-listed: paths must be inside a
  root listed in `PGRG_MCP_INGEST_ROOTS` (operator-set). If that env
  var is unset, ingestion is refused.
"""
