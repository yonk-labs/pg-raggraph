# pg-raggraph — Configuration Reference

> ⚠️ **About the default embedder.** Every benchmark number in this repo (MuSiQue, NTSB, SCOTUS, PG-docs, pg-agents, medical-HRT) is generated with the default `embedding_model = "BAAI/bge-small-en-v1.5"` — a 384-dimensional, ~33 MB CPU-friendly model. **Stronger embedders (bge-large-en-v1.5 at 1024-dim, NV-Embed-v2 at 4096-dim, OpenAI text-embedding-3-large at 3072-dim) materially raise the retrieval ceiling.** Public papers consistently show +5-10 pp F1 / +10-15 pp Recall@5 from a stronger embedder on the same corpus. The default is conservative (free, fast, airgap-safe); any production deployment that cares about retrieval quality on hard queries should evaluate a larger embedder. See `embedding_model` below + the "Phase A-prime" decision branch in [`proposals/Accuracy-Improvements-Roadmap.md`](proposals/Accuracy-Improvements-Roadmap.md).

Canonical reference for every tunable setting. Each entry follows the same 6-field shape:

```
### `field_name` (type, default: `value`)
Env var: `PGRG_FIELD_NAME`

What: one-sentence behavior description.
Pros: what you gain when raised / lowered.
Cons: what you give up.
When to use: concrete scenario where the non-default is right.
When NOT to use: concrete scenario where the non-default is wrong.
```

**Two equally valid ways to set any config:**

```python
# Constructor kwargs
rag = GraphRAG(dsn=..., top_k=20, rerank_model="BAAI/bge-reranker-base")

# Environment variables (every field gets a PGRG_ prefix)
PGRG_TOP_K=20 PGRG_RERANK_MODEL=BAAI/bge-reranker-base python my_app.py
```

The default ships are conservative: zero added per-query LLM cost, sub-second p50 latency on a 1700-paragraph corpus, no behavior changes vs verbose paragraph answers, no graph mode that surprises you. Every accuracy-improving feature (rerank, short_answer, evolution tiers) is opt-in. **Flip a knob only when you have a specific reason.**

---

## Connection

### `dsn` (str, default: `postgresql://postgres:postgres@localhost:5434/pg_raggraph`)
Env var: `PGRG_DSN`

What: PostgreSQL connection string.
Pros: standard libpq URI; supports SSL params, `application_name`, etc.
Cons: defaults use well-known credentials — fine for local dev, NOT for shared envs.
When to use: always (override the default for any non-local deployment).
When NOT to use: never. Always set explicitly outside `localhost`.

### `pool_min` (int, default: `2`)
Env var: `PGRG_POOL_MIN`

What: minimum number of warm DB connections held open.
Pros: lower means smaller idle footprint; raise to absorb burst load without checkout latency.
Cons: too low = first query of a quiet period pays connection-establish cost.
When to use: raise to 5-10 in latency-sensitive prod APIs serving steady traffic.
When NOT to use: raise above pool_max; never raise above your DB's `max_connections` budget.

### `pool_max` (int, default: `10`)
Env var: `PGRG_POOL_MAX`

What: maximum number of concurrent DB connections this client will open.
Pros: higher absorbs concurrent ingest + query workloads.
Cons: too high starves other apps sharing the database; can exhaust `max_connections`.
When to use: raise for high-concurrency ingest (`doc_concurrency` > 4) or many parallel queries.
When NOT to use: never raise past 25-30% of the database's `max_connections` setting.

### `namespace` (str, default: `default`)
Env var: `PGRG_NAMESPACE`

What: logical separation of corpora within a single database. Every document, chunk, entity, and relationship is namespace-scoped.
Pros: multi-tenant isolation, separate corpora share embeddings/extensions but not data.
Cons: cross-namespace queries are not supported; pick the right scope at ingest time.
When to use: per-customer isolation, per-corpus benchmarks, per-environment partitioning.
When NOT to use: as a substitute for proper schema/database separation when tenants are untrusted.

---

## Embeddings

### `embedding_dim` (int, default: `384`)
Env var: `PGRG_EMBEDDING_DIM`

What: dimensionality of the vector column. Must match `embedding_model`'s output.
Pros: smaller dim = less storage, faster HNSW search.
Cons: setting doesn't truncate or transform — must match model exactly or you'll get insert failures.
When to use: change in lockstep with `embedding_model`. e.g., set to 1024 for `bge-large-en-v1.5`.
When NOT to use: never change in isolation; never change after data is ingested without a re-embed plan.

Changing the dimension on a database that already has data: use the online expand/contract migration — `pgrg migrate-embeddings prepare/backfill/build-index/cutover/finalize` — which re-embeds into a second column while the app keeps serving, then swaps it in during a brief lock. No parallel database, no full downtime. A startup guard refuses to connect if `embedding_dim` no longer matches the live column, so a forgotten config change fails fast with a clear message. See [`cookbook/changing-embedding-dimensions.md`](cookbook/changing-embedding-dimensions.md).

