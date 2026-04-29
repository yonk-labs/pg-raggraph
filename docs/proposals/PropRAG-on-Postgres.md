# Proposal: PropRAG-on-Postgres

> **Status:** Draft (2026-04-29). Forward-looking design — not yet committed for execution. Awaiting MuSiQue baseline numbers before Phase A starts.

## TL;DR

Port the two ideas behind PropRAG (current zero-shot SOTA on MuSiQue: ~54 F1 / 77.3% Recall@5) into pg-raggraph using only existing Postgres primitives — no Neo4j, no Apache AGE, no PL/Python required. Two ideas, three phases:

1. **Propositions** — extract context-rich natural-language statements during ingest, alongside or in place of (subject, predicate, object) triples. Avoids "context collapse." New tables: `propositions` + `proposition_entities` (junction). Phase A.
2. **Personalized PageRank (PPR)** — replace 1-hop graph re-rank (`naive_boost`) and recursive-CTE traversal (`local`/`global`) with a principled global score computed via scipy sparse matvec. Two-stage damping for explore→exploit. Phase B.
3. **PPR over proposition cliques** — combine #1 and #2: PPR runs on the entity adjacency *induced by* `proposition_entities`, where every two entities co-occurring in any proposition are 1 hop apart. Phase C.

This positions pg-raggraph as the reference implementation of PropRAG's central claim — that graph-based RAG doesn't need a graph database, only a vector store + a junction table + sparse linear algebra. Same Postgres-native single-database story we already have, with measurably stronger multi-hop performance.

