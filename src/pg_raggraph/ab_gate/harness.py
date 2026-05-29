"""A/B Gate retrieval harness — #48.

One entry point: ``run_harness_mode(rag, corpus_id, mode, gold_questions, top_k)``
returning an :class:`ABRunnerOutput`. Three modes:

- ``naive_vector`` — pure ANN over chunks, fact rows excluded per chunkshop §4.2.
- ``graph_leg`` — entity-resolve question terms via #47, walk fact triples and
  cooccur edges, return the episode chunks carrying those facts.
- ``hybrid`` — optional 50/50 blend. SC-007 explicitly allows shipping with
  ``NotImplementedError`` if scope grows.

The harness reads the chunkshop-emitted row set verbatim — no shape
transformation, no re-indexing. Per the brief's P1 constraint.

Question-term encoding (used by ``graph_leg``) goes through ``lede_spacy``'s
NER backend so ingest and query share the same entity definition. A
whitespace+stoplist fallback covers environments where lede_spacy isn't
installed (operator sees a warning, not a crash).
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Literal

from pg_raggraph.ab_gate.io import (
    ABCaseResult,
    ABRetrievedItem,
    ABRunnerOutput,
    GoldQuestion,
)
from pg_raggraph.resolution import ResolvedEntity, resolve_entity_lookup

if TYPE_CHECKING:
    from pg_raggraph import GraphRAG

logger = logging.getLogger("pg_raggraph.ab_gate.harness")

Mode = Literal["naive_vector", "graph_leg", "hybrid"]


# SQL for naive_vector mode.
#
# Mirrors the shape of _build_naive_vector_first in retrieval.py:366, stripped
# of the evolution / weighted-rerank logic the production retriever needs.
# The single new clause is chunkshop §4.2:
#
#     AND c.metadata->>'kind' IS DISTINCT FROM 'fact'
#
# DC-002 enforces ``IS DISTINCT FROM``, not ``!=`` — those differ on NULL.
# A chunk with no 'kind' metadata key (legacy / non-chunkshop ingest) MUST
# still be returned; ``!= 'fact'`` would drop it.
_NAIVE_VECTOR_SQL = """
SELECT
    c.id,
    COALESCE(c.embedded_content, c.content) AS content,
    d.source_path,
    1 - (c.embedding <=> %(embedding)s::vector) AS score
FROM chunks c
JOIN documents d ON d.id = c.document_id
WHERE d.namespace = %(namespace)s
  AND c.metadata->>'kind' IS DISTINCT FROM 'fact'
ORDER BY c.embedding <=> %(embedding)s::vector
LIMIT %(top_k)s
"""

# Fact-triple walk for graph_leg mode.
#
# Per chunkshop §4.2: fact rows have ``metadata->>'kind' = 'fact'`` with keys
# ``subject``, ``predicate``, ``object``. The walk pivots from a resolved
# entity name to fact rows naming the entity in either ``subject`` or
# ``object``, then joins to the *parent episode* chunk for citation — the
# fact row itself is never cited (chunkshop §4.2 / SC-006).
_GRAPH_LEG_FACT_SQL = """
WITH facts AS (
    SELECT DISTINCT c.document_id
    FROM chunks c
    JOIN documents d ON d.id = c.document_id
    WHERE d.namespace = %(namespace)s
      AND c.metadata->>'kind' = 'fact'
      AND (
          c.metadata->>'subject' = ANY(%(names)s)
          OR c.metadata->>'object' = ANY(%(names)s)
      )
)
SELECT
    ep.id,
    COALESCE(ep.embedded_content, ep.content) AS content,
    d.source_path,
    1.0::float AS score
FROM facts f
JOIN chunks ep ON ep.document_id = f.document_id
              AND ep.metadata->>'kind' = 'episode'
JOIN documents d ON d.id = ep.document_id
LIMIT %(top_k)s
"""

# Cooccur walk for graph_leg mode.
#
# Per chunkshop §4.2: cooccur lives on episode rows in ``metadata['cooccur']``
# as an array of ``{a, b, weight}`` objects. The walk pivots from a resolved
# entity name to episode rows whose cooccur array names the entity on either
# the ``a`` or ``b`` side.
_GRAPH_LEG_COOCCUR_SQL = """
SELECT
    c.id,
    COALESCE(c.embedded_content, c.content) AS content,
    d.source_path,
    COALESCE((co.value->>'weight')::float, 0.5) AS score