### `embedding_model` (str, default: `BAAI/bge-small-en-v1.5`)
Env var: `PGRG_EMBEDDING_MODEL`

What: the model used to embed chunks and entities at ingest time. **This is the single biggest lever on retrieval quality** — a stronger embedder shifts every other accuracy metric.

Default is conservative: 384-dim, ~33 MB, CPU-only via fastembed, airgap-safe, free. It's fast and good enough for most queries; it is NOT optimal.

Per public benchmark literature on multi-hop QA (MuSiQue, HotpotQA), upgrading the embedder typically buys:
- **+5-10 pp F1** on retrieval-bound questions
- **+10-15 pp Recall@5**
- Most of this gain shows up on paraphrased, vocabulary-mismatched, or rare-entity queries

Reasonable alternatives:

| Model | Dims | Size | Cost | Lift estimate |
|---|---|---|---|---|
| BAAI/bge-small-en-v1.5 (default) | 384 | 33 MB | free | baseline |
| BAAI/bge-base-en-v1.5 | 768 | 110 MB | free | +2-4 pp F1 |
| BAAI/bge-large-en-v1.5 | 1024 | 1.3 GB | free | +5-8 pp F1 |
| NV-Embed-v2 | 4096 | ~16 GB | free (huge) | +8-10 pp F1 (SOTA on MTEB) |
| OpenAI text-embedding-3-small | 1536 | API | ~$0.02/M tokens | +4-6 pp F1 |
| OpenAI text-embedding-3-large | 3072 | API | ~$0.13/M tokens | +6-9 pp F1 |

Pros (raise embedder size): higher retrieval recall, better paraphrase handling, smaller gap to published SOTA.
Cons (raise embedder size): bigger ingest time + memory; a different `embedding_dim` means re-embedding — do it online with `pgrg migrate-embeddings` (no parallel DB, brief cutover; see [`cookbook/changing-embedding-dimensions.md`](cookbook/changing-embedding-dimensions.md)) or via a full re-ingest; OpenAI variants leak data + add per-token cost.
When to use: every benchmark number you read in this repo is bge-small-bounded — if your retrieval ceiling matters in production, run a paired ingest with bge-large or NV-Embed-v2 and remeasure.
When NOT to use: OpenAI embedders for any data sensitivity / airgap requirement.

### `embedding_provider` (`"local" | "openai" | "ollama"`, default: `local`)
Env var: `PGRG_EMBEDDING_PROVIDER`

What: where embeddings are computed. `local` = fastembed (CPU/GPU), `openai` = paid API, `ollama` = local server.
Pros: `local` is free + airgap-safe. `openai` outsources the model-management problem. `ollama` lets you run larger embedding models on a separate GPU box.
Cons: `openai` adds per-token cost and per-request latency. `ollama` requires running a sidecar.
When to use: `openai` only if you've already standardized on their stack and don't mind paying per ingest.
When NOT to use: `openai` for any data sensitivity / cost-sensitive workload; `local` is the right default.

---

## LLM (extraction + answer generation)

### `llm_base_url` (str, default: `http://localhost:11434/v1`)
Env var: `PGRG_LLM_BASE_URL`

What: OpenAI-compatible API endpoint for entity extraction at ingest and answer synthesis at query (`rag.ask`).
Pros: any OpenAI-compatible server works (Ollama, vLLM, llama.cpp server, OpenAI proper).
Cons: must serve a chat-completions endpoint; non-OpenAI APIs need a translation layer.
When to use: point at vLLM for fast local Qwen/Llama, or OpenAI for top-quality extraction.
When NOT to use: the Ollama default is conservative — only keep it if you're literally running Ollama on the same box.

### `llm_model` (str, default: `llama3.2`)
Env var: `PGRG_LLM_MODEL`

What: model identifier passed to the LLM endpoint.
Pros: bigger models extract higher-quality entities and relationships at ingest.
Cons: bigger model = more cost (per-call for paid APIs) or slower (for local).
When to use: `gpt-4o-mini` or `gpt-5-mini` for top extraction quality. `Qwen3-Coder-Next-int4` for cheap local.
When NOT to use: changing without re-ingesting if you care about a consistent graph quality across the corpus.

### `llm_api_key` (str, default: `""`)
Env var: `PGRG_LLM_API_KEY` (or `OPENAI_API_KEY` for OpenAI endpoints)

What: bearer token for the LLM endpoint.
Pros: required for paid APIs; ignored by local Ollama/vLLM.
Cons: passing via constructor literal leaks into stack traces. Prefer env var.
When to use: any non-local LLM endpoint.
When NOT to use: never hardcode in source. Use env vars or a secret manager.

### `extraction_prompt` (`"default" | "dev"`, default: `default`)
Env var: `PGRG_EXTRACTION_PROMPT`

What: which entity-extraction prompt to use at ingest. `default` is general-purpose; `dev` is tuned for developer corpora (people, services, libraries, files, commits, incidents, ADRs).
Pros: `dev` produces meaningfully better entities + relationships on dev knowledge bases.
Cons: `dev` over-extracts on non-dev corpora (medical, legal).
When to use: `dev` for codebases, runbooks, on-call docs, ADR collections.
When NOT to use: `dev` for general-knowledge corpora — use `default`.

