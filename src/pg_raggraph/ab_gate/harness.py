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


def _encode_question_terms(question: str) -> list[str]:
    """Encode question terms via lede_spacy NER, falling back on raise/empty.

    The fallback covers two cases: lede_spacy not installed (raises) and
    the NER finding no entities (returns []). In both, we'd rather have
    whitespace tokens than zero terms — the graph_leg walk degrades
    gracefully into a noisy lookup instead of returning empty.

    Logs a warning on fallback so operators notice.
    """
    if not question or not question.strip():
        return []
    try:
        entities = _lede_spacy_entities(question)
    except Exception as exc:  # noqa: BLE001 — broad on purpose for fallback
        logger.warning("lede_spacy NER failed (%s); falling back to whitespace + stoplist", exc)
        return _fallback_whitespace_terms(question)
    if entities:
        return entities
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
            raise NotImplementedError("hybrid mode lands in Task 6 (or stays NotImplementedError)")
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
            )
        )
    return ABRunnerOutput(corpus_id=corpus_id, mode=mode, results=results)
