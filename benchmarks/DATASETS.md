# pg-raggraph Benchmark Datasets

## Available Corpora

### 1. KG-RAG Eval Datasets (docugami)

**Source:** [github.com/docugami/KG-RAG-datasets](https://github.com/docugami/KG-RAG-datasets)

| Dataset | Docs | Size | Gold QnA |
|---------|------|------|----------|
| SEC 10-Q Filings | 20 | 3.3MB | **195** (76 single-chunk, 54 multi-chunk, 65 multi-doc) |
| NTSB Aviation Reports | 20 | 110KB | Draft |
| NIH Clinical Trials | 20 | (unzipped) | Draft |
| US Fed Agency Reports | 20 | (unzipped) | Draft |

**Why useful:** Real production-style documents with gold-standard QA pairs designed for multi-doc RAG evaluation.

### 2. PostgreSQL Documentation

**Source:** Official PG 16 docs + blog posts (EDB, pgDash, pgedge)

| Dataset | Docs | Size | Gold QnA |
|---------|------|------|----------|
| PostgreSQL Docs | 31 | 491KB | 10 (hand-written) |

**Why useful:** Dense technical content, tests whether graph helps on self-contained reference documentation.

### 3. HotpotQA (Wikipedia Multi-Hop)

**Source:** [hotpotqa.github.io](https://hotpotqa.github.io/) dev set
**License:** CC BY-SA 4.0

| Dataset | Docs | Size | Gold QnA |
|---------|------|------|----------|
| HotpotQA (dev, distractor) | 4,937 Wikipedia articles | 46MB JSON | **500 hard multi-hop questions** |

**Structure:**
- 404 "bridge" questions (A → B → answer, requires 2-3 hops)
- 96 "comparison" questions (compare A and B across docs)
- Each question has 2 gold supporting articles + 8 distractors
- All labeled as difficulty level "hard"

**Why useful:** **The standard academic benchmark for multi-hop QA.** Every question requires reading 2+ Wikipedia articles. If graph RAG can't win here, it can't win anywhere.

### 4. US Supreme Court (SCOTUS)

**Source:** [Oyez Project API](https://api.oyez.org/) — free, no auth
**License:** Public domain (federal court records)

| Dataset | Docs | Size | Graph Structure |
|---------|------|------|------|
| SCOTUS Cases (2018-2023) | **391 cases** | 1.7MB | Justice votes, parties, citations |

**Structure per case:**
- Case name, docket number, citation
- Question presented
- Facts of the case
- Decision and reasoning
- Vote breakdown by justice (majority/dissent/concurrence)
- Related/cited cases
- Parties (petitioner, respondent)

**Why useful:**
- **Explicit graph structure:** Justices → cases → precedents → parties
- **Cross-case reasoning:** "Which cases cited Chevron?" requires the citation graph
- **Entity density:** Every case has 9+ justices, 2 parties, citations, dates
- **Real relationships:** Same justices appear across all cases — the knowledge graph practically builds itself

---

## Total Available

- **~440 individual documents** across 4 corpora
- **~200 gold-standard QA pairs** for objective accuracy measurement
- **5.5MB text** for ingestion performance testing
- **Three orders of magnitude** in relationship density (technical docs → aviation reports → SCOTUS cases)

## Ingestion Time Estimates

Using the parallel ingestion (doc_concurrency=4, extract_concurrency=16, remote vLLM):

| Corpus | Docs | Estimated Time | Status |
|--------|------|---------------|--------|
| PostgreSQL Docs | 31 | ~8 min | ✅ Complete |
| NTSB Aviation | 20 | ~3.5 min | ✅ Complete (213s) |
| SEC 10-Q | 20 | ~30 min | 🔄 In progress |
| HotpotQA (sample) | ~40 | ~8 min | 🔄 In progress |
| SCOTUS (full) | 391 | ~60-90 min | ⏳ Ready to ingest |

With a faster LLM (GPT-4o-mini, local Llama 3.2 with better hardware), these times would be 2-5x faster.
