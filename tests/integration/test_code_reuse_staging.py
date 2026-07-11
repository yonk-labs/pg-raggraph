"""Capability 1: a code doc whose chunks+vectors are REUSED via `pre_chunked`
must still feed the deferred code-graph staging — using a caller-supplied
faithful source (`code_source_content`), since the doc-level `text` on the reuse
path is joined-chunk text, not a faithful file. Loud-fail if it's missing."""

import os

import pytest

from pg_raggraph import GraphRAG
from pg_raggraph.backfill import backfill_code_graph

DSN = os.environ.get("PGRG_TEST_DSN", "postgresql://postgres:postgres@localhost:5434/pg_raggraph")
pytestmark = pytest.mark.integration

NS = "test_code_reuse_staging"

# Faithful original file vs the joined-chunk text a reuse bridge would pass as `text`.
FAITHFUL_SRC = "import os\n\n\ndef greet(name):\n    return f'hi {name}'\n"
JOINED_CHUNK_TEXT = "def greet(name):\n    return f'hi {name}'\n"


def _pre_chunked(dim: int):
    return [
        {
            "content": JOINED_CHUNK_TEXT,
            "embedding": [0.0] * dim,
            "metadata": {"language": "python", "fqn": "mod.greet"},
        }
    ]


@pytest.mark.asyncio
async def test_reused_code_doc_stages_faithful_source():
    rag = GraphRAG(dsn=DSN, namespace=NS)
    await rag.connect()
    await rag.delete(NS)
    try:
        dim = rag.config.embedding_dim
        await rag.ingest_records(
            [
                {
                    "text": JOINED_CHUNK_TEXT,  # joined-chunk text (NOT faithful)
                    "source_id": "f1.py",
                    "pre_chunked": _pre_chunked(dim),
                    "code_source_content": FAITHFUL_SRC,  # the faithful file
                    "skip_llm": True,
                }
            ],
            namespace=NS,
            defer_extraction=True,
        )
        rows = await rag._db.fetch_all(
            "SELECT content, language, source_path FROM code_backfill_stage WHERE namespace = %s",
            (NS,),
        )
        assert len(rows) == 1
        assert rows[0]["language"] == "python"
        assert rows[0]["content"] == FAITHFUL_SRC  # faithful, not the joined chunk
    finally:
        await rag.delete(NS)
        await rag.close()


@pytest.mark.asyncio
async def test_reused_code_doc_without_faithful_source_is_refused():
    # ingest_records contains per-record failures (batch semantics): the bad
    # record's ValueError is logged + counted failed and its per-doc transaction
    # rolls back — it is NOT raised to the caller. The refusal is observable as a
    # rolled-back doc (would have silently persisted-but-unstaged before the fix).
    rag = GraphRAG(dsn=DSN, namespace=NS)
    await rag.connect()
    await rag.delete(NS)
    try:
        dim = rag.config.embedding_dim
        await rag.ingest_records(
            [
                {
                    "text": JOINED_CHUNK_TEXT,
                    "source_id": "f2.py",
                    "pre_chunked": _pre_chunked(dim),
                    # no code_source_content → must be refused, not staged
                    "skip_llm": True,
                }
            ],
            namespace=NS,
            defer_extraction=True,
        )
        docs = await rag._db.fetch_one(
            "SELECT COUNT(*) AS n FROM documents WHERE namespace = %s", (NS,)
        )
        assert docs["n"] == 0  # transaction rolled back — nothing persisted
        staged = await rag._db.fetch_one(
            "SELECT COUNT(*) AS n FROM code_backfill_stage WHERE namespace = %s", (NS,)
        )
        assert staged["n"] == 0  # garbage never staged
    finally:
        await rag.delete(NS)
        await rag.close()


# --- #88 acceptance: edge-set parity between re-chunk and reuse paths ---------

# One source with intra-file CALLS + INHERITS. Same bytes fed to both paths;
# only vector provenance differs, so the tree-sitter edge set must be identical.
PARITY_SRC = (
    "def helper(x):\n"
    "    return x + 1\n\n\n"
    "def runner(y):\n"
    "    return helper(y) * 2\n\n\n"
    "class Base:\n"
    "    pass\n\n\n"
    "class Child(Base):\n"
    "    def go(self):\n"
    "        return runner(3)\n"
)


