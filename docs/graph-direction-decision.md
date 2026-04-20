# Graph-approach direction decision — pg-raggraph (2026-04-20)

> Closes TODO item **T-G1**. Time-boxed research pass answering: is the way pg-raggraph does "graph" (LLM entity extraction → adjacency tables → recursive CTE traversal) the right primitive, or is it what's capping our accuracy?

## TL;DR

**Keep the graph tables. Supplement retrieval with dual-level keyword matching. Demote the graph-augmented retrieval modes in the product narrative.** The bakeoff evidence is clear: chunking carried every accuracy win; the graph retrieval modes add cost without adding signal, including on the multi-hop bridging class they were specifically designed for. The graph layer is still valuable for explainability, provenance, visualization, and MCP tool use — but positioning pg-raggraph as "graph-augmented retrieval" is not supported by the data. The next high-value experiment is porting LightRAG's dual-level retrieval (low + high keywords against entity and relationship vectors), which is the one graph-adjacent idea we haven't tried.

---

## Four questions

T-G1 asked four things. Each gets an evidence-backed answer below.

### (a) Is entity-extraction-from-LLM the wrong primitive?

**Answer: probably not the right question.** The primitive isn't the bottleneck.

- pg-raggraph's extraction captures SCOTUS entities + relationships byte-identically to Apache AGE on the bakeoff. Extraction quality is not where we lose accuracy. (See `benchmarks/age-bakeoff/results/REPORT-VERDICT.md` §4 — both engines preserve 416/416 entities and 4397/4397 relationships on the same LLM output.)
- Alternative primitives like HippoRAG (Personalized PageRank on entity embeddings with no relationship type at all) or knowledge-graph-triple extraction (subject-predicate-object canonicalization) would produce a different graph topology, but the bakeoff shows the existing topology isn't being used. Switching primitives to get unused bits into a different shape isn't the upgrade path.
- Where the primitive _does_ matter: downstream use cases like explainability, citation chains, and the web-UI graph view all want typed, traversable relationships. Entity embeddings alone (HippoRAG style) give you worse explanations. The LLM-extracted primitive is fine for those use cases.

### (b) Are adjacency-table relationships noise for most queries?

**Answer: for retrieval specifically, yes.** Per-class SCOTUS hierarchy bakeoff (pgrg, 30 questions):

| Class | n | naive | naive_boost | local | global | hybrid | smart |
|---|---|---|---|---|---|---|---|
| semantic | 8 | **8** | **8** | **8** | **8** | **8** | **8** |
| factual | 6 | 4 | 4 | 4 | 4 | 4 | 4 |
| multi_hop_bridging | 6 | 2 | 2 | 2 | **1** | 2 | 2 |
| single_hop | 10 | 4 | 3 | 4 | **5** | 4 | 3 |

Observations:

- **Graph modes don't beat naive on any class.** They tie on semantic + factual + multi_hop_bridging and hover inside noise on single_hop.
- **Multi-hop bridging, the class graph was supposed to crush, caps at 2/6 across every mode.** The one place graph retrieval was supposed to earn its keep does not show a graph advantage. Global is actually _worse_ on bridging (1/6) than naive (2/6).
- **Graph wins are inside ±1-question noise.** Global's +1 on single_hop is a coin flip; the −1 on bridging cancels it.

The hypothesis "graph expansion surfaces chunks that vector misses" is falsified on this corpus at this question count. Even if we extend to 100 questions and see graph modes edge out by 1-2 points on bridging, that would still be a small win bought at 3× latency and 3× code complexity — not a defining product advantage.

Corroborating evidence from acme (`ACME-HIER-REPLICATION.md`): graph modes also offered no lift there. Two independent corpora pointing the same direction.

### (c) Should community detection (Leiden) replace or augment traversal?

**Answer: supplement, don't replace — and don't ship as default.**