### `skip_extraction` (bool, default: `False`)
Env var: `PGRG_SKIP_EXTRACTION`

What: ingest documents but skip the LLM-based entity/relationship extraction step.
Pros: 10-100× faster ingest; useful for vector-only RAG.
Cons: graph modes (`local`, `global`, `hybrid`, `naive_boost`) won't help — there's no graph to traverse.
When to use: pure vector search workloads where you'll never need graph mode.
When NOT to use: any workload that might benefit from cross-document entity chains.

---

## Chunking

### `chunk_strategy` (str, default: `auto`)
Env var: `PGRG_CHUNK_STRATEGY`

What: how to split documents into chunks. Built-in values: `auto` (detect markdown / code / text and pick the right splitter), `hierarchy` (heading-prefixed chunks). Plus chunkshop pass-through values when the optional dep is installed: `chunkshop:hierarchy`, `chunkshop:sentence_aware`, `chunkshop:semantic`, `chunkshop:fixed_overlap`, `chunkshop:neighbor_expand`, `chunkshop:code_aware`, `chunkshop:symbol_aware` — see [`cookbook/chunkshop-integration.md`](cookbook/chunkshop-integration.md).
Pros: `auto` is good across most corpora. `hierarchy` improves retrieval when titles disambiguate similar content. `chunkshop:*` strategies are the recommended chunkers for markdown-shaped, sentence-rich, or source-code corpora — chunkshop's hierarchy and symbol-aware chunkers carry richer `embedded_content` and metadata than pg-raggraph's built-in splitter.
Cons: `chunkshop:*` requires the `chunkshop` optional dep (`pip install 'pg-raggraph[chunkshop]'`); without it pg-raggraph errors with an install hint when you set the strategy. `chunkshop:semantic` loads a sentence-transformer for boundary detection. `chunkshop:code_aware` and `chunkshop:symbol_aware` require a Chunkshop build that includes those 0.6 chunker config classes; `symbol_aware` works best with Chunkshop's tree-sitter code extra installed.
When to use: `chunkshop:hierarchy` as the upgrade path from `auto` for structured corpora. `chunkshop:sentence_aware` for prose without strong heading structure. `chunkshop:semantic` for long-form content where topic-shift detection matters and the extra runtime cost is worth it. `chunkshop:symbol_aware` for multi-language code repositories where FQN, line range, and symbol metadata should travel with chunks.
When NOT to use: any `chunkshop:*` strategy if you don't want the extra dependency. The built-in `auto`/`hierarchy` are perfectly serviceable.

### `chunk_max_tokens` (int, default: `512`)
Env var: `PGRG_CHUNK_MAX_TOKENS`

What: maximum tokens per chunk before a hard split.
Pros: smaller chunks = more precise retrieval, less context dilution. Larger chunks = fewer LLM calls at ingest.
Cons: too small (<200) loses context; too large (>1000) overflows LLM context windows on many extractor models.
When to use: 256 for question-answering on dense factual content; 768 for summarization-heavy workloads.
When NOT to use: change without considering the matching `embedding_model`'s context window.

### `chunk_overlap_tokens` (int, default: `50`)
Env var: `PGRG_CHUNK_OVERLAP_TOKENS`

What: tokens of overlap between adjacent chunks.
Pros: prevents missing facts that straddle chunk boundaries.
Cons: more storage, more redundant retrieval results, more entity-resolution work.
When to use: 100-150 for dense reference docs (encyclopedias, policy manuals).
When NOT to use: 0 for already-pre-chunked data; very high values waste storage.

---

## Ingest performance

### `ingest_profile` (`conservative | balanced | aggressive | max`, default: `balanced`)
Env var: `PGRG_INGEST_PROFILE`

What: convenience preset for `doc_concurrency`, `extract_concurrency`, `embed_batch_size`. `conservative` minimizes CPU contention; `max` saturates everything.
Pros: one knob for the common "use more / less of the box" tradeoff.
Cons: still needs DB-side `pool_max` raised to match aggressive profiles.
When to use: `aggressive` or `max` for one-shot bulk ingests on a dedicated box.
When NOT to use: `max` if the box also serves online queries — you'll starve them.

### `extract_concurrency` (int, default: `0` = profile-driven)
Env var: `PGRG_EXTRACT_CONCURRENCY`

What: max concurrent LLM extraction calls during ingest.
Pros: higher saturates a fast LLM endpoint; faster ingest.
Cons: too high triggers rate limits on paid APIs; can OOM local model servers.
When to use: 16-32 for local vLLM with batching; 4-8 for OpenAI to stay under tier rate limits.
When NOT to use: never exceed your LLM endpoint's parallelism ceiling.

### `embed_batch_size` (int, default: `0` = profile-driven)
Env var: `PGRG_EMBED_BATCH_SIZE`