async def _code_graph(rag, ns):
    """CODE_SYMBOL entity names + typed edges (rel_type, src_name, dst_name),
    as comparable sets keyed by name so cross-namespace id differences wash out."""
    ents = {
        r["name"]
        for r in await rag._db.fetch_all(
            "SELECT name FROM entities WHERE namespace = %s AND entity_type = 'CODE_SYMBOL'",
            (ns,),
        )
    }
    edges = {
        (r["rel_type"], r["src"], r["dst"])
        for r in await rag._db.fetch_all(
            "SELECT r.rel_type, s.name AS src, d.name AS dst "
            "FROM relationships r "
            "JOIN entities s ON s.id = r.src_id "
            "JOIN entities d ON d.id = r.dst_id "
            "WHERE r.namespace = %s AND r.rel_type IN ('CALLS','INHERITS','IMPLEMENTS')",
            (ns,),
        )
    }
    return ents, edges


@pytest.mark.asyncio
async def test_edge_set_parity_rechunk_vs_reuse():
    """#88 acceptance: ingest the same code corpus twice —
    (A) the re-chunk+re-embed path, (B) pre_chunked + code_source_content —
    then run the deferred backfill on each. CODE_SYMBOL entities and
    CALLS/INHERITS/IMPLEMENTS edges must be identical: same source in →
    same tree-sitter edges out, only vector provenance differs."""
    pytest.importorskip("chunkshop")
    pytest.importorskip("tree_sitter_python")

    ns_a, ns_b = "test_parity_rechunk", "test_parity_reuse"
    # Same source_id in both so module-derived FQNs match (sample.helper, …).
    src_id = "sample.py"

    rag_a = GraphRAG(dsn=DSN, namespace=ns_a, chunk_strategy="chunkshop:symbol_aware")
    rag_b = GraphRAG(dsn=DSN, namespace=ns_b)
    await rag_a.connect()
    await rag_b.connect()
    try:
        await rag_a.delete(ns_a)
        await rag_b.delete(ns_b)
        dim = rag_a.config.embedding_dim

        # Path A: faithful file goes through the normal code chunker.
        await rag_a.ingest_records(
            [{"text": PARITY_SRC, "source_id": src_id, "skip_llm": True}],
            namespace=ns_a,
            defer_extraction=True,
        )
        # Path B: reused (pre_chunked) vectors + caller-supplied faithful source.
        await rag_b.ingest_records(
            [
                {
                    "text": "def helper(x): ...",  # lossy joined-chunk text
                    "source_id": src_id,
                    "pre_chunked": [
                        {
                            "content": PARITY_SRC,
                            "embedding": [0.0] * dim,
                            "metadata": {"language": "python"},
                        }
                    ],
                    "code_source_content": PARITY_SRC,  # faithful bytes
                    "skip_llm": True,
                }
            ],
            namespace=ns_b,
            defer_extraction=True,
        )

        stats_a = await backfill_code_graph(rag_a, ns_a)
        stats_b = await backfill_code_graph(rag_b, ns_b)

        ents_a, edges_a = await _code_graph(rag_a, ns_a)
        ents_b, edges_b = await _code_graph(rag_b, ns_b)

        # Sanity: both actually produced a graph (guards a vacuous {} == {} pass).
        assert edges_a, f"path A produced no edges (stats={stats_a})"
        assert edges_b, f"path B produced no edges (stats={stats_b})"

        assert ents_a == ents_b, (
            f"CODE_SYMBOL entities differ: A-only={ents_a - ents_b}, B-only={ents_b - ents_a}"
        )
        assert edges_a == edges_b, (
            f"code edges differ: A-only={edges_a - edges_b}, B-only={edges_b - edges_a}"
        )
    finally:
        await rag_a.delete(ns_a)
        await rag_b.delete(ns_b)
        await rag_a.close()
        await rag_b.close()
