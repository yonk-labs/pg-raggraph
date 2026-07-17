"""Regression tests for #114: naive top-k must not deterministically exclude
the gold record on template-near-duplicate corpora when the query carries
rare discriminating tokens.

The failing geometry (bank_kyc fleet): N near-identical dispute records where
name/vendor cohorts are larger than top_k, 4 ticket cross-reference docs, and
a query naming the customer, vendor, unique amount, and ticket id. Under
ts_rank (no IDF) the rare tokens carry no extra weight — docs matching many
common template words outrank the one doc matching the query's discriminating
tokens, and rank among near-duplicate siblings is arbitrary-but-deterministic.
The IDF-coverage bonus (w_rare, from lexeme_stats) restores the lift.
"""

import pytest

from pg_raggraph import GraphRAG

pytestmark = pytest.mark.integration

TEST_DSN = "postgresql://postgres:postgres@localhost:5434/pg_raggraph"
NS = "test_rare_token_rank"

_VENDORS = ["Northwind Supply", "Acme Retail", "Globex Market", "Initech Store",
            "Umbrella Mart"]
_NAMES = ["Maria Ashby", "Deshawn Boudreaux", "Ines Iyer", "Silas Grady",
          "Lucia Whitfield"]
_OFFICERS = ["Officer Dana Kowalski", "Officer Miguel Serrano", "Officer Priya Nair",
             "Officer Tom Okafor", "Officer Lena Vogel", "Officer Sam Whitaker",
             "Officer Aisha Diallo", "Officer Chen Wei"]

_N = 80
_GOLD_IDX = 3  # Silas Grady / Initech Store / $103.00
GOLD = f"dsp-{_GOLD_IDX}"

QUERY = (
    "Silas Grady disputed a $103.00 charge from Initech Store "
    "(ticket TCKT-1065). Which officer approved the reversal and on what date?"
)


def _make_corpus():
    records = []
    for i in range(_N):
        content = (
            f"Dispute DSP-{1000 + i}: Account ACCT-{9000 + i} "
            f"({_NAMES[i % len(_NAMES)]}) disputed a ${100 + i}.00 charge from "
            f"{_VENDORS[i % len(_VENDORS)]} dated 2026-03-{1 + i % 28:02d}. "
            f"The cardholder reported the transaction as unauthorized and "
            f"requested a chargeback. {_OFFICERS[i % len(_OFFICERS)]} reviewed "
            f"the claim and approved the reversal on 2026-04-{1 + i % 28:02d}."
        )
        records.append({"text": content, "source_id": f"dsp-{i}"})
    gold_dsp = f"DSP-{1000 + _GOLD_IDX}"
    for j, content in enumerate([
        f"Ticket TCKT-1065: escalation opened for dispute {gold_dsp}. "
        f"Routed to the disputes queue for officer review.",
        f"Ticket TCKT-1065 audit log: status changed OPEN -> IN_REVIEW. "
        f"Linked case {gold_dsp}.",
        f"Ticket TCKT-1065 SLA record: response due within 48 hours of filing. "
        f"Case reference {gold_dsp}.",
        f"Ticket TCKT-1065 communications log: cardholder notified of "
        f"provisional credit. See {gold_dsp}.",
    ]):
        records.append({"text": content, "source_id": f"dsp-ref-{j}"})
    return records


@pytest.fixture(scope="module")
async def seeded_rag():
    rag = GraphRAG(dsn=TEST_DSN, namespace=NS)
    await rag.connect()
    await rag.db.execute("DELETE FROM documents WHERE namespace = %s", (NS,))
    await rag.ingest_records(_make_corpus(), namespace=NS, defer_extraction=True)
    yield rag
    await rag.db.execute("DELETE FROM documents WHERE namespace = %s", (NS,))
    await rag.close()


def _sources(result):
    return [c.document_source for c in result.chunks]


@pytest.mark.asyncio
async def test_naive_recovers_gold_from_template_cohort(seeded_rag):
    result = await seeded_rag.query(QUERY, mode="naive", namespace=NS, top_k=12)
    srcs = _sources(result)
    assert GOLD in srcs, (
        f"gold {GOLD} missing from naive top-12 (#114): rare query tokens "
        f"(name/vendor/amount/ticket) did not lift it over template siblings; "
        f"got {srcs}"
    )


@pytest.mark.asyncio
async def test_naive_boost_recovers_gold_from_template_cohort(seeded_rag):
    result = await seeded_rag.query(QUERY, mode="naive_boost", namespace=NS, top_k=12)
    srcs = _sources(result)
    assert GOLD in srcs, f"gold {GOLD} missing from naive_boost top-12 (#114): {srcs}"


@pytest.mark.asyncio
async def test_linear_fusion_also_recovers_gold(seeded_rag):
    result = await seeded_rag.query(
        QUERY, mode="naive", namespace=NS, top_k=12, fusion="linear"
    )
    srcs = _sources(result)
    assert GOLD in srcs, f"gold {GOLD} missing under fusion=linear (#114): {srcs}"


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["local", "global", "hybrid"])
async def test_graph_modes_execute_with_rare_bonus(seeded_rag, mode):
    """Graph builders carry the bonus too — their SQL must bind and execute
    under default config (this namespace has no graph, so results may be
    empty; the guard is against bind/SQL errors, not ranking)."""
    result = await seeded_rag.query(QUERY, mode=mode, namespace=NS, top_k=12)
    assert result is not None


@pytest.mark.asyncio
async def test_exact_id_query_surfaces_id_docs(seeded_rag):
    """A ticket-only query (the #103 exact-ID class): the only docs carrying
    the query's unique hyphenated id must not be buried by template siblings
    that merely match many common words — pre-#114 they sat at lexical rank
    51/54 under ts_rank."""
    result = await seeded_rag.query(
        "What is the current status of ticket TCKT-1065?",
        mode="naive", namespace=NS, top_k=12,
    )
    srcs = _sources(result)
    ref_hits = sum(1 for s in srcs if s.startswith("dsp-ref-"))
    assert ref_hits == 4, (
        f"expected all 4 TCKT-1065 docs in naive top-12 for a ticket-only "
        f"query, got {ref_hits}: {srcs}"
    )
