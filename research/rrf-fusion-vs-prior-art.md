# RRF Fusion in pg-raggraph vs Prior Art: Why Linear Beat It, and What We Got Wrong

**Date:** 2026-06-03
**Purpose:** Explain why pg-raggraph's optional RRF fusion (issue #57) lost to linear weighting on our scale benchmark, by comparing our implementation against how the field uses and implements Reciprocal Rank Fusion. Determine what we did right, what we did wrong, and whether our default is actually the better choice.
**Status:** Research note. Informs whether to fix our RRF (fuse independent retriever lists) or keep linear as the endorsed default.

---

## The question

We shipped optional RRF (`fusion="rrf"`) and benchmarked it. On a saturated small corpus it was recall-neutral; on the full 1700-doc MuSiQue corpus with rank-sensitive metrics, **linear beat RRF by ~3-5pp on nDCG@10, MRR, and recall@1** (`benchmarks/rrf-ab/results-scale-linear-vs-rrf.txt`). Two possible explanations: (a) we implemented RRF wrong, or (b) we hit the known tradeoff where a tuned score combination beats tuning-free RRF. This note establishes that **both are true**, and what to do about it.

## Why RRF exists (the actual benefit)

RRF fuses rankers by rank position instead of score: `RRFscore(d) = Σ_r w_r / (k + rank_r(d))`. It solves exactly one problem, and solves it well: **combining rankers whose scores live on incompatible scales, with zero tuning and no labeled data.**

- BM25 (`ts_rank`, unbounded, corpus-dependent) and cosine (0 to 1) cannot be summed directly; score normalization (min-max, z-score) is brittle because one outlier compresses everything else.
- RRF discards magnitude and fuses on rank, so it "just works" across heterogeneous retrievers out of the box.
- Origin: Cormack, Clarke & Büttcher, SIGIR 2009. They built RRF as a *baseline* and it beat every individual system, Condorcet Fuse, and CombMNZ by ~4-5% on TREC/LETOR data. `k=60` "was fixed during a pilot investigation… but the choice was not critical" (flat from k≈30 to k≈100).

That is why RRF is the safe default in OpenSearch and Azure AI Search, and an opt-in everywhere else.

## The modern caveat that explains our result

Cormack 2009 was metaranking of homogeneous TREC systems. The directly relevant regime is hybrid lexical+dense retrieval, analyzed definitively by **Bruch, Gai & Ingber, "An Analysis of Fusion Functions for Hybrid Retrieval" (arXiv 2210.11934, ACM TOIS 2023)**:

- A tuned **convex combination (CC) of normalized scores outperforms RRF in in-domain AND out-of-domain settings.**
- **RRF is "sensitive to its parameters"**, directly contradicting its tune-free reputation in the hybrid setting.
- CC needs only a small labeled set to tune its one parameter, and is largely agnostic to the normalization choice.

**This is our result.** pg-raggraph's linear mode is a weighted score combination (`w_sem*cos + w_bm25*ts_rank`, with `tune_scoring_weights()` to fit per corpus). On a corpus with strong, well-calibrated embeddings, the magnitude RRF throws away is the good part, so tuned-ish linear wins. We reproduced the state of the art, not a bug.

## How the field implements RRF (per-system survey)

| System | RRF default? | k | Fuses each retriever's top-N (absent doc → 0)? | Weighted? |
|---|---|---|---|---|
| Elasticsearch | opt-in (`rrf` retriever) | 60 | **Yes** (`if d in result(q)`) | No (equal) |
| OpenSearch | opt-in (pipeline) | 60 | **Yes** (missing → 0.0) | Roadmap |
| Weaviate | was default ≤1.23; score-norm default since 1.24 | 60 | **Yes** (rankedFusion) | Yes (`alpha`) |
| Qdrant | opt-in (Query API) | **2** | **Yes** (per-prefetch) | Yes (≥1.17) |
| Vespa | author-defined expr | 60 | **Yes** (global-phase top-N) | Yes (free-form) |
| Azure AI Search | **default** | 60 | **Yes** ("each result set where it shows up") | Yes (vector weight) |
| pgvector community (TigerData, ParadeDB, Katz) | opt-in, hand-rolled SQL | 60 | **Yes** (`LEFT/FULL JOIN` + `COALESCE(1/(60+rank),0)`) | both |