What: how many strings are passed to a single embedder forward pass.
Pros: bigger batches amortize per-call overhead.
Cons: larger batches need more memory; very large can hurt latency.
When to use: 64-128 for fastembed CPU; up to 512 for GPU.
When NOT to use: when memory is constrained or you have many small ingests rather than a few large ones.

### `doc_concurrency` (int, default: `0` = profile-driven)
Env var: `PGRG_DOC_CONCURRENCY`

What: max number of documents being ingested in parallel.
Pros: more parallelism = faster ingest of many small docs.
Cons: each parallel doc holds a DB connection during its transaction; high values need matching `pool_max`.
When to use: 8 for `aggressive` profile on bulk loads.
When NOT to use: above `pool_max` — connections will queue and block.

### `nice_level` (int, default: `0`)
Env var: `PGRG_NICE_LEVEL`

What: Unix `nice(2)` level applied to ingest workers. Higher = lower CPU priority.
Pros: makes ingest yield to interactive queries on a shared box.
Cons: ingest takes longer.
When to use: 5-10 for ingests running alongside online traffic.
When NOT to use: dedicated bulk-ingest boxes (waste of capacity).

---

## Retrieval — basic

### `top_k` (int, default: `10`)
Env var: `PGRG_TOP_K`

What: maximum number of chunks returned by retrieval (and passed to the answer LLM).
Pros: higher gives the answer LLM more context; lower reduces context-dilution.
Cons: too high overflows the answer LLM's context window; too low misses facts.
When to use: 5-7 for cheap answer LLMs (gpt-4o-mini); 10-15 for context-rich answer modes.
When NOT to use: above 20 — you're past the point of diminishing returns and pulling in noise.

### `max_hops` (int, default: `2`)
Env var: `PGRG_MAX_HOPS`

What: maximum graph traversal depth in `local` and `hybrid` modes.
Pros: deeper hops can find indirectly-related context.
Cons: every additional hop multiplies the candidate pool and pulls in noise. MuSiQue 4-hop showed full hybrid traversal HURTS on hard multi-hop questions.
When to use: 3 only on dense entity graphs where 1-2 hops aren't enough (e.g., dev codebase with tightly-linked services).
When NOT to use: above 3 ever. The 2-hop default already pulls many neighbors.

### `similarity_threshold` (float, default: `0.3`)
Env var: `PGRG_SIMILARITY_THRESHOLD`

What: minimum cosine similarity for a chunk to be returned.
Pros: filters out garbage low-relevance results.
Cons: too high silently drops valid results on rare-vocabulary queries.
When to use: 0.4-0.5 for very precise question-answering where false positives are worse than misses.
When NOT to use: above 0.6 — most legitimate queries score in the 0.3-0.6 range.

---

## Retrieval — cross-encoder reranking (opt-in)

### `rerank_model` (str, default: `Xenova/ms-marco-MiniLM-L-6-v2`)
Env var: `PGRG_RERANK_MODEL`

What: cross-encoder model used when `rag.query(rerank=True)` or `rag.ask(rerank=True)` is called.
Pros: MiniLM-L-6 (~80 MB) is ~5× faster than bge-reranker-base on CPU with <2 pp accuracy loss per public benchmarks.
Cons: nothing — reranker only loads when `rerank=True` is passed.
When to use: `BAAI/bge-reranker-base` (~1 GB) for accuracy-first workloads where +400-1000 ms p50 is acceptable. `Xenova/ms-marco-MiniLM-L-12-v2` (~120 MB) for a middle-ground.
When NOT to use: switching to bge-reranker-base on CPU-constrained boxes — its size will starve other workloads.

### `rerank_factor` (int, default: `2`)
Env var: `PGRG_RERANK_FACTOR`

What: how many candidates retrieval fetches before reranking — `top_k * rerank_factor`. Default 2 means 20 candidates, rerank to top_k=10.
Pros: higher = bigger candidate pool, more reranker headroom for hard queries.
Cons: linear cost in cross-encoder time. factor=4 cost 1.4-3.4 s on 1 GB bge model in our MuSiQue Step 2 run.
When to use: 3-4 only when `rerank_model` is small (MiniLM-L-6) AND retrieval-bound benchmarks suggest you're losing the right answer to reranker's first-pass.
When NOT to use: above 4 — the cross-encoder cost dominates and lift plateaus.

---

## Retrieval — short answer (opt-in)

### `rag.ask(short_answer=True)` (per-call flag, no global config field)

What: switches the answer-generation system prompt to "Output ONLY the answer as a short noun phrase, named entity, number, or date. ≤10 tokens. No explanation."
Pros: makes EM/F1 publishable on SQuAD-style benchmarks (MuSiQue, HotpotQA). Latency drops 5-8× because the LLM emits ~10 tokens vs ~200.
Cons: removes reasoning trace + citations; users get a bare answer with no provenance display. LLM judges sometimes penalize the short factoid harder than they penalized "right answer buried in a ramble."
When to use: SQuAD-style benchmarks; factoid Q&A APIs where the answer is a single fact.
When NOT to use: explanatory question answering, anything where the user needs the reasoning shown, anything where chain-of-thought matters.

---

