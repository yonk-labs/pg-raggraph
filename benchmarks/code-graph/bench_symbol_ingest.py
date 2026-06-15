"""Benchmark: symbol_aware code-graph ingest (#74/#75).

Ingests real pg-raggraph source files with ``chunk_strategy="chunkshop:symbol_aware"``
and reports:

- end-to-end ingest wall-time,
- the code-graph extraction overhead in isolation (``extract_symbol_graph``)
  vs the bare chunker, so you can see what #74/#75 adds to the chunk step,
- the resulting graph (CODE_SYMBOL nodes, CALLS/INHERITS/IMPLEMENTS edges,
  per-chunk callees), and a sample ``code_impact`` query.

Run:  uv run python benchmarks/code-graph/bench_symbol_ingest.py
Needs: PostgreSQL on 5434 (docker compose up -d postgres), the [chunkshop] extra,
       and a tree-sitter grammar (pip install tree-sitter tree-sitter-python).
"""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path

from pg_raggraph import GraphRAG
from pg_raggraph import code_graph as cg
from pg_raggraph.chunking import _derive_title
from pg_raggraph.config import PGRGConfig

DSN = os.environ.get("PGRG_TEST_DSN", "postgresql://postgres:postgres@localhost:5434/pg_raggraph")
NS = "bench_code_graph"

# Real, non-trivial source modules (call-heavy, classes + methods).
SRC_DIR = Path(__file__).resolve().parents[2] / "src" / "pg_raggraph"
FILES = ["retrieval.py", "resolution.py", "code_graph.py", "chunkshop_bridge.py", "db.py"]


def _extractor_overhead(records: list[dict]) -> dict:
    """Time the bare chunker vs chunker + extract_symbol_graph, per file."""
    from chunkshop.chunkers import load_chunker
    from chunkshop.config import FixedOverlapChunker as FixedCfg
    from chunkshop.config import SymbolAwareChunker as SymCfg
    from chunkshop.sources.base import Document

    from pg_raggraph import chunkshop_bridge

    # Mirror _chunk_via_chunkshop's production config (max_chars + if_oversize
    # fallback) so the timing is faithful and the chunker doesn't warn.
    cfg = PGRGConfig(chunk_strategy="chunkshop:symbol_aware")
    max_chars = max(cfg.chunk_max_tokens * 4, 800)
    oversize = FixedCfg(type="fixed_overlap", max_chars=max_chars)
    chunker = load_chunker(SymCfg(type="symbol_aware", max_chars=max_chars, if_oversize=oversize))

    bare_s, extract_s, n_chunks, n_callees = 0.0, 0.0, 0, 0
    for rec in records:
        content, sp = rec["text"], rec["source_id"]
        doc = Document(id=sp, content=content, title=_derive_title(content, sp) or None)
        t0 = time.perf_counter()
        cs_chunks = chunker.chunk(doc)
        bare_s += time.perf_counter() - t0
        t1 = time.perf_counter()
        sg = chunkshop_bridge.extract_symbol_graph(
            content, cs_chunks, source_path=sp, project_id=sp
        )
        extract_s += time.perf_counter() - t1
        n_chunks += len(cs_chunks)
        if sg:
            n_callees += sum(len(c) for c in sg.callees_by_index)
    return {
        "bare_chunk_s": bare_s,
        "extract_s": extract_s,
        "n_chunks": n_chunks,
        "n_callees": n_callees,
    }


async def main():
    records = [
        {"text": (SRC_DIR / f).read_text(), "source_id": f, "skip_llm": True}
        for f in FILES
        if (SRC_DIR / f).exists()
    ]
    total_loc = sum(r["text"].count("\n") for r in records)
    print(f"corpus: {len(records)} files, {total_loc} lines\n")

    over = _extractor_overhead(records)
    print("chunk-step breakdown (sum over files):")
    print(f"  bare chunker:           {over['bare_chunk_s'] * 1000:8.1f} ms")
    print(f"  + extract_symbol_graph: {over['extract_s'] * 1000:8.1f} ms  (#74/#75 overhead)")
    pct = 100 * over["extract_s"] / max(over["bare_chunk_s"] + over["extract_s"], 1e-9)
    print(f"  extractor share of chunk step: {pct:.0f}%")
    print(f"  chunks: {over['n_chunks']}, callees attached: {over['n_callees']}\n")

    rag = GraphRAG(dsn=DSN, namespace=NS, chunk_strategy="chunkshop:symbol_aware")
    await rag.connect()
    await rag.delete(NS)
    try:
        t0 = time.perf_counter()
        await rag.ingest_records(records, namespace=NS)
        ingest_s = time.perf_counter() - t0

        ents = await rag._db.fetch_one(
            "SELECT COUNT(*) AS n FROM entities WHERE namespace=%s AND entity_type='CODE_SYMBOL'",
            (NS,),
        )
        rels = await rag._db.fetch_all(
            "SELECT rel_type, COUNT(*) AS n FROM relationships WHERE namespace=%s "
            "GROUP BY rel_type ORDER BY rel_type",
            (NS,),
        )
        print(
            f"end-to-end ingest (chunk + embed + graph): {ingest_s * 1000:8.1f} ms "
            f"({ingest_s / max(len(records), 1) * 1000:.1f} ms/file)"
        )
        print(f"  CODE_SYMBOL nodes: {ents['n']}")
        print("  edges: " + ", ".join(f"{r['rel_type']}={r['n']}" for r in rels))

        # Sample code_impact on the most-connected symbol.
        top = await rag._db.fetch_one(
            "SELECT e.name, COUNT(*) AS deg FROM relationships r "
            "JOIN entities e ON e.id IN (r.src_id, r.dst_id) "
            "WHERE r.namespace=%s GROUP BY e.name ORDER BY deg DESC LIMIT 1",
            (NS,),
        )
        if top:
            impact = await cg.code_impact(rag._db, top["name"], namespace=NS, depth=1)
            print(
                f"\n  code_impact('{top['name']}'): "
                f"{len(impact.callers)} callers, {len(impact.callees)} callees"
            )
    finally:
        await rag.delete(NS)
        await rag.close()


if __name__ == "__main__":
    asyncio.run(main())