**The universal invariant:** every system fuses each retriever's **independent** returned top-N, and a document absent from retriever X's list gets **zero** contribution from X. None of them rank one shared candidate set two ways. `k=60` is the near-universal constant (Qdrant's 2 is the outlier).

## What pg-raggraph got RIGHT

- `rrf_k=60`, the universal default.
- **Weighted legs**, we multiply the RRF terms by per-leg weights. More expressive than Elasticsearch/OpenSearch (equal-weight only); matches the Qdrant/Weaviate/Vespa/Azure direction.
- **Opt-in, default-off**, matches Elasticsearch/OpenSearch/Qdrant/Vespa.
- **Linear as the default**, this is the Bruch-et-al-endorsed higher-ceiling choice. We are not behind by defaulting to linear.

## What pg-raggraph got WRONG (the real divergence)

Our shipped naive RRF (`_build_naive_query_twostage_rrf`, the default path with `two_stage_retrieval=True`, `candidate_k=200`) builds **one vector-seeded candidate pool** and ranks it two ways:

```sql
WITH candidates AS (SELECT ... ORDER BY embedding <=> q LIMIT 200),   -- vector-only
     scored AS (SELECT ..., vec_score, bm25_score FROM candidates),
     ranked AS (SELECT *, rank() OVER (ORDER BY vec_score DESC),
                          rank() OVER (ORDER BY bm25_score DESC) FROM scored)
```

This violates the universal invariant in two ways, both confirmed empirically on the live 1700-doc corpus:

1. **The BM25 leg is captive to the vector pool.** It can never surface a strong lexical match the embedding missed, the signature strength of RRF. (Damage is small *here* because vector recall is high: the BM25 top-10 is mostly already inside the vector top-200, 0-4 of 10 missed across sampled queries. On a corpus with weaker embeddings it would be severe.)
2. **Zero-BM25 docs get a tied, noisy rank instead of zero.** 75-131 of the 200 candidates (38-66%) have `bm25_score = 0` for a typical query. SQL `rank()` ties them all at one middling rank, so they inject a uniform, meaningless BM25 term into an already-good vector ranking. This is most of why RRF reorders 99/100 and lands slightly worse: the BM25-rank term is mostly noise, not signal.

The fix is the universal pattern: run vector top-N **and** BM25 top-N independently from the whole corpus, fuse with a `FULL OUTER JOIN`, and `COALESCE(w/(k+rank), 0)` so an absent doc contributes zero. That removes the tie-noise and lets BM25 surface its own finds.

## The fair measurement (3-way)

`benchmarks/rrf-ab/run_rrf_ab_proper.py` runs linear vs captive-RRF (shipped) vs proper-RRF (independent legs, FULL OUTER JOIN, COALESCE-to-zero) on the same 1700-doc corpus, same weights, same `k=60`.

Same corpus (1700 docs), same 100 questions, same weights (`w_sem=0.5, w_bm25=0.2`), same `k=60`. Result (`results-proper-3way.txt`):

| metric | linear | rrf (captive, shipped) | rrf (proper, FULL OUTER JOIN) |
|---|---:|---:|---:|
| nDCG@10 | **0.5581** | 0.5308 | 0.5146 |
| MRR | **0.7809** | 0.7300 | 0.7112 |
| recall@1 | **0.6600** | 0.6100 | 0.5800 |
| recall@10 | 0.9600 | 0.9600 | 0.9600 |
| latency/q | 80 ms | 77 ms | **30 ms** |

**The surprise: proper RRF is WORSE than our captive RRF, not better.** `linear > captive > proper`. Building it the standard way did not close the gap; it widened it.

**Why this is actually consistent, not contradictory.** The captive pool was accidentally *protecting* RRF. By restricting BM25 to the vector-relevant top-200, it limited how much lexical noise BM25 could inject. The proper version gives BM25 its own full-corpus top-100, and on MuSiQue (multi-hop QA over Wikipedia) BM25 surfaces many lexically-similar-but-wrong paragraphs, docs that share an entity name with the question but do not answer it. At equal rank-footing those now get real RRF mass and push the strong vector hits down. The proper implementation faithfully gives the *weaker leg on this corpus* more reach, so it loses more.

This sharpens the conclusion: **the implementation was never the reason RRF lost.** All three rank-fusion variants (captive and proper) trail linear, because linear keeps BM25's contribution both small (`w_bm25=0.2`) and magnitude-aware, adding the sliver of lexical signal that helps without the rank-noise. RRF discards the calibrated vector magnitude that is the actual signal here, exactly as Bruch et al. predict. (Latency footnote: proper RRF is the cheapest of the three at 30 ms, two clean indexed queries instead of a candidate-and-rescore. So if RRF were ever the right tool, the proper form is also the fast form. It just is not the right tool on this corpus.)

**Caveat:** one corpus, same weights across all three. A different weighting (lower `w_bm25` in rank space), a different `k`, or a corpus where BM25 is the stronger leg could move the proper-vs-captive ordering. What is robust across every variant we ran: none beat tuned linear on strong-embedding multi-hop QA.

## Bottom line

- **Linear beating RRF is the expected SOTA outcome** (Bruch et al.): a tuned score combination beats tuning-free RRF on calibrated signals. Our default is the right default.
- **Our RRF is built non-standardly** (captive single-pool fusion), which is a real divergence worth fixing for correctness and for corpora with weak vector recall. But it was NOT the reason RRF lost: the standard implementation (independent legs, FULL OUTER JOIN) scored *worse* here, because it gives the weaker lexical leg more reach to inject noise. The captive pool was accidentally limiting that damage.
- **The honest tradeoff:** RRF's pitch is "no tuning, scale-robust." Ours is "tune the weights." The research says the tuned bet has the higher ceiling, at the cost of needing labels and re-tuning per corpus. RRF earns its keep when scales are untrusted, no labels exist, and retrievers are genuinely diverse, not on MuSiQue with strong embeddings.
- **Recommendation:** keep linear as the default (endorsed by Bruch et al. and by our own three-way result). Keep RRF as the opt-in it already is. If we invest in RRF further, the highest-value change is a proper independent-leg implementation gated for the case it actually helps (untrusted scales / weak embeddings / genuinely diverse retrievers), not as a contender for the default on clean dense-retrieval corpora.

## Sources

1. Cormack, Clarke, Büttcher. *Reciprocal Rank Fusion outperforms Condorcet and individual Rank Learning Methods.* SIGIR 2009. https://cormack.uwaterloo.ca/cormacksigir09-rrf.pdf
2. Bruch, Gai, Ingber. *An Analysis of Fusion Functions for Hybrid Retrieval.* arXiv 2210.11934 / ACM TOIS 2023. https://arxiv.org/abs/2210.11934
3. OpenSearch. *Introducing reciprocal rank fusion for hybrid search.* https://opensearch.org/blog/introducing-reciprocal-rank-fusion-hybrid-search/
4. Elasticsearch. *Reciprocal rank fusion.* https://www.elastic.co/docs/reference/elasticsearch/rest-apis/reciprocal-rank-fusion
5. Weaviate. *Hybrid search concepts (rankedFusion vs relativeScoreFusion).* https://docs.weaviate.io/weaviate/concepts/search/hybrid-search
6. Qdrant. *Hybrid queries (RRF, weighted RRF, DBSF).* https://qdrant.tech/documentation/search/hybrid-queries/
7. Vespa. *Phased ranking (reciprocal_rank_fusion).* https://docs.vespa.ai/en/ranking/phased-ranking.html
8. Azure AI Search. *Hybrid search scoring (RRF).* https://learn.microsoft.com/en-us/azure/search/hybrid-search-ranking
9. BigDataBoutique. *Reciprocal Rank Fusion: How It Works and When to Use It.* https://bigdataboutique.com/blog/reciprocal-rank-fusion-how-it-works-and-when-to-use-it
10. TigerData. *Elasticsearch's Hybrid Search, Now in Postgres (BM25 + Vector + RRF).* https://www.tigerdata.com/blog/elasticsearchs-hybrid-search-now-in-postgres-bm25-vector-rrf
