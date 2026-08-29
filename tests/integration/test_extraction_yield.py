"""Extraction-yield gate: cheap, always-on evidence that extraction produced
a plausible graph.

Guards the issue #93 incident class — extraction silently under-yielding
(111 entities landed where ~1,004 belonged) behind green checkmarks. The
deterministic ``lede_prose`` extractor (spaCy NER + noun-chunk heads +
co-occurrence, no LLM) is run over the committed graph_wins fixture corpus
and the resulting entity/relationship counts must land inside a tolerance
band around a measured baseline.

Baseline (calibrated 2026-07-07, en_core_web_sm + fact_extractor=lede_prose,
3 identical runs): 3 documents -> 39 chunks -> 172 entities, 437
relationships. The path is deterministic for a fixed spaCy model, so the
band is generous (0.6x-1.6x): it tolerates legitimate drift from spaCy
model or chunker upgrades while failing hard on order-of-magnitude yield
collapse (the #93 class: 111/1004 = 0.11x) or runaway duplication.

If this test fails after an intentional extractor/chunker/model change,
recalibrate: ingest tests/fixtures/graph_wins_corpus with
fact_extractor="lede_prose", record the new counts, and update the baseline
constants with a note in the commit message. Do NOT widen the band.
"""

import pytest

from pg_raggraph import GraphRAG

pytestmark = pytest.mark.integration

_DSN = "postgresql://postgres:postgres@localhost:5434/pg_raggraph"
_NS = "test_extraction_yield"

# Measured baseline — see module docstring for calibration provenance.
_BASELINE_ENTITIES = 172
_BASELINE_RELATIONSHIPS = 437
_BAND_LOW = 0.6
_BAND_HIGH = 1.6

# Proper nouns that dominate the corpus; lede_prose must lift every one of
# these regardless of minor model drift. Catches "extraction ran but parsed
# garbage" even when raw counts stay in band.
_ANCHOR_ENTITIES = {
    "Authentication Service",
    "Payment Service",
    "Lisa Wang",
    "Sarah Chen",
    "Kong",
}


def _model_available() -> bool:
    try:
        import lede  # noqa: F401
        import lede_spacy  # noqa: F401
        import spacy

        spacy.load("en_core_web_sm")
        return True
    except Exception:
        return False


@pytest.mark.skipif(
    not _model_available(),
    reason="lede / lede-spacy / en_core_web_sm not available",
)
async def test_lede_prose_yield_on_fixture_corpus():
    import os

    corpus = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "fixtures", "graph_wins_corpus"
    )
    rag = GraphRAG(dsn=_DSN, namespace=_NS, fact_extractor="lede_prose", llm_base_url="")
    await rag.connect()
    try:
        await rag.delete(_NS)
        await rag.ingest([corpus], namespace=_NS)

        docs = (
            await rag.db.fetch_one(
                "SELECT COUNT(*) AS n FROM documents WHERE namespace=%s", (_NS,)
            )
        )["n"]
        assert docs == 3, f"fixture corpus is 3 markdown files, ingested {docs}"

        entities = (
            await rag.db.fetch_one("SELECT COUNT(*) AS n FROM entities WHERE namespace=%s", (_NS,))
        )["n"]
        relationships = (
            await rag.db.fetch_one(
                "SELECT COUNT(*) AS n FROM relationships WHERE namespace=%s", (_NS,)
            )
        )["n"]

        lo_e = int(_BASELINE_ENTITIES * _BAND_LOW)
        hi_e = int(_BASELINE_ENTITIES * _BAND_HIGH)
        assert lo_e <= entities <= hi_e, (
            f"entity yield {entities} outside [{lo_e}, {hi_e}] "
            f"(baseline {_BASELINE_ENTITIES}) — extraction is under- or "
            "over-yielding; see module docstring before touching the band"
        )
        lo_r = int(_BASELINE_RELATIONSHIPS * _BAND_LOW)
        hi_r = int(_BASELINE_RELATIONSHIPS * _BAND_HIGH)
        assert lo_r <= relationships <= hi_r, (
            f"relationship yield {relationships} outside [{lo_r}, {hi_r}] "
            f"(baseline {_BASELINE_RELATIONSHIPS})"
        )

        names = {
            r["name"]
            for r in await rag.db.fetch_all("SELECT name FROM entities WHERE namespace=%s", (_NS,))
        }
        missing = _ANCHOR_ENTITIES - names
        assert not missing, f"anchor entities missing from extraction: {sorted(missing)}"
    finally:
        await rag.delete(_NS)
        await rag.close()
