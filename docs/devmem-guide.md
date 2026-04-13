# pg-raggraph devmem — Developer Knowledge Base

> Turn your code, docs, incidents, ADRs, and git history into a queryable knowledge graph.

`pgrg devmem` is a subcommand with engineering-tuned defaults:
- **Dev extraction prompt** that knows about `person`, `service`, `library`, `file`, `commit`, `incident`, `ticket`, `adr` entity types
- **Code-aware chunking** that splits Python/JS/TS/Go/Rust files on function/class boundaries
- **Git metadata** capture (commit, author, date) as chunk metadata
- **Smart mode by default** for queries — fast on easy questions, graph-aware on hard ones
- **`devmem` namespace** for isolation from other pg-raggraph data

## Quick Start

```bash
# 1. Initialize
pgrg devmem init

# 2. Ingest your repo
pgrg devmem ingest ./my-monorepo/

# 3. Ask questions
pgrg devmem ask "who owns the auth service?"
pgrg devmem ask "why did we add Redis caching?"
pgrg devmem ask "what incidents are related to the payment service?"

# 4. Check status
pgrg devmem status
```

## What devmem Ingests

The default ingestion walks the provided paths and picks up these file types:
- **Markdown** (`.md`) — README, docs, ADRs, runbooks (heading-aware chunking)
- **Python** (`.py`) — split on `def`/`class` boundaries
- **JavaScript/TypeScript** (`.js`, `.ts`, `.tsx`, `.jsx`) — split on function/class/const
- **Go** (`.go`) — split on `func` boundaries
- **Rust** (`.rs`) — split on `fn`/`struct`/`impl`/`trait`
- **Plain text** (`.txt`) — sentence-aware chunking

Each file becomes 1+ chunks. The LLM extracts:
- **People** mentioned (authors, owners, reviewers)
- **Services** (microservices, APIs)
- **Libraries** and dependencies
- **Files** referenced
- **Commits** and PR numbers
- **Incidents** (INC-NNN) and tickets (JIRA-NNN)
- **ADRs** (architecture decisions)

And relationships between them: `OWNS`, `DEPENDS_ON`, `TOUCHED`, `CAUSED`, `FIXED_BY`, `REFERENCES`, `PART_OF`, `DEPLOYED_TO`, etc.

## Example Queries

Queries that naive vector search alone would miss:

```bash
# Multi-hop: who wrote the code that caused the memory leak incident?
pgrg devmem ask "who wrote the code that caused INC-2024-102?"

# Cross-doc reasoning: which services depend on the library we're deprecating?
pgrg devmem ask "what services use the deprecated aws-sdk v2 library?"

# Impact analysis: if I change the auth service API, who's affected?
pgrg devmem ask "which services call the auth service login endpoint?"

# Historical context: why was this decision made?
pgrg devmem ask "why did we choose JWT over sessions?"

# Root-cause analysis across incidents
pgrg devmem ask "what incidents were caused by rate limiting changes?"
```

## Configuration

All standard pg-raggraph config applies (PGRG_DSN, PGRG_LLM_*, etc.). Devmem-specific:

```bash
# Use a non-default namespace (e.g., per-repo or per-team)
pgrg devmem ingest ./my-repo/ -n team-backend

# Gentler ingestion for shared dev machines
pgrg devmem ingest ./my-repo/ -p conservative

# Aggressive for dedicated machines
pgrg devmem ingest ./my-repo/ -p aggressive
```

## Query Modes

Devmem's `ask` command uses `smart` mode by default (adaptive routing). Override if needed:

```bash
pgrg devmem ask "question" -m naive        # fastest
pgrg devmem ask "question" -m naive_boost  # naive + cheap graph re-rank
pgrg devmem ask "question" -m smart        # default, adaptive
pgrg devmem ask "question" -m hybrid       # most context, slowest
```

## Tips for Best Results

1. **Ingest incrementally.** Re-running `pgrg devmem ingest` on the same repo is safe — content hashes prevent re-processing unchanged files.

2. **Include non-code docs.** Ingest `./docs/`, `./adr/`, your wiki export, and old incident postmortems alongside code. The graph becomes much more valuable with cross-source entity connections.

3. **Per-team namespaces.** If you have multiple teams/products, use `-n team-x` to keep their knowledge graphs separate.

4. **Use `-v` for progress.** Large repos take a few minutes to ingest. The verbose flag shows per-file progress.

5. **Smart mode is the right default.** It's faster than hybrid on easy questions and as accurate on hard ones. Only switch to other modes for experimentation.

## What's Different from Plain `pgrg query`?

| Feature | `pgrg query` | `pgrg devmem ask` |
|---------|-------------|-------------------|
| Namespace | `default` | `devmem` |
| Extraction prompt | generic | dev-tuned (person, service, etc.) |
| Default mode | `smart` | `smart` |
| Chunking | markdown-aware | markdown + code-aware |
| Git metadata | no | yes (when in a git repo) |

You can use plain `pgrg query` on a devmem namespace, or use `pgrg devmem ask` with a different namespace. The commands are interchangeable — devmem is just a convenience wrapper with better defaults for engineering content.
