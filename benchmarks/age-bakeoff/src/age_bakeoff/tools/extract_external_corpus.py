"""Extract an external corpus into the ExtractionOutput cache format.

Same output shape as pg-src's extraction_cache.json: documents + chunks +
entities + relationships as one JSON blob the ExternalCorpus class loads.

Chunks via age_bakeoff.chunker.chunk_text (strategy=hierarchy by default —
the SCOTUS-winning chunker, reasonable prior for prose corpora).

Caches to ``corpora/external-extractions/{corpus_id}.json``. Rerun-safe via
cache check on first line.

Usage:
    uv run python -m age_bakeoff.tools.extract_external_corpus \\
        --corpus graphrag-bench-medical --model gpt-5-nano

    # Force re-extraction (e.g. to try a different chunker):
    uv run python -m age_bakeoff.tools.extract_external_corpus \\
        --corpus graphrag-bench-medical --force
"""
from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path
from typing import Any

from age_bakeoff.chunker import ChunkerStrategy, chunk_text
from age_bakeoff.extraction.external_corpora import CORPUS_LOADERS, load_corpus
from age_bakeoff.extraction.pg_src import _slug
from age_bakeoff.extraction.prompts import EXTRACTION_SYSTEM, EXTRACTION_USER_TEMPLATE
from age_bakeoff.models import (
    Chunk,
    ExtractedEntity,
    ExtractedRelationship,
    ExtractionOutput,
)

_BAKEOFF_ROOT = Path(__file__).resolve().parents[3]
CACHE_DIR = _BAKEOFF_ROOT / "corpora" / "external-extractions"


def _chunks_for_docs(
    documents: list[dict], strategy: ChunkerStrategy
) -> list[Chunk]:
    chunks: list[Chunk] = []
    for doc in documents:
        title = doc.get("title", "")
        for c in chunk_text(
            text=doc["content"],
            document_id=doc["id"],
            strategy=strategy,
            title=title,
        ):
            meta = {**c.metadata, "title": title, **doc.get("metadata", {})}
            chunks.append(c.model_copy(update={"metadata": meta}))
    return chunks


async def _extract_one_chunk(
    client: Any, chunk: Chunk, model: str
) -> tuple[list[dict], list[dict]]:
    user_msg = EXTRACTION_USER_TEMPLATE.format(
        source_path=chunk.metadata.get("source_path", chunk.document_id),
        content=chunk.content,
    )
    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": EXTRACTION_SYSTEM},
                {"role": "user", "content": user_msg},
            ],
            response_format={"type": "json_object"},
        )
    except Exception as e:
        print(f"  WARN: extraction call failed for {chunk.id}: {e}")
        return [], []
    content = resp.choices[0].message.content or "{}"
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return [], []
    return data.get("entities", []), data.get("relationships", [])


async def extract_corpus(
    corpus_id: str,
    model: str,
    strategy: ChunkerStrategy,
    concurrency: int,
    n_questions: int | None,
    seed: int,
) -> ExtractionOutput:
    from age_bakeoff.llm_clients import client_for

    print(f"Loading corpus {corpus_id!r}...")
    documents, _questions = load_corpus(
        corpus_id, n_questions=n_questions, seed=seed
    )
    print(f"  {len(documents)} documents")

    print(f"Chunking (strategy={strategy!r})...")
    chunks = _chunks_for_docs(documents, strategy)
    print(f"  {len(chunks)} chunks")

    print(f"Running LLM extraction ({model}, concurrency={concurrency})...")
    client = client_for("extraction")

    entities_by_id: dict[str, ExtractedEntity] = {}
    relationships: list[ExtractedRelationship] = []

    sem = asyncio.Semaphore(concurrency)
    done_count = [0]
    total = len(chunks)
    t0 = time.time()

    async def _process(chunk: Chunk):
        async with sem:
            ents, rels = await _extract_one_chunk(client, chunk, model)
            for e in ents:
                eid = _slug(e.get("name", ""))
                if eid and eid not in entities_by_id:
                    entities_by_id[eid] = ExtractedEntity(
                        id=eid,
                        name=e["name"],
                        entity_type=e.get("entity_type", "Concept"),
                        description=e.get("description", ""),
                    )
            for r in rels:
                src_id = _slug(r.get("src", ""))
                dst_id = _slug(r.get("dst", ""))
                if src_id in entities_by_id and dst_id in entities_by_id:
                    relationships.append(
                        ExtractedRelationship(
                            src_id=src_id,
                            dst_id=dst_id,
                            rel_type=r.get("rel_type", "RELATES_TO"),
                            description=r.get("description", ""),
                        )
                    )
            done_count[0] += 1
            if done_count[0] % 25 == 0 or done_count[0] == total:
                elapsed = time.time() - t0
                rate = done_count[0] / elapsed if elapsed > 0 else 0
                eta = (total - done_count[0]) / rate if rate > 0 else 0
                print(
                    f"  {done_count[0]}/{total} chunks  "
                    f"({rate:.1f}/s, ETA {eta:.0f}s)  "
                    f"ents={len(entities_by_id)} rels={len(relationships)}"
                )

    await asyncio.gather(*[_process(c) for c in chunks])

    return ExtractionOutput(
        corpus=corpus_id,
        chunks=chunks,
        entities=sorted(entities_by_id.values(), key=lambda e: e.id),
        relationships=relationships,
    )


def _cache_path(corpus_id: str) -> Path:
    return CACHE_DIR / f"{corpus_id}.json"


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--corpus", required=True, choices=sorted(CORPUS_LOADERS.keys()))
    p.add_argument("--model", default="gpt-5-nano")
    p.add_argument(
        "--strategy",
        choices=("sentence_aware", "hierarchy"),
        default="hierarchy",
    )
    p.add_argument("--concurrency", type=int, default=8)
    p.add_argument("--n-questions", type=int, default=None)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--force", action="store_true", help="Re-extract even if cached")
    args = p.parse_args()

    out_path = _cache_path(args.corpus)
    if out_path.exists() and not args.force:
        print(f"Cache exists at {out_path}; use --force to re-extract")
        return

    output = asyncio.run(
        extract_corpus(
            args.corpus,
            model=args.model,
            strategy=args.strategy,
            concurrency=args.concurrency,
            n_questions=args.n_questions,
            seed=args.seed,
        )
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(output.model_dump_json(indent=2))
    print(f"\nWrote extraction cache to {out_path}")
    print(
        f"  {len(output.chunks)} chunks, "
        f"{len(output.entities)} entities, "
        f"{len(output.relationships)} relationships"
    )


if __name__ == "__main__":
    main()