FROM chunks c
JOIN documents d ON d.id = c.document_id
CROSS JOIN LATERAL jsonb_array_elements(
    COALESCE(c.metadata->'cooccur', '[]'::jsonb)
) co(value)
WHERE d.namespace = %(namespace)s
  AND c.metadata->>'kind' = 'episode'
  AND (
      co.value->>'a' = ANY(%(names)s)
      OR co.value->>'b' = ANY(%(names)s)
  )
ORDER BY score DESC
LIMIT %(top_k)s
"""


# Hybrid mode (vector-seeds + graph-rerank).
#
# Per chunkshop §4.2, hybrid is the production-shaped mode: the vector leg
# seeds a candidate set, then the graph reranks those candidates by entity
# overlap. Crucially it does NOT entity-resolve the question (graph_leg's
# weak-NER failure), only the retrieved chunks. We pull a wider vector seed
# (top_k × _HYBRID_SEED_MULT) with document_id, then fetch each seed doc's
# fact endpoints + cooccur nodes and boost docs that share entities with
# OTHER seed docs (topical centrality within the retrieved set).
_HYBRID_SEED_MULT = 3
_HYBRID_GRAPH_WEIGHT = 0.5

_HYBRID_SEED_SQL = """
SELECT
    c.id,
    c.document_id,
    COALESCE(c.embedded_content, c.content) AS content,
    d.source_path,
    1 - (c.embedding <=> %(embedding)s::vector) AS score
FROM chunks c
JOIN documents d ON d.id = c.document_id
WHERE d.namespace = %(namespace)s
  AND c.metadata->>'kind' IS DISTINCT FROM 'fact'
ORDER BY c.embedding <=> %(embedding)s::vector
LIMIT %(seed_k)s
"""

# Fact endpoints + cooccur nodes for a set of seed documents (for centrality).
_HYBRID_DOC_NODES_SQL = """
SELECT c.document_id, val
FROM chunks c
JOIN documents d ON d.id = c.document_id
CROSS JOIN LATERAL (VALUES (c.metadata->>'subject'), (c.metadata->>'object')) AS f(val)
WHERE d.namespace = %(namespace)s
  AND c.metadata->>'kind' = 'fact'
  AND c.document_id = ANY(%(doc_ids)s)
  AND val IS NOT NULL AND length(trim(val)) > 0
UNION ALL
SELECT c.document_id, co.value->>'a'
FROM chunks c
JOIN documents d ON d.id = c.document_id
CROSS JOIN LATERAL jsonb_array_elements(COALESCE(c.metadata->'cooccur', '[]'::jsonb)) co(value)
WHERE d.namespace = %(namespace)s
  AND c.metadata->>'kind' = 'episode'
  AND c.document_id = ANY(%(doc_ids)s)
  AND co.value->>'a' IS NOT NULL AND length(trim(co.value->>'a')) > 0
UNION ALL
SELECT c.document_id, co.value->>'b'
FROM chunks c
JOIN documents d ON d.id = c.document_id
CROSS JOIN LATERAL jsonb_array_elements(COALESCE(c.metadata->'cooccur', '[]'::jsonb)) co(value)
WHERE d.namespace = %(namespace)s
  AND c.metadata->>'kind' = 'episode'
  AND c.document_id = ANY(%(doc_ids)s)
  AND co.value->>'b' IS NOT NULL AND length(trim(co.value->>'b')) > 0