`global` mode already uses community summaries (pre-computed per namespace). Its per-class row is the flattest of any mode: 4/6 factual, 8/8 semantic, 1/6 bridging, 5/10 single_hop. Best single-hop result of the sweep; worst bridging. No overall accuracy win.

Microsoft GraphRAG's original Leiden-based approach costs ~$6-7 to index 32K words on GPT-4o and needs full rebuild on any new document. LightRAG specifically ditched Leiden communities in favor of dual-level keywords and claims 6,000× cheaper per-query cost while matching or beating GraphRAG on accuracy. The field has broadly moved away from "communities as the retrieval primitive."

pg-raggraph already supports community IDs as a column on the `entities` table with an optional `leidenalg` extra. The schema and SDK path exist. What's missing is:
- Actually running Leiden on ingest (we don't — community_id stays NULL).
- Wiring community summaries into the `global` mode retrieval (today `global` uses a simpler "all chunks linked to frequently-mentioned entities" heuristic, not communities).

**Recommendation:** leave the schema in place. Don't turn Leiden on by default. If a user with a specific need (cross-document bridging on a stable corpus) asks for it, we have the hooks. But we don't ship it as the answer to the graph-retrieval problem because the evidence says the graph-retrieval problem is not solvable by better graph retrieval.

### (d) Is "graph" mostly ceremony on top of what's really vector+BM25+rank?

**For retrieval, yes. For the library overall, no.** The distinction matters.

**Graph is ceremony when**:

- The question is "which chunks should I rank?" — pure vector + BM25 + title-prefix chunking got there on SCOTUS.
- You're comparing retrieval modes. The bakeoff spent weeks proving local/global/hybrid/smart all tie naive under good chunks. Real data, not a paper claim.
- Latency matters. Graph modes on SCOTUS ran 2-5× slower than naive for a zero-accuracy trade.

**Graph is not ceremony when**:

- The user wants to see _why_ an answer was retrieved. The `/graph` endpoint, web UI visualization, and MCP tool `pgrg_query`'s `entities` return field all depend on the adjacency tables.
- A downstream agent wants to follow relationships programmatically. `rag.query(..., mode="local")` with a seed entity is a legitimate API even if it doesn't win benchmark accuracy.
- Provenance and citation quality are the product goal rather than top-k accuracy.
- The corpus is agentic state (conversations, incident timelines, ownership chains) where the graph _is_ the primary data model, not a retrieval booster.

The product should lead with the second set of use cases, not the first.

---

## What to do about it

### Keep

- **The graph schema** — adjacency tables, recursive-CTE traversal, community_id column. Cheap to maintain; high value for explainability.
- **`local` as an explicit API path** — users who ask "what else relates to entity X?" need this. Document as such; don't pitch it as "the accuracy mode."
- **`naive` and `naive_boost`** — they're the honest baseline and the cheapest upgrade path respectively.
- **`global` as a niche tool** — document that it's for corpora with meaningful community structure (not 30 short legal cases) and don't evangelize it.

### Pivot (positioning, not code)

The product's marketing story today is something like "GraphRAG in Postgres — hybrid vector + BM25 + graph retrieval." That narrative is underwritten by SCOTUS evidence it cannot support. Rewrite to:

> **pg-raggraph is a GraphRAG library that lives entirely in Postgres. It stores documents, chunks, embeddings, entities, and relationships in one ACID-compliant database — no separate graph or vector store. Retrieve with vector + BM25 by default (fast, cheap, accurate on well-chunked corpora). Walk the graph when you need explainability, provenance, or cross-document bridging specifically.**

Concrete doc changes:
- Update README's headline to lead with the "one database, multi-surface access (SDK / CLI / API / MCP / UI)" story rather than "+18.9% with graph boost." Coordinate with TODO T-P9.
- Rewrite `docs/modes.md` to open with "pick `naive` unless you have a specific reason" and treat `local`/`global`/`hybrid`/`smart` as documented escape hatches.
- Update the pitch in the pg-raggraph-vs-AGE comparison doc to de-emphasize "graph retrieval wins" and lean on operational wins (latency, cloud compatibility, single DB) where the evidence is strongest.

### Supplement — the one experiment worth running

**Port LightRAG's dual-level retrieval.** This is the one graph-adjacent idea we haven't benchmarked, and it's the only one with compelling third-party evidence (EMNLP 2025 Findings, 33K stars).

How it works:
1. At query time, the LLM extracts **low-level keywords** (specific entity names) and **high-level keywords** (themes, concepts) from the question.
2. Low-level keywords match against entity name/description embeddings → seed entities.
3. High-level keywords match against relationship description embeddings → seed relationships.
4. Union the chunks attached to both seed sets, rank, return.

This is fundamentally different from our current `local` mode (vector-first, then graph-expand). It's keyword-first in the LLM's ontology, then vector-matched against graph nodes and edges, then chunk-materialized. LightRAG's benchmark claims 60-84% win rate vs NaiveRAG, including on legal-style corpora.

**Cost to try:** ~1 week of implementation, ~$10 of bakeoff runs on SCOTUS + acme + one new corpus. If it lifts accuracy past 20/30 on SCOTUS or past 10/30 on acme while staying within 2× naive latency, it justifies keeping the graph layer as a retrieval primitive. If it doesn't move the needle, we lean harder into "graph is for explainability, not retrieval" and simplify accordingly.

### Don't do

- **Don't rewrite the extraction pipeline** to use entity embeddings instead of LLM-extracted relationships. No evidence it helps; we'd lose explainability (typed relationships are what the web UI and MCP return).
- **Don't ship Leiden community detection as a default.** Keep the optional extra; revisit only if a user with a stable-corpus use case asks for it and we have measured data on it.
- **Don't rip out the graph retrieval modes.** They have real users (even inside this project, smart mode is the server default). Demoting them in docs is enough; preserving the API keeps backward compat.
- **Don't build smart-mode v2** until we have either (a) a larger benchmark question set or (b) a corpus where smart has a clearer signal than naive. Today's 17-vs-18 SCOTUS gap is noise.

---

## The bet this decision makes

pg-raggraph is not going to beat LightRAG, HippoRAG, or MS GraphRAG on raw retrieval accuracy. None of those systems has a GraphRAG stack that runs on vanilla Postgres with pgvector + pg_trgm, and none has a clean multi-surface story (SDK + CLI + API + MCP + UI). Those are the lanes pg-raggraph can own.

The retrieval-accuracy-winning frontier will keep moving every 6 months with some new paper. We're not going to chase it. We're going to ship the best, simplest, most-operable GraphRAG-for-Postgres library, with enough graph surface area for real use cases (explainability, programmatic traversal, multi-tenant isolation) and enough retrieval quality that users don't regret the choice.

If dual-level retrieval (the one experiment above) pulls us into the top tier of retrieval accuracy on our next corpora, great — we'll take the win. If not, the positioning above still holds.

---

## Next actions (new TODO items)

Adding to the project TODO for tracking:

- **T-G2**: Implement LightRAG dual-level retrieval as a new mode. ~1 week. Ship behind `mode="dual_level"` initially; promote to default if it beats naive by ≥3 questions on SCOTUS AND holds up on acme.
- **T-G3**: Rewrite README headline + `docs/modes.md` opening + pg-raggraph-vs-AGE positioning per "pivot (positioning)" above. ~4-6 hours. Coordinates with T-P9.
- **T-G4**: Add a question-class breakdown to the bakeoff report generator (`age-bakeoff report --by-class`). Would have surfaced the "graph doesn't help bridging" finding in the original sweep rather than forcing a manual re-analysis today.

These are _not_ blockers for the public-repo push. T-G3 should land alongside T-P9 before or shortly after the repo goes public so the positioning is right from day one.
