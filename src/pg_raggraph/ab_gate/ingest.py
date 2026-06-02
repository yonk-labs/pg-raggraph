"""A/B-gate entity materialization.

The chunkshop bridge (``pg_raggraph.chunkshop_bridge``) imports chunkshop's
emission table into pg-raggraph's ``chunks`` table — preserving
``metadata.kind`` / ``subject`` / ``object`` / ``cooccur``. But the graph leg
of the A/B harness (``ab_gate.harness._run_graph_leg``) resolves question
terms against pg-raggraph's ``entities`` table, which the bridge never
populates.

``materialize_entities_from_corpus`` closes that gap: it reads every distinct
fact-endpoint surface (``subject`` / ``object`` on ``kind='fact'`` chunks) and
cooccur node (``a`` / ``b`` in ``metadata['cooccur']`` on ``kind='episode'``
chunks), embeds them, and inserts one entity per distinct surface.

**Why 1:1 (no fuzzy collapse at materialization time):** the harness fact walk
joins ``metadata->>'subject' = ANY(canonical_names)``. If materialization
collapsed "Apple"/"Apple Inc." into a single canonical name, every fact whose
subject string differed from that canonical would become unreachable — silently
handicapping the graph leg. Keeping entities 1:1 with distinct surfaces means
query-time ``resolve_entity_lookup`` does the collapsing (fuzzy-matching a
question term onto the nearest surface), which is the fair design for the gate.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pg_raggraph import GraphRAG

logger = logging.getLogger("pg_raggraph.ab_gate.ingest")

# Distinct fact-endpoint surfaces: subject + object from kind='fact' chunks.
_FACT_SURFACES_SQL = """
SELECT DISTINCT val
FROM chunks c
JOIN documents d ON d.id = c.document_id
CROSS JOIN LATERAL (
    VALUES (c.metadata->>'subject'), (c.metadata->>'object')
) AS t(val)
WHERE d.namespace = %(namespace)s
  AND c.metadata->>'kind' = 'fact'
  AND val IS NOT NULL
  AND length(trim(val)) > 0
"""

# Distinct cooccur-node surfaces: a + b from metadata['cooccur'] on episodes.
_COOCCUR_SURFACES_SQL = """
SELECT DISTINCT val
FROM chunks c
JOIN documents d ON d.id = c.document_id
CROSS JOIN LATERAL jsonb_array_elements(
    COALESCE(c.metadata->'cooccur', '[]'::jsonb)
) co(value)
CROSS JOIN LATERAL (
    VALUES (co.value->>'a'), (co.value->>'b')
) AS t(val)
WHERE d.namespace = %(namespace)s
  AND c.metadata->>'kind' = 'episode'
  AND val IS NOT NULL
  AND length(trim(val)) > 0
"""

_INSERT_ENTITY_SQL = (
    "INSERT INTO entities (namespace, name, entity_type, description, embedding, properties) "
    "VALUES (%s, %s, %s, %s, %s, %s::jsonb) "
    "ON CONFLICT (namespace, name) DO NOTHING"
)


async def _distinct_surfaces(rag: "GraphRAG", corpus_id: str) -> list[str]:
    """Union of distinct fact-endpoint + cooccur-node surfaces for the corpus."""
    fact_rows = await rag.db.fetch_all(_FACT_SURFACES_SQL, {"namespace": corpus_id})
    cooccur_rows = await rag.db.fetch_all(_COOCCUR_SURFACES_SQL, {"namespace": corpus_id})
    surfaces: set[str] = set()
    for row in list(fact_rows) + list(cooccur_rows):
        val = (row["val"] or "").strip()
        if val:
            surfaces.add(val)
    # Sorted for deterministic embedding order (helps reproducibility + caching).
    return sorted(surfaces)


async def materialize_entities_from_corpus(
    rag: "GraphRAG",
    corpus_id: str,
    *,
    entity_type: str = "ab_node",
    embed_batch: int = 256,
) -> int:
    """Materialize pg-raggraph entities from a corpus's fact + cooccur surfaces.

    Idempotent: re-running inserts only surfaces not already present
    (``ON CONFLICT (namespace, name) DO NOTHING``).

    Parameters
    ----------
    rag:
        Connected ``GraphRAG`` whose configured embedder dims match the
        corpus's chunk embeddings.
    corpus_id:
        The namespace to materialize. Identity-equal to the chunkshop corpus.
    entity_type:
        Stored on ``entities.entity_type`` for the materialized nodes.
    embed_batch:
        Surface count per embedding batch (keeps memory bounded on large corpora).

    Returns
    -------
    int
        Number of entities actually inserted this call (excludes ON CONFLICT
        skips). A second run on an unchanged corpus returns 0.
    """
    surfaces = await _distinct_surfaces(rag, corpus_id)
    if not surfaces:
        logger.warning(
            "no fact/cooccur surfaces found for corpus %r — graph_leg will be empty. "
            "Did the chunkshop bridge import preserve metadata.kind / subject / cooccur?",
            corpus_id,
        )
        return 0

    embedder = rag._get_embedder()
    before = await rag.db.fetch_one(
        "SELECT count(*) AS n FROM entities WHERE namespace = %s", (corpus_id,)
    )
    before_n = before["n"] if before else 0

    props = json.dumps({"source": "ab_gate_materialize"})
    for start in range(0, len(surfaces), embed_batch):
        batch = surfaces[start : start + embed_batch]
        embeddings = await rag._embed_texts_with_cache(batch, embedder)
        async with rag.db.transaction() as tx:
            for surface, emb in zip(batch, embeddings):
                await tx.execute(
                    _INSERT_ENTITY_SQL,
                    (corpus_id, surface, entity_type, "", emb, props),
                )
        logger.info(
            "materialized %d/%d surfaces for %r",
            min(start + embed_batch, len(surfaces)),
            len(surfaces),
            corpus_id,
        )

    after = await rag.db.fetch_one(
        "SELECT count(*) AS n FROM entities WHERE namespace = %s", (corpus_id,)
    )
    after_n = after["n"] if after else 0
    inserted = after_n - before_n
    logger.info("materialized %d new entities for corpus %r", inserted, corpus_id)
    return inserted