Beam search over proposition paths (the smaller of PropRAG's two algorithmic ideas) is deferred — high implementation complexity, marginal F1 vs Phase A+B+C.

## Why this matters now

Three independent reasons line up.

**Benchmark positioning.** Our running MuSiQue numbers will land somewhere on the table the user shared today. Best-case current architecture is mid-40s F1 (comparable to NV-Embed-v2 / HippoRAG v1). PropRAG sits at ~54. The 9-point gap is real and traceable to two specific algorithmic ideas, both of which fit our schema.

**Strategic positioning.** PropRAG's paper effectively argues the same thesis pg-raggraph has been arguing: graph databases are unnecessary, the graph is "structural sugar over a relational + vector workload." If we ship PropRAG-on-Postgres, we own the most credible implementation of that thesis. The blog post writes itself: *"Why your GraphRAG doesn't need a graph database."*

**Architectural fit.** The two new tables (`propositions`, `proposition_entities`) extend our existing schema cleanly. PPR over our existing `relationships` table is ~80 LOC of Python. Neither requires a new dependency or a deployment-shape change.

## The thesis we're proving

> Graph-augmented RAG can be implemented end-to-end inside a single PostgreSQL instance using only `pgvector` + adjacency tables + scipy. No graph database, no Cypher, no special extensions. The lift over pure-vector retrieval comes from two algorithmic ideas — propositions and PPR — that are independent of any storage substrate.

The benchmark target is MuSiQue — same dev split we're indexing right now (1700 paragraphs from 100 stratified questions). Our current run gives the floor; the PropRAG-on-Postgres branch raises that floor toward the ~54 F1 SOTA.

## Architecture

### Schema additions

Two new tables. Both follow our existing conventions: namespace-aware, JSONB metadata, embeddings inline, HNSW index for cosine.

```sql
-- propositions: context-rich natural-language statements extracted from chunks
CREATE TABLE propositions (
    id BIGSERIAL PRIMARY KEY,
    namespace TEXT NOT NULL,
    document_id BIGINT REFERENCES documents(id) ON DELETE CASCADE,
    chunk_id BIGINT REFERENCES chunks(id) ON DELETE CASCADE,
    text TEXT NOT NULL,
    embedding vector(384),  -- match config.embedding_dim
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_prop_embed ON propositions USING hnsw (embedding vector_cosine_ops);
CREATE INDEX idx_prop_namespace ON propositions(namespace);
CREATE INDEX idx_prop_doc ON propositions(document_id);
CREATE INDEX idx_prop_chunk ON propositions(chunk_id);

-- proposition_entities: junction table; co-occurrence cliques are implicit
CREATE TABLE proposition_entities (
    proposition_id BIGINT REFERENCES propositions(id) ON DELETE CASCADE,
    entity_id BIGINT REFERENCES entities(id) ON DELETE CASCADE,
    PRIMARY KEY (proposition_id, entity_id)
);
CREATE INDEX idx_pe_entity ON proposition_entities(entity_id);
```

The "hyper-edges" PropRAG draws as shaded ovals fall out of `proposition_entities` automatically: any two entities sharing any proposition are 1 hop apart through that proposition. We materialize the cliques on demand in scipy, not in storage.

Migration: `005_propositions.sql` (new file under `src/pg_raggraph/sql/migrations/`).

### Extraction pipeline changes

Today `extraction.py` calls the LLM with one prompt that returns entities + relationships. We add a parallel ask for propositions.

Two design choices to evaluate during Phase A:

- **Option A — single merged prompt** that returns `{entities, relationships, propositions}`. Cheaper (one LLM call per chunk), harder to tune. Format and quality of each artifact may regress relative to today's tuned entity/rel prompt.
- **Option B — two prompts** in parallel via the existing extraction semaphore. Doubles LLM calls per chunk but keeps each prompt focused. Better controlled rollout.

Recommendation: **start with Option B for clarity**, optimize to Option A if cost becomes a problem. Our existing `extract_concurrency` semaphore already amortizes parallel LLM calls.

Proposition extraction prompt (sketch):

```
Extract propositions from the following text. A proposition is a single
context-rich natural-language statement that:
  - Asserts ONE complete fact
  - Names every entity it references explicitly (no anaphora)
  - Preserves temporal and modal qualifiers ("until 1952", "as of 2020")
  - Is shorter than the source paragraph but richer than a triple

Return JSON: {"propositions": [{"text": "...", "entities": ["Name1", "Name2"]}]}

Example input:  "Marchese Camillo Serafini was born in Rome and held the
                 post of Governor of Vatican City until his death in 1952."
Example output: {"propositions": [
  {"text": "Marchese Camillo Serafini was born in Rome.",
   "entities": ["Marchese Camillo Serafini", "Rome"]},
  {"text": "Marchese Camillo Serafini held the post of Governor of Vatican
            City until his death in 1952.",
   "entities": ["Marchese Camillo Serafini", "Governor of Vatican City", "1952"]}
]}
```

After extraction, the resolution step matches each proposition's entity names to existing `entities` rows (same path entities use today via `resolve_entity()`), then writes the `proposition_entities` linkage.

### Retrieval pipeline changes

Two new modes; existing modes untouched.

**`prop` (Phase A baseline)** — vector similarity over the `propositions` table, then surface the chunks that contain the top-k propositions. Comparable to "retrieval over propositions" without PPR. Lets us isolate the lift from chunking-as-propositions vs. PPR.

**`prop_ppr` (Phase C)** — PropRAG's full pipeline:
1. Vector similarity over `propositions` to identify seed propositions.
2. Build entity adjacency from `proposition_entities` clique: cache a CSR sparse matrix per namespace.
3. **Stage 1 (explore):** PPR with damping=0.75, seeded by entities of the top propositions. Yields a candidate subgraph of ~50 propositions / chunks.
4. **Stage 2 (exploit):** PPR with damping=0.45 over the reduced subgraph, seeded by the top output of stage 1. Yields the final top-k.
5. Return chunks containing the surfaced propositions.

Both modes are pure SQL + numpy. No LLM calls at retrieval time — same as our existing modes.

### Where PPR runs

scipy in Python, inside `retrieval.py`. The adjacency matrix is built from a single SQL query per namespace and cached.

Pseudocode sketch:

```python
async def _ppr_score(seeds, namespace, damping=0.5, n_iter=20):
    A = await _adjacency_csr(namespace)        # cached
    n = A.shape[0]
    s = np.zeros(n); s[seed_indices] = 1.0
    s /= s.sum()
    x = s.copy()
    for _ in range(n_iter):
        x = damping * (A @ x) + (1 - damping) * s
    return x
```

Adjacency cache: invalidate on namespace mutation (`ingest`/`delete`). Initial implementation can rebuild on every query — at 10K-100K entities the rebuild is sub-100ms on a localhost connection.

### API surface

Minimal user-visible changes:

- `rag.query(question, mode="prop")` — new mode value
- `rag.query(question, mode="prop_ppr")` — new mode value
- `GraphRAG(extract_propositions=True, ...)` — opt-in config flag for ingest
- CLI: `pgrg ingest --extract-propositions`, `pgrg query --mode prop_ppr`

Backwards compatible. Existing modes (`naive`, `naive_boost`, `local`, `global`, `hybrid`, `smart`) keep their current behavior.

## Phase plan

Each phase produces a working, testable end-to-end change. None depends on the next.

### Phase A — Propositions (1 week effort)

**Scope.** Schema, migration, extraction prompt, resolution path, basic retrieval mode.

**Tasks.**
- New migration `005_propositions.sql`.
- New `extract_propositions()` in `extraction.py` (Option B: separate prompt).
- Resolution step writes `proposition_entities` rows.
- New retrieval mode `prop` (vector similarity over propositions → return parent chunks).
- Unit tests for prompt parsing and linkage.
- Integration test: ingest 10 docs with propositions, verify counts and linkage.
- Re-run MuSiQue with `--mode prop` (alongside existing modes).

**Definition of done.**
- 1700 MuSiQue paragraphs ingested with propositions; `propositions` and `proposition_entities` populated.
- No regression on existing modes' retrieval times or accuracy.
- `prop` mode F1 measurable on MuSiQue.
- PR includes before/after F1 numbers.

### Phase B — PPR (1 week effort)

**Scope.** Standalone PPR re-ranking layer over existing `entities` + `relationships`. Independent of Phase A.

**Tasks.**
- `_adjacency_csr(namespace)` cache builder (scipy CSR from `relationships`).
- `_ppr_score(seeds, namespace, damping)` core loop.
- New retrieval mode `local_ppr` (or augment `local`/`naive_boost` via flag).
- Two-stage variant: `local_ppr_2stage` with the 0.75/0.45 damping swap.
- Unit tests with a hand-built tiny adjacency.
- Re-run MuSiQue with both single-stage and two-stage PPR.

**Definition of done.**
- PPR runs end-to-end in <500ms for namespaces up to 100K entities.
- MuSiQue F1 lift over `local`/`naive_boost` measured.
- Adjacency cache invalidation on `ingest`/`delete` works.

### Phase C — PPR over proposition cliques (1 week effort)

**Scope.** Combine A and B. PPR's adjacency comes from `proposition_entities` cliques, not `relationships`.

**Tasks.**
- `_adjacency_from_propositions_csr(namespace)` — clique expansion via SQL or Python.
- New retrieval mode `prop_ppr` using the proposition-derived adjacency.
- Two-stage damping enabled by default in this mode.
- Re-run MuSiQue.

**Definition of done.**
- `prop_ppr` mode operational.
- Documented MuSiQue F1 ≥45 (target) / ≥50 (stretch) on our 100-question stratified set.
- `prop_ppr` becomes the recommended mode for multi-hop questions in the user-guide.

### Phase D — Beam search (deferred)

Only attempted if A+B+C don't close the gap to ~54 F1.

**Why deferred.** Beam search adds materially more complexity (path representation, candidate scoring against running-context embeddings, beam pruning) for what the PropRAG paper itself reports as a smaller delta than PPR. Better to land Phase C, measure, and decide.

## Success criteria

Phase-by-phase F1 targets on MuSiQue (n=100 stratified, current corpus):

| Phase | Mode | Target F1 | Stretch | Reasoning |
|---|---|---|---|---|
| baseline | `naive` | (measured) | — | Vector + BM25 floor |
| A | `prop` | ≥ baseline + 3 pp | +5 pp | Propositions as richer retrieval target |
| B | `local_ppr_2stage` | ≥ baseline + 5 pp | +8 pp | PPR over `relationships` |
| C | `prop_ppr` | ≥ 45 | ≥ 50 | A + B combined |
| D | `prop_ppr_beam` | ≥ 52 | ≥ 54 | Only if C falls short |

If we exit Phase C at ≥50, the project ships and Phase D becomes optional (good blog material, not core thesis).

If `naive` baseline lands lower than expected (say <35), the embedder is the bottleneck before any of this matters. Fallback: try a stronger embedder (NV-Embed-v2 or similar via fastembed) before continuing — that's a Phase A-prime, not part of this proposal.

## Risks

**R1 — Extraction LLM cost doubles** with two prompts per chunk. Mitigation: existing semaphore handles parallelism; if cost spirals, switch to merged prompt (Option A). For our MuSiQue corpus (1700 paragraphs), the cost is bounded.

**R2 — PPR adjacency rebuild slow on large corpora.** Mitigation: cache aggressively, invalidate only on mutations. For >1M entities, consider materializing CSR as a `BYTEA` blob in `pgrg_meta`. Won't bite us at MuSiQue scale.

**R3 — Embedder ceiling.** If bge-small-en-v1.5 is the actual bottleneck, even perfect propositions + PPR may cap at ~45-48 F1. Mitigation: phase A-prime evaluates a swap to a stronger fastembed-supported embedder. Decoupled from PropRAG mechanics.

**R4 — Cache coherence in multi-process deployment.** scipy adjacency cached in Python process won't be shared across workers. Mitigation: re-derive at startup (cheap), or persist CSR in `pgrg_meta`. Defer; not a v1 concern.

**R5 — Proposition extraction quality varies by domain.** PropRAG paper validates on Wikipedia-like corpora. May regress on highly structured docs (legal, medical, code). Mitigation: track per-domain F1; keep a per-corpus prompt option.

**R6 — `evolution_tier` interaction.** Tier 1 features (versioning, retraction) are orthogonal to retrieval mechanics, but propositions don't currently carry `effective_from` / `retracted_at` columns. Mitigation: add those columns in the migration if Tier 1 awareness is wanted; otherwise document that propositions inherit the parent chunk's evolution metadata.

## What we deliberately don't build

- **No graph database extension** (Apache AGE, no Neo4j sidecar). PropRAG paper itself confirms the operations are linear algebra; storage stays Postgres-native.
- **No PL/Python on the server.** Adjacency lives in client-side numpy. Postgres only does the SQL pulls.
- **No new embedding model in this proposal.** Stays bge-small-en-v1.5 unless R3 forces a separate phase.
- **No beam search in v1.** Phase D, only if needed.
- **No new query language or DSL.** Same `rag.query(question, mode=...)` API.
- **No materialized cliques in storage.** Cliques are implicit in `proposition_entities`, expanded on demand.
- **No incremental PPR.** Recompute on each query (cheap at our scale). Streaming PPR is a research problem we don't need.

## Open questions

1. **Single merged extraction prompt or two prompts?** Affects ingest cost and prompt tunability. Decision in Phase A based on early A/B comparison.
2. **PPR cache strategy** — Python-process-local vs persisted in `pgrg_meta`? Decision in Phase B based on scale needs.
3. **Should `prop_ppr` become a tier of `smart` mode?** I.e., should `smart` route multi-hop-looking questions to `prop_ppr` automatically? Decision after Phase C, when we have F1 numbers per question type.
4. **Tier 1 evolution awareness** — propositions inherit chunk evolution metadata, or carry their own? Decision in Phase A schema.
5. **Embedder swap in scope?** If our `naive` floor is much lower than NV-Embed-v2, do we treat embedder upgrade as a prerequisite? Decision after current MuSiQue baseline lands.

## Out of scope for this proposal

- Re-architecting `extraction.py` beyond adding the proposition path
- Changing existing modes (`naive`, `local`, `global`, `hybrid`, `smart`)
- Replacing pgvector with a different vector backend
- Replacing FastEmbed with a different embedder (separate decision per R3)
- Adding new corpora to benchmarks beyond what already exists (MuSiQue + SCOTUS + NTSB + medical-hrt + python-versioned-docs + pg-agents)
- Re-running the SCOTUS bake-off — orthogonal; AGE comparison is a settled question

## What lands when this is done

A `prop_ppr` mode in pg-raggraph that beats every public number on MuSiQue except PropRAG's own (and gets within striking distance of it), plus a blog post and reproducible benchmark showing the result was implemented entirely on Postgres with no graph database, no special extensions, and no LLM at retrieval time.

The blog narrative aligns perfectly with our existing positioning: *"Use the database you have. The graph is sugar over relational + vector. Here's the proof, on the same Postgres your application is already running on."*

## References

- **PropRAG (ACL 2025).** Original paper introducing propositions and beam-search PPR. Current zero-shot SOTA on MuSiQue at ~54 F1 / 77.3% Recall@5.
- **HippoRAG 2 (NeurIPS 2024).** KG triples + PPR + filtering. 51.9 F1 on MuSiQue.
- **HippoRAG (NeurIPS 2024 v1).** Original neurally-inspired PPR over OpenIE triples. ~46 F1.
- **MuSiQue (Trivedi et al. 2022).** The benchmark itself. 2-4 hop multi-hop QA over Wikipedia.
- **pgvector.** Already a dependency. HNSW + cosine ops cover the embedding side.
- **scipy.sparse.** Already in the dependency tree (transitively, via fastembed numpy stack). CSR matvec for PPR.
- **`research/apache-age-evaluation.md`** — our existing argument for why graph databases are unnecessary. PropRAG-on-Postgres is the experimental confirmation.