## Retrieval — smart-mode routing (default mode)

### `boost_confidence_threshold` (float, default: `0.7`)
Env var: `PGRG_BOOST_CONFIDENCE_THRESHOLD`

What: top-chunk score above which `smart` mode ships the naive result as-is (skips graph boost).
Pros: high confidence skips the graph step entirely → fastest path.
Cons: too low ships weak naive results without graph review.
When to use: 0.8 in production where false-confidence is worse than slight latency.
When NOT to use: below 0.5 — almost everything will pass and graph boost won't fire.

### `expand_confidence_threshold` (float, default: `0.4`)
Env var: `PGRG_EXPAND_CONFIDENCE_THRESHOLD`

What: top-chunk score below which `smart` mode escalates to full `local` mode (graph expansion).
Pros: lets `smart` handle hard queries that naive retrieval can't.
Cons: each escalation adds 30-200 ms of graph traversal latency.
When to use: 0.5 for noise-heavy corpora where false-confidence is common.
When NOT to use: above 0.6 — `smart` will escalate on most queries and lose its latency advantage.

### `enable_graph_boost` (bool, default: `True`)
Env var: `PGRG_ENABLE_GRAPH_BOOST`

What: master switch for the graph-boost step in `smart` and `naive_boost` modes.
Pros: turning off makes `smart` behave like timed `naive` for medium-confidence queries.
Cons: loses the +6-19 pp lift from graph boost on multi-doc corpora (per pg-agents, MuSiQue 2-hop benchmarks).
When to use: turn off only for ablation testing or when you're sure your corpus has no useful entity chains.
When NOT to use: production unless you've measured graph boost hurts on your specific corpus.

### `graph_boost_factor` (float, default: `1.2`)
Env var: `PGRG_GRAPH_BOOST_FACTOR`

What: multiplier applied to chunks that share entities with seed chunks during graph-boost.
Pros: higher emphasizes graph-connected chunks; lower keeps vector signal dominant.
Cons: too high promotes weakly-connected chunks over strongly-relevant ones.
When to use: 1.5 for dense, well-curated entity graphs. 1.1 for noisy corpora.
When NOT to use: above 2.0 — graph signal swamps vector signal entirely.

---

## Entity resolution (ingest-time)

### `resolution_threshold` (float, default: `0.85`)
Env var: `PGRG_RESOLUTION_THRESHOLD`

What: minimum combined score (trgm + vector) for two extracted entities to be merged into one row.
Pros: higher = fewer false merges (more entity rows, more granular). Lower = more aggressive dedup.
Cons: too high keeps every spelling variant ("Apple Inc.", "apple", "Apple Inc") as separate entities → graph fragments.
When to use: 0.9-0.95 for legal/medical corpora where false merges between similar names corrupt the graph.
When NOT to use: below 0.7 — false merges become common and the graph becomes incoherent.

### `trgm_weight` (float, default: `0.4`)
Env var: `PGRG_TRGM_WEIGHT`

What: weight of pg_trgm fuzzy string similarity in the resolution score.
Pros: high weight = prefers spelling-similarity. Useful when names are inconsistently capitalized or hyphenated.
Cons: high weight ignores semantic identity (e.g., "JFK" and "John Kennedy" share no trigrams).
When to use: 0.6 when you trust source spelling and entities are short names.
When NOT to use: 1.0 — semantic dedup via embeddings is the signal that catches synonyms.

### `vec_weight` (float, default: `0.6`)
Env var: `PGRG_VEC_WEIGHT`

What: weight of vector cosine similarity in the resolution score.
Pros: high weight = prefers semantic identity over spelling.
Cons: alone, can conflate unrelated entities with similar embeddings ("Apple" the fruit vs "Apple" the company).
When to use: 0.7-0.8 for synonym-heavy corpora (medical, scientific).
When NOT to use: 1.0 — `trgm_weight` is what disambiguates same-name-different-spelling cases.

### `min_trgm_score` (float, default: `0.3`)
Env var: `PGRG_MIN_TRGM_SCORE`

What: minimum trigram similarity required for an entity to enter the resolution candidate pool.
Pros: pre-filters obviously different names before paying the vector-cosine cost.
Cons: too high silently rejects valid synonym candidates that don't share characters.
When to use: 0.4 for clean datasets where typos are rare.
When NOT to use: 0.0 — every entity becomes a candidate and resolution becomes O(N²).

---

## Hybrid scoring weights

(Used in `local`, `global`, and `hybrid` modes to combine signals.)

### `w_sem` (float, default: `0.50`)
Env var: `PGRG_W_SEM`

What: weight of semantic (vector cosine) similarity in the final chunk score.
Pros: high weight = prefer semantic match. Most-tested default.
Cons: high weight on noisy queries pulls in tangentially-related chunks.
When to use: 0.6 for paraphrased / vocabulary-mismatched queries.
When NOT to use: 0.0 — you'd be turning off the dominant signal.

### `w_bm25` (float, default: `0.20`)
Env var: `PGRG_W_BM25`

