# pg-raggraph Benchmark Papers

A series of standalone benchmark papers, one per corpus. Each paper is self-contained: a reader who lands on an individual paper can understand the setup, reproduce the run, and cite the results without reading any of the others.

All papers use the same template (`_template.md`) and the same evaluation methodology (majority-of-3 LLM judge, shared answer model, shared embedding model family, seed-stable question subsets).

> **Status:** in progress. This index gets updated as papers land.

## Corpora

| Paper | Domain | N questions | Engines | Status |
|---|---|---|---|---|
| [SCOTUS](scotus.md) | U.S. Supreme Court cases | 30 | pgrg, AGE | ← carry-over from prior bake-off (to be re-issued under new template) |
| [Acme](acme.md) | Synthetic project updates | 30 | pgrg, AGE | ← carry-over |
| [GraphRAG-Bench medical](graphrag-bench-medical.md) | Medical/clinical | 100 (stratified) | pgrg, AGE, MS GraphRAG | planned |
| [GraphRAG-Bench novel](graphrag-bench-novel.md) | Long-form fiction | 100 (stratified) | pgrg, AGE, MS GraphRAG | planned |
| [MS Kevin Scott Podcast](ms-kevin-scott-podcast.md) | Conversational, sensemaking | ~50 | pgrg, AGE, MS GraphRAG | planned |
| [MS HotPotQA Filtered](ms-hotpotqa.md) | Multi-hop bridging | 100 (stratified) | pgrg, AGE, MS GraphRAG | planned |
| [MS MSFT Transcripts](ms-msft-transcripts.md) | Conversational (MSFT earnings etc) | ~all | pgrg, AGE, MS GraphRAG | planned |
| [pg-src](pg-src.md) | PostgreSQL C source (executor/planner) | 30+ | pgrg, AGE, MS GraphRAG | planned |

## Cross-corpus results matrix

> Populated as papers land. Columns are the same across all corpora; one glanceable view of "when do graph modes win."

| corpus | winning chunker | winning embedder | naive @ fully_correct | best pgrg graph mode | best engine overall |
|---|---|---|---|---|---|
| (filled as we go) | | | | | |

## Methodology — shared across papers

- **Answer model:** OpenAI `gpt-4.1-mini` (paid, cost tracked per paper).
- **Judge model:** OpenAI `gpt-4.1-mini`, 3 independent votes per question × engine × mode, majority wins.
- **Embedding model:** local fastembed. The chunker × embedder factorial per corpus selects a winner from `{sentence_aware, fixed_overlap, hierarchy, neighbor_expand}` × `{bge-small-fp32, bge-small-int8, nomic}`.
- **Question subsets:** stratified sample of 100 per corpus unless the upstream set is smaller. `seed=42` for all sampling. Full sample file shipped in-repo.
- **Chunking + embedding:** sourced via `chunkshop`, which produces a pgvector table consumed by the bakeoff.
- **Three engines:**
  - `pgrg` — this project.
  - `age` — Apache AGE reference implementation, same schema as prior bake-off.
  - `msgraph` — Microsoft's `graphrag` Python package, its own chunking + indexing, its own native modes.
- **Fairness caveat:** MS GraphRAG does its own chunking and indexing, so it's not strictly apples-to-apples with pgrg + AGE at the chunk level. Every paper documents this asymmetry explicitly in its Methodology section.

## See also

- [Template](_template.md) — the section structure every paper must follow.
- [graph-direction-decision.md](../graph-direction-decision.md) — T-G1 v1; will be revised (v2) after all 7 papers land.
- [GRAPH-AUGMENTATION-VERDICT.md](../../benchmarks/age-bakeoff/results/GRAPH-AUGMENTATION-VERDICT.md) — prior 2-corpus verdict this effort is stress-testing.
- [Mission brief](../../skill-output/mission-brief/Mission-Brief-multi-corpus-benchmarks.md) — scope, success criteria, drift checkpoints.
