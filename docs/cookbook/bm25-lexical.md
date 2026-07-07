# BM25 lexical scoring and rank fusion (issue #96)

The hybrid score has always had a "BM25" leg. Until 0.5.0a20 it was actually
`ts_rank` — term frequency and proximity only — blended linearly at `w_bm25=0.20`
against cosine at `0.50`. Three compounding defects made it a near-no-op:

1. **No IDF.** `ts_rank` never consults corpus statistics, so a rare
   discriminating token (a function-name component, a unique codename) gets no
   advantage over a common word. tf-heavy prose beats the chunk that defines
   the term.
2. **`'english'` stemming mangles identifiers.** The tsvector *parser* splits
   `validate_billing_archive` into `valid`/`bill`/`archiv` — and it does this
   regardless of dictionary config (`'simple'` included; the split happens
   before dictionaries run).
3. **Raw-scale mismatch.** ts_rank raw scores live at ~0.01–0.1 while cosine
   lives at ~0.6–0.9; at 0.20 weight the lexical contribution is smaller than
   embedding noise between near-identical chunks.

Two fixes shipped together:

- **`fusion="rrf"` is now the default** (was `"linear"`). Reciprocal Rank
  Fusion combines the legs by rank, not raw score, so the lexical leg votes
  regardless of scale. It now applies to `naive`, `local`, `global`, and
  `hybrid` modes (it was silently inert in local/global before). `linear`
  remains available for byte-for-byte reproducibility:
  `PGRG_FUSION=linear` or `rag.query(..., fusion="linear")`.
- **`lexical_backend="bm25"`** (opt-in) replaces ts_rank with real Okapi BM25
  scored in SQL, plus identifier-preserving tokenization.

## Enabling BM25

```python
from pg_raggraph import GraphRAG

rag = GraphRAG(dsn=..., lexical_backend="bm25")   # or PGRG_LEXICAL_BACKEND=bm25
await rag.connect()                                # applies migration 016
```

For a corpus that existed **before** migration 016, backfill the statistics
once per namespace:

```python
await rag.rebuild_lexical_stats("my_namespace")
# or: pgrg rebuild-lexical-stats -n my_namespace
```

New writes (ingest, re-ingest, update, delete) maintain the stats
automatically from that point on. Run the rebuild while ingest into the
namespace is quiescent.

## The scoring formula

Per query term `t` present in the chunk:

```
score += IDF(t) · tf·(k1 + 1) / (tf + k1·(1 − b + b·dl/avgdl))

IDF(t) = ln(1 + (N − df + 0.5) / (df + 0.5))     # Lucene's non-negative variant
```

- `N`, `avgdl` — per-namespace chunk count and average length
  (`lexical_corpus_stats`)
- `df` — number of chunks containing the lexeme (`lexeme_stats`)
- `tf` — the lexeme's position count in `chunks.search_vector`
- `dl` — the chunk's total term count
- `k1` (`bm25_k1`, default 1.2) and `b` (`bm25_b`, default 0.75) — standard
  Okapi knobs

Everything is computed in one SQL expression per candidate chunk — no second
round-trip, no extension, single-database thesis intact. A Python reference
implementation lives at `pg_raggraph.lexical.bm25_score` for auditing.

## Identifier-preserving tokenization

Migration 016 adds `pgrg_identifier_tsvector()`: underscored identifiers are
extracted by regex and injected into `search_vector` as whole lexemes
(bypassing the parser), lowercased, positionless. The query side applies the
same function, so `validate_billing_archive` matches the chunk that defines it
— and because the identifier is corpus-rare, BM25's IDF ranks that chunk above
prose that merely mentions "valid", "billing", or "archives".

This is always on for new writes (it is a no-op on prose — prose rarely
contains underscored tokens) and invisible to the `ts_rank` backend
(positionless lexemes rank as 0 there). Chunks indexed before the migration
pick up identifier lexemes on their next content update, or re-index with
`UPDATE chunks SET content = content` (see migration 011's notes).

## Stats maintenance strategy

Exact incremental triggers — **no drift by design**:

- `chunks` AFTER INSERT / UPDATE / DELETE (statement-level, transition
  tables): increment/decrement `df` per lexeme plus corpus counters. Updates
  only pay for rows whose `search_vector` actually changed.
- `documents` BEFORE DELETE (row-level): handles the FK-cascade path — by the
  time cascaded chunk deletes fire, the parent document (and its namespace)
  is gone, so the document trigger decrements while the chunks still exist.

Deletes decrement rather than drift-and-rebuild; `rebuild_lexical_stats()`
exists only for pre-migration corpora (and as a repair tool). Upsert order is
sorted `(namespace, lexeme)` so concurrent ingest transactions can't deadlock
on shared lexeme rows; the known ceiling is hot-lexeme row locks serializing
the *storage phase* of concurrent document transactions.

## Interplay and caveats

- **Fusion:** BM25 raw scores are unbounded (~0–15). Under the default
  `fusion="rrf"` this is irrelevant (ranks, not scores). Under
  `fusion="linear"`, retune `w_bm25` before drawing conclusions.
- **Smart mode:** the `smart` router's confidence probe is pinned to linear
  fusion internally — its 0.7/0.4 thresholds are calibrated on raw linear
  scores (RRF scores live at ~0.01 and would route everything to the
  low-confidence escalation). Shape-routed and escalation queries follow your
  configured fusion.
- **Hybrid mode:** under `rrf`, the local/global legs are rank-fused in
  Python across the two lists (issue #57); each leg's internal SQL stays
  linear so the damping isn't applied twice.
- **`retrieval_expansion`:** expansion terms feed the ts_rank tsquery; the
  BM25 term set is derived from the raw question text (stemmed + identifier
  lexemes). If you rely on alias expansion, keep the ts_rank backend or file
  an issue.
- **Cost:** the BM25 expression is a per-candidate correlated subquery. With
  the default two-stage retrieval it prices over ≤ `retrieval_candidate_k`
  rows. In single-pass `weighted` strategy on very large namespaces it scores
  every chunk — prefer two-stage (default) or `pre_filter`/`vector_first`.