"""


# Stopwords for the whitespace fallback. Kept short — the fallback is
# already a degraded path; aggressive stopping would drop entities too.
_FALLBACK_STOPWORDS = frozenset(
    {
        "a", "an", "the", "and", "or", "but", "if", "of", "in", "on", "at",
        "to", "for", "from", "by", "with", "is", "are", "was", "were", "be",
        "been", "being", "do", "does", "did", "doing", "have", "has", "had",
        "having", "what", "which", "who", "whom", "whose", "where", "when",
        "why", "how", "this", "that", "these", "those", "i", "you", "he",
        "she", "it", "we", "they", "say", "said", "says", "saying", "about",
    }
)  # fmt: skip


def _lede_spacy_entities(text: str) -> list[str]:
    """Wrap lede_spacy's NER call so it can be patched in tests.

    Reuses the same backend the ``fact_extractor="lede_spacy"`` ingest
    path uses (see ``src/pg_raggraph/lede_extraction.py``). Symmetric
    ingest/query encoding is the whole point — see chunkshop §4.2.
    """
    import lede
    import lede_spacy  # noqa: F401  (registers the spacy backend on import)

    if not text.strip():
        return []
    raw = lede.extract.metadata(text, backend="spacy").entities
    out: list[str] = []
    seen: set[str] = set()
    for name in raw:
        name = (name or "").strip()
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        out.append(name)
    return out


def _fallback_whitespace_terms(text: str) -> list[str]:
    """Whitespace + stoplist fallback for environments without lede_spacy.

    Splits on whitespace, drops empties and stopwords, dedupes case-
    insensitively (first-seen casing wins). Punctuation at edges is
    stripped. Not as good as NER — that's the point; the warning in
    the caller tells the operator to install lede_spacy for quality.
    """
    if not text or not text.strip():
        return []
    out: list[str] = []
    seen: set[str] = set()
    for raw in text.split():
        tok = raw.strip(".,;:!?\"'()[]{}")
        if not tok:
            continue
        low = tok.lower()
        if low in _FALLBACK_STOPWORDS:
            continue
        if low in seen:
            continue
        seen.add(low)
        out.append(tok)
    return out


def _expand_entity_terms(entities: list[str]) -> list[str]:
    """Expand NER noun phrases into resolvable terms.

    lede_spacy NER yields full phrases ("Bostock v. Clayton County"), but the
    materialized entity nodes are single surfaces ("Bostock", "Clayton County").
    A full-phrase lookup resolves to nothing, so we emit BOTH the full phrase
    (it might exact-match a multi-word node) AND each component word-token (so
    "Bostock" / "Clayton" / "County" can resolve individually).

    Dedup is case-insensitive, first-seen wins. Edge punctuation is stripped;
    stopwords and single-character joiners (the "v" in "X v. Y") are dropped.
    """
    out: list[str] = []
    seen: set[str] = set()

    def _add(term: str) -> None:
        term = term.strip(".,;:!?\"'()[]{} ")
        if len(term) < 2:
            return
        low = term.lower()
        if low in seen or low in _FALLBACK_STOPWORDS:
            return
        seen.add(low)
        out.append(term)

    for ent in entities:
        if not ent or not ent.strip():
            continue
        _add(ent)  # full phrase — may exact-match a multi-word node
        for token in ent.split():  # component words — resolve individually
            _add(token)
    return out


def _encode_question_terms(question: str) -> list[str]:
    """Encode question terms via lede_spacy NER, falling back on raise/empty.

    On a successful NER pass, multi-word entities are expanded into their
    component tokens (see ``_expand_entity_terms``) so they resolve against
    the single-surface entity nodes graph_leg walks.

    The whitespace fallback covers two cases: lede_spacy not installed
    (raises) and NER finding no entities (returns []). In both, whitespace
    tokens beat zero terms — the walk degrades into a noisy lookup instead
    of returning empty. Logs a warning on fallback so operators notice.
    """
    if not question or not question.strip():
        return []
    try:
        entities = _lede_spacy_entities(question)
    except Exception as exc:  # noqa: BLE001 — broad on purpose for fallback
        logger.warning("lede_spacy NER failed (%s); falling back to whitespace + stoplist", exc)
        return _fallback_whitespace_terms(question)
    if entities:
        return _expand_entity_terms(entities)
    logger.warning("lede_spacy NER returned no entities; using whitespace fallback")
    return _fallback_whitespace_terms(question)


async def _run_naive_vector(
    rag: "GraphRAG",
    *,
    corpus_id: str,
    question: str,
    top_k: int,
) -> list[ABRetrievedItem]:
    """Pure ANN over chunks, excluding fact rows.

    Reuses the rag's configured embedder so dims line up with the
    ingested chunks. Returns 1-indexed ABRetrievedItems ordered by
    score DESC.
    """
    embedder = rag._get_embedder()
    [embedding] = await embedder.embed([question])
    rows = await rag.db.fetch_all(
        _NAIVE_VECTOR_SQL,
        {"embedding": embedding, "namespace": corpus_id, "top_k": top_k},
    )
    items: list[ABRetrievedItem] = []
    for rank, row in enumerate(rows, start=1):
        source = row["source_path"] or f"{corpus_id}:chunk:{row['id']}"
        items.append(
            ABRetrievedItem(
                rank=rank,
                source=source,
                score=float(row["score"]),
                content_snippet=row["content"] or "",
            )
        )
    return items


async def _resolve_question_entities(
    rag: "GraphRAG",
    *,
    corpus_id: str,
    terms: list[str],
) -> list[ResolvedEntity]:
    """Resolve each question term via #47's resolve_entity_lookup.

    Returns only the resolved hits (drops Nones). Order preserves the
    encoder's term order so downstream walks have a stable iteration.
    """
    resolved: list[ResolvedEntity] = []
    for surface in terms:
        hit = await resolve_entity_lookup(
            surface,
            corpus_id=corpus_id,
            db=rag.db,
            config=rag.config,
        )
        if hit is not None:
            resolved.append(hit)
    return resolved


async def _run_graph_leg(
    rag: "GraphRAG",
    *,
    corpus_id: str,
    question: str,
    top_k: int,
) -> list[ABRetrievedItem]:
    """Entity-resolve → walk fact triples + cooccur edges → episode chunks.

    Two walks run in sequence (fact-triple, then cooccur). Results are
    merged by document, deduped by source_path, capped at top_k, ranked
    by aggregated score (fact-walk = 1.0 per match; cooccur = the edge
    weight). Only episode chunks are cited — SC-006.
    """
    terms = _encode_question_terms(question)
    resolved = await _resolve_question_entities(rag, corpus_id=corpus_id, terms=terms)
    if not resolved:
        return []
    # Use canonical_name (entity table's name field) as the join key, since
    # facts/cooccur store surface strings that the resolver already
    # normalized to canonical_name during entity ingest.
    names = [r.canonical_name for r in resolved]

    fact_rows = await rag.db.fetch_all(
        _GRAPH_LEG_FACT_SQL,
        {"namespace": corpus_id, "names": names, "top_k": top_k},
    )
    cooccur_rows = await rag.db.fetch_all(
        _GRAPH_LEG_COOCCUR_SQL,
        {"namespace": corpus_id, "names": names, "top_k": top_k},
    )

    # Merge by source_path. Sum scores when an episode surfaces from both
    # walks so dual-evidence episodes outrank single-evidence ones.
    merged: dict[str, tuple[float, str]] = {}
    for row in list(fact_rows) + list(cooccur_rows):
        src = row["source_path"] or f"{corpus_id}:chunk:{row['id']}"
        score = float(row["score"])
        if src in merged:
            prev_score, prev_content = merged[src]
            merged[src] = (prev_score + score, prev_content)
        else:
            merged[src] = (score, row["content"] or "")

    # Order by aggregate score DESC and cap at top_k.
    ranked = sorted(merged.items(), key=lambda kv: kv[1][0], reverse=True)[:top_k]
    return [
        ABRetrievedItem(
            rank=rank,
            source=src,
            score=score,
            content_snippet=content,
        )
        for rank, (src, (score, content)) in enumerate(ranked, start=1)
    ]


def _blend_hybrid_candidates(
    candidates: list[dict],
    doc_to_nodes: dict,
    *,
    top_k: int,
    graph_weight: float,
) -> list[ABRetrievedItem]:
    """Rerank vector candidates by graph centrality (pure, deterministic).

    centrality(doc) = Σ over the doc's fact/cooccur nodes of (how many OTHER
    seed docs also carry that node) — i.e. topical overlap within the
    retrieved set. Blended score = (1-w)·norm(vector) + w·norm(centrality).
    Empty graph signal (no shared nodes / no nodes) degrades to pure vector
    order, so hybrid never does worse than naive on the seed it was given.
    """
    if not candidates:
        return []

    # node → number of distinct seed docs containing it.
    node_doc_freq: dict[str, int] = {}
    for nodes in doc_to_nodes.values():
        for n in nodes:
            node_doc_freq[n] = node_doc_freq.get(n, 0) + 1

    def _centrality(doc_id) -> float:
        nodes = doc_to_nodes.get(doc_id, set())
        return float(sum(node_doc_freq.get(n, 0) - 1 for n in nodes))

    vmax = max(c["vector_score"] for c in candidates) or 1.0
    vmin = min(c["vector_score"] for c in candidates)
    vrange = (vmax - vmin) or 1.0
    cents = {c["document_id"]: _centrality(c["document_id"]) for c in candidates}
    cmax = max(cents.values()) or 1.0

    scored = []
    for c in candidates:
        vnorm = (c["vector_score"] - vmin) / vrange
        cnorm = cents[c["document_id"]] / cmax if cmax else 0.0
        blended = (1.0 - graph_weight) * vnorm + graph_weight * cnorm
        scored.append((blended, c))
    # Stable sort: ties keep vector order (candidates arrive vector-sorted).
    scored.sort(key=lambda bc: bc[0], reverse=True)

    return [
        ABRetrievedItem(
            rank=rank,
            source=c["source"],
            score=round(blended, 6),
            content_snippet=c["content"] or "",
        )
        for rank, (blended, c) in enumerate(scored[:top_k], start=1)
    ]


async def _run_hybrid(
    rag: "GraphRAG",
    *,
    corpus_id: str,
    question: str,
    top_k: int,
) -> list[ABRetrievedItem]:
    """Vector-seeds + graph-rerank. See _HYBRID_* SQL + _blend_hybrid_candidates.

    The graph reranks the *retrieved chunks* by entity overlap — it never
    entity-resolves the question, so this mode is immune to graph_leg's
    weak-NER failure (chunkshop §4.2).
    """
    embedder = rag._get_embedder()
    [embedding] = await embedder.embed([question])
    seed_k = max(top_k * _HYBRID_SEED_MULT, top_k)
    seed_rows = await rag.db.fetch_all(
        _HYBRID_SEED_SQL,
        {"embedding": embedding, "namespace": corpus_id, "seed_k": seed_k},
    )
    if not seed_rows:
        return []

    candidates = [
        {
            "id": r["id"],
            "document_id": r["document_id"],
            "source": r["source_path"] or f"{corpus_id}:chunk:{r['id']}",
            "content": r["content"] or "",
            "vector_score": float(r["score"]),
        }
        for r in seed_rows
    ]

    doc_ids = list({c["document_id"] for c in candidates})
    node_rows = await rag.db.fetch_all(
        _HYBRID_DOC_NODES_SQL, {"namespace": corpus_id, "doc_ids": doc_ids}
    )
    doc_to_nodes: dict = {}
    for row in node_rows:
        val = (row["val"] or "").strip()
        if val:
            doc_to_nodes.setdefault(row["document_id"], set()).add(val)

    return _blend_hybrid_candidates(
        candidates, doc_to_nodes, top_k=top_k, graph_weight=_HYBRID_GRAPH_WEIGHT
    )


async def run_harness_mode(
    rag: "GraphRAG",
    *,
    corpus_id: str,
    mode: Mode,
    gold_questions: list[GoldQuestion],
    top_k: int = 10,
) -> ABRunnerOutput:
    """Run one (corpus, mode) cell of the A/B matrix.

    See module docstring for mode semantics. Returns one ABCaseResult
    per input GoldQuestion in the same order. Latency is measured per
    case — only the retrieval call, not setup like entity resolution
    (see SC-014 / DC-FINAL).
    """
    results: list[ABCaseResult] = []
    for gold in gold_questions:
        t0 = time.monotonic()
        if mode == "naive_vector":
            retrieved = await _run_naive_vector(
                rag, corpus_id=corpus_id, question=gold.question, top_k=top_k
            )
        elif mode == "graph_leg":
            retrieved = await _run_graph_leg(
                rag, corpus_id=corpus_id, question=gold.question, top_k=top_k
            )
        elif mode == "hybrid":
            retrieved = await _run_hybrid(
                rag, corpus_id=corpus_id, question=gold.question, top_k=top_k
            )
        else:
            raise ValueError(f"unknown harness mode: {mode!r}")
        latency_ms = (time.monotonic() - t0) * 1000.0
        results.append(
            ABCaseResult(
                question_id=gold.id,
                question=gold.question,
                gold_answer=gold.gold_answer,
                retrieved=retrieved,
                latency_ms=latency_ms,
                gold_doc_id=gold.gold_doc_id,
            )
        )
    return ABRunnerOutput(corpus_id=corpus_id, mode=mode, results=results)