What: weight of BM25 keyword match (Postgres tsvector + tsquery).
Pros: high weight = prefers exact keyword match. Crucial for rare-vocabulary queries (proper nouns, code identifiers).
Cons: too high ignores semantic intent.
When to use: 0.3-0.4 for code/log/identifier-heavy corpora.
When NOT to use: 0.0 — losing BM25 hurts on names and codes.

### `w_graph` (float, default: `0.20`)
Env var: `PGRG_W_GRAPH`

What: weight of graph-connectivity score (chunk's connection to seed entities).
Pros: high weight = prefers chunks connected via entity graph. Big lift on multi-doc reasoning.
Cons: too high creates "graph bias" — chunks score high just for being densely connected, even when off-topic.
When to use: 0.3 on multi-doc corpora where reasoning chains matter.
When NOT to use: above 0.4 — graph signal swamps direct relevance.

### `w_recent` (float, default: `0.10`)
Env var: `PGRG_W_RECENT`

What: weight of recency bias (newer documents score higher). Only effective when `evolution_tier` ≠ `off`.
Pros: surfaces recent updates over stale content.
Cons: penalizes durable evergreen content.
When to use: 0.2 for news, alerts, on-call runbooks where recent ≈ correct.
When NOT to use: encyclopedic / reference corpora where age is not a signal.

### `w_supersession` (float, default: `0.10`)
Env var: `PGRG_W_SUPERSESSION`

What: weight of supersession penalty (chunks superseded by newer ones get lower scores). Only effective when `evolution_tier` ≠ `off`.
Pros: prevents stale facts surfacing when newer ones exist.
Cons: requires `supersedes` metadata at ingest.
When to use: versioned docs (Python 3.10/3.11/3.12), evolving policy docs.
When NOT to use: corpora without supersession structure.

### `temporal_half_life_years` (float, default: `5.0`)
Env var: `PGRG_TEMPORAL_HALF_LIFE_YEARS`

What: years over which `w_recent` decays a document's score by half.
Pros: smooth recency weighting instead of a hard cutoff.
Cons: too short over-penalizes anything not from this quarter.
When to use: 1.0 for fast-moving fields (security advisories, model releases).
When NOT to use: <0.25 — recency dominates everything else.

### `lambda_supersession` (float, default: `0.5`)
Env var: `PGRG_LAMBDA_SUPERSESSION`

What: how much score reduction superseded chunks receive (0 = none, 1 = full hide).
Pros: tune how aggressively old facts get pushed down.
Cons: too high loses historical context entirely.
When to use: 0.7 for compliance / latest-policy enforcement.
When NOT to use: 1.0 — equivalent to deleting old knowledge.

---

## Retrieval — strategy and metadata indexes

These knobs control the SQL shape of vector + metadata queries and the indexes that make selective predicates cheap. All have safe defaults — opt in only when you have caller-supplied metadata you want to filter on.

### `retrieval_strategy` (`"weighted" | "pre_filter" | "vector_first"`, default: `weighted`)
Env var: `PGRG_RETRIEVAL_STRATEGY`

What: SQL shape for combining vector similarity with metadata predicates. `weighted` joins documents/chunks then ranks (today's default; works on every plan). `pre_filter` filters documents BEFORE the vector seek — fastest when the predicate is selective AND indexed. `vector_first` runs HNSW first, then post-filters — best for single-namespace HNSW-eligible corpora where the planner picks the index.

Per-call override: `rag.query(..., retrieval_strategy="pre_filter")` (multi-tenant safe; no config mutation).

Pros: lets you match the SQL shape to your data shape. `pre_filter` is dramatic on selective metadata predicates with indexes.
Cons: `vector_first` can recall-shortfall under selective predicates — bump `retrieval_oversample_factor` or switch to `pre_filter`.
When to use: `pre_filter` for sales-CRM / per-tenant / per-version corpora. `vector_first` for single-namespace, broad-predicate. `weighted` when in doubt.
See: [`docs/cookbook/retrieval-strategy.md`](cookbook/retrieval-strategy.md).

### `retrieval_oversample_factor` (int, default: `10`)
Env var: `PGRG_RETRIEVAL_OVERSAMPLE_FACTOR`

What: for `vector_first`, how many candidates to fetch from HNSW before applying the post-filter. Effective seed size = `top_k × retrieval_oversample_factor`.
Pros: higher = better recall under selective predicates.
Cons: higher = slower vector seek.
When to use: tune up when you observe `pgrg.vector_first.recall_shortfall` events in the metrics logger.

### `metadata_indexes` (list[str], default: `[]`)
Env var: `PGRG_METADATA_INDEXES` (comma-separated)

What: per-key btree indexes on `chunks.metadata->>'<key>'`. For each key in the list, `connect()` runs `CREATE INDEX IF NOT EXISTS idx_chunks_metadata_<key>`.
Pros: makes selective equality predicates on chunk metadata cheap; pairs with `retrieval_strategy="pre_filter"`.
Cons: non-CONCURRENTLY `CREATE INDEX` takes an `ACCESS EXCLUSIVE` lock during initial build — fine on fresh deploys, brutal on a live multi-million-row table. For retrofits, use the `apply_metadata_indexes_concurrently()` runtime API instead, then add the key here so `connect()` finds the existing index.
Key whitelist: `^[a-zA-Z_][a-zA-Z0-9_]*$`, ≤63 chars.

### `metadata_indexes_gin` (bool, default: `False`)
Env var: `PGRG_METADATA_INDEXES_GIN`

What: GIN index over the whole `chunks.metadata` JSONB column. Use when you have JSONB containment predicates (`metadata @> '{"tag":"x"}'`), key-existence (`metadata ? 'k'`), or multi-key matches (`metadata ?| ARRAY[...]`) — none of which the per-key btrees can serve.
Pros: covers the long tail of ad-hoc JSONB predicates.
Cons: ~2–4× the bytes per indexed row vs btree; slower writes.
When to use: alongside `metadata_indexes` — btree for hot equality keys, GIN for the long tail.

### `metadata_generated_columns` (dict[str, str], default: `{}`)
Env var: not env-configurable (dict).

What: STORED generated columns + btree indexes derived from `chunks.metadata`. Map of metadata key → SQL type. For each entry, `connect()` creates `meta_<key>` of the given type (cast from `metadata->>'<key>'`) and a btree on it. Allowed types: `text`, `int`, `bigint`, `numeric`, `timestamptz`, `boolean`.
Pros: the only correct way to index numeric / timestamp predicates from JSONB — text comparison says `'10' < '5'`.
Cons: the cast runs on every write; a row whose `metadata->>'<key>'` doesn't parse fails the write. Loud failure beats silent corruption.
Example: `{"priority": "int", "created_at": "timestamptz"}`.

### `document_metadata_indexes` (list[str], default: `[]`)
Env var: `PGRG_DOCUMENT_METADATA_INDEXES` (comma-separated)

What: per-key btree indexes on `documents.metadata->>'<key>'`. The chunks-side mirror (above) targets chunker-written fields; this targets caller-supplied per-record fields (salesperson, product, customer_id, etc.) that land on `documents.metadata` via `ingest_records()`. For the common GraphRAG-from-DB pattern (sales notes, support tickets, anything pulled from a PG table), the USEFUL indexes are on `documents.metadata`, not `chunks.metadata`.
See: [`docs/cookbook/metadata-indexes.md`](cookbook/metadata-indexes.md) → "Why two tables matter".

### `document_metadata_indexes_gin` (bool, default: `False`)
Env var: `PGRG_DOCUMENT_METADATA_INDEXES_GIN`

What: GIN index over `documents.metadata` JSONB. Same shape and trade-offs as `metadata_indexes_gin` but for the documents side.

### `document_metadata_generated_columns` (dict[str, str], default: `{}`)
Env var: not env-configurable.

What: STORED generated columns + btree indexes on `documents` (column: `meta_<key>`; index: `idx_documents_meta_<key>`). Same allowed types and trade-offs as the chunks-side `metadata_generated_columns`.

---

## Evolution / Tier 1 (versioning + retraction)

### `evolution_tier` (`"off" | "structural" | "fact_aware" | "full"`, default: `off`)
Env var: `PGRG_EVOLUTION_TIER`

What: master switch for evolving-knowledge features. `off` = classic GraphRAG. `structural` = adds version_label / effective_from / retracted columns. Higher tiers add fact-level deduplication and contradiction detection.
Pros: enables time-travel queries (`as_of=...`) and retraction-aware retrieval.
Cons: higher tiers add ingest cost (fact extraction). `structural` is the cheap one.
When to use: `structural` for any corpus that gets updated over time. `fact_aware` for medical/legal/regulatory.
When NOT to use: `full` for static one-shot benchmarks — pure overhead.

### `retracted_behavior` (`"hide" | "flag" | "surface_both"`, default: `flag`)
Env var: `PGRG_RETRACTED_BEHAVIOR`

What: how retracted documents/facts are treated by retrieval. `flag` includes them with a marker; `hide` excludes them; `surface_both` returns retracted + replacement.
Pros: `hide` is safest for compliance ("never return retracted"); `surface_both` is best for research.
Cons: `flag` shows retracted content downstream, requiring caller awareness.
When to use: `hide` for medical/regulatory; `surface_both` for research / audit trails.
When NOT to use: `flag` if downstream consumers can't process the metadata flag.

### `supersession_behavior` (`"hide" | "prefer_new" | "surface_both"`, default: `surface_both`)
Env var: `PGRG_SUPERSESSION_BEHAVIOR`

What: how superseded versions are handled. `surface_both` returns old + new; `prefer_new` ranks new higher; `hide` returns only new.
Pros: tune how aggressively old knowledge is suppressed.
Cons: `hide` makes "what changed?" queries hard.
When to use: `prefer_new` for general user-facing search; `hide` for "current docs only" requirements.
When NOT to use: `hide` when historical context matters (e.g., "what was the API in v1.2?").

### `memory_tier` (`"provisional" | "consolidated" | "both"`, default: `both`)
Env var: `PGRG_MEMORY_TIER`

What: read-side filter for chunkshop SP-A agent-memory tier (Pattern M cookbook). When chunks carry a `tier` key in their JSONB metadata (bridged from `chunkshop.agent_memory.memory`), this restricts retrieval to chunks with the matching tier(s). Default `both` applies no filter — non-memory corpora and pre-SP-A chunks are unaffected.

Per-call override: `rag.query(..., memory_tier="consolidated")`.

Pros: enforces SP-A's "consolidated-wins" O2 rule at read time without mutating ingest.
Cons: filter is predicate-based; highly selective predicates may benefit from a dedicated namespace per tenant instead.
When to use: any agent-memory deployment via the SP-A bridge.
See: [`docs/cookbook/chunkshop-integration.md#pattern-m-agent-memory`](cookbook/chunkshop-integration.md#pattern-m-agent-memory).

### `contradiction_detection` (bool, default: `True`)
Env var: `PGRG_CONTRADICTION_DETECTION`

What: at ingest time, flag facts that contradict existing facts in the same namespace.
Pros: catches stale-info issues automatically; useful for medical / regulatory.
Cons: adds ingest cost; false-positive rate depends on the extractor model.
When to use: any evolving knowledge corpus.
When NOT to use: static benchmarks (waste of cycles); when the extractor is unreliable.

### `fact_extractor` (`"llm" | "lede_spacy" | "none"`, default: `none`)
Env var: `PGRG_FACT_EXTRACTOR`

What: extractor backend for the graph. `llm` = full-quality LLM entity+relationship extraction, expensive. `lede_spacy` = deterministic, LLM-free: lede + lede-spacy NER produce (untyped) entities and edges are sentence-level co-occurrence (`RELATED_TO`); no LLM, no network. `none` = disabled.
Requires (for `lede_spacy`): `pip install 'pg-raggraph[lede_spacy]'` **and** `python -m spacy download en_core_web_sm`. Selecting `lede_spacy` builds a graph **without** `llm_base_url` set; missing deps fail loud with the exact install commands.
Pros: `lede_spacy` is ~sub-5ms/doc and fully offline; `llm` gives higher relational quality.
Cons: `llm` adds an extraction LLM call per chunk. `lede_spacy` edges are co-occurrence, not semantic relations; entities are untyped (`entity_type="entity"`) in this version.
When to use: `lede_spacy` when you need a graph with no LLM/offline; `llm` for higher-quality typed relations.
When NOT to use: `none` is correct unless you want a graph. NOTE: `lede_spacy` does **not** emit SPO triples and does **not** populate the Tier 2 `facts` table — that is a tracked follow-up.

### `fact_dedup_threshold` (float, default: `0.8`)
Env var: `PGRG_FACT_DEDUP_THRESHOLD`

What: cosine similarity threshold for deduplicating facts at ingest.
Pros: prevents the same fact extracted from two paraphrases from creating two rows.
Cons: too high keeps near-duplicates; too low merges similar-but-different facts.
When to use: 0.85 for tight technical corpora.
When NOT to use: below 0.7 — risks merging different facts.

### `fact_similarity_threshold` (float, default: `0.92`)
Env var: `PGRG_FACT_SIMILARITY_THRESHOLD`

What: cosine threshold for matching a query against the facts table during retrieval.
Pros: high threshold = only high-confidence fact matches get returned.
Cons: too high silently misses paraphrased queries.
When to use: 0.95 for accuracy-first; 0.88 for recall-first.
When NOT to use: below 0.8 — false matches contaminate results.

### `fact_edge_candidate_k` (int, default: `8`)
Env var: `PGRG_FACT_EDGE_CANDIDATE_K`

What: maximum edges considered per entity during fact-level retrieval.
Pros: higher = more comprehensive search through the fact graph.
Cons: linear cost; diminishing returns past 8-12.
When to use: 12 on dense fact graphs.
When NOT to use: above 20 — performance falls off.

### `diversity_backfill` (bool, default: `True`)
Env var: `PGRG_DIVERSITY_BACKFILL`

What: at retrieval time, backfill the result set with diverse chunks if too many top-k come from the same document.
Pros: prevents single-doc dominance in answers.
Cons: can dilute precision if all relevant info is in one doc.
When to use: multi-doc corpora where coverage matters.
When NOT to use: single-doc answers (e.g., manual lookups) where precision dominates.

---

## How to find the right values for your corpus

1. **Start with defaults.** Every default has been measured on at least one of {SCOTUS, NTSB, PG-docs, pg-agents, MuSiQue, medical-HRT}.
2. **Run [`benchmarks/run_all_benchmarks.py`](../benchmarks/run_all_benchmarks.py)** on a representative sample of your corpus.
3. **Tune one knob at a time.** Confounded changes are unreadable.
4. **Always re-measure latency too.** Accuracy lifts that quintuple latency rarely make it to production.

For a step-by-step accuracy improvement plan that respects latency, see [`docs/proposals/Accuracy-Improvements-Roadmap.md`](proposals/Accuracy-Improvements-Roadmap.md).
