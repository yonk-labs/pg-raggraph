"""Build audit-ready llm-judge cases from pg-raggraph benchmark retrievals.

The existing showcase summaries preserve aggregate scores and token counts.
This adapter preserves the evidence needed for review: question, retrieved
context, expected answer, required facts, config labels, and retrieval timing.
Answers are intentionally left empty by default so ``llm-judge`` can generate
answers from the supplied context before judging them.

Usage:
    uv run python -m benchmarks.showcase.llm_judge_cases \
      --dataset mhr --subset 5 --arms chunks_10,toc_doc_summary_plus_chunk_summary \
      --out .llm-judge-runs/mhr5/input.jsonl
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from benchmarks.e2e.config import DEFAULT_DSN, PINNED_EMBEDDING_DIM, PINNED_EMBEDDING_MODEL
from benchmarks.e2e.datasets import get as get_loader
from benchmarks.e2e.datasets._common import Query
from benchmarks.e2e.ingest import namespace_for
from benchmarks.showcase.grounding import (
    _budget_for_tokens,
    _docs_text,
    _query_docs,
    _summarize_facts,
)
from pg_raggraph import GraphRAG
from pg_raggraph.chunking import token_count

DEFAULT_ARMS = (
    "chunks_10",
    "chunks_20",
    "chunks_30",
    "doc_summary_facts",
    "hint_doc_summary_facts",
    "doc_summary_facts_plus_chunks10",
    "hint_doc_summary_facts_plus_chunks10",
    "toc_doc_summary_plus_chunk_summary",
)


@dataclass
class JudgeInput:
    id: str
    question: str
    answer: str
    expected: list[str]
    required_facts: list[str]
    chunks: list[str]
    settings: dict
    metadata: dict


def _chunks_text(chunks) -> str:
    return "\n\n".join(c.content for c in chunks)


def _answers(query: Query) -> list[str]:
    return [answer for answer in query.answers if answer and answer.strip()]


def _case(
    *,
    dataset: str,
    query: Query,
    arm: str,
    chunks: list[str],
    source_tokens: int,
    retrieval_latency_ms: float,
    settings: dict,
    metadata: dict | None = None,
    answer: str = "",
) -> JudgeInput:
    context_tokens = token_count("\n\n".join(chunks))
    return JudgeInput(
        id=f"{dataset}:{query.qid}:arm:{arm}",
        question=query.question,
        answer=answer,
        expected=_answers(query),
        # The current normalized MHR/MuSiQue/2Wiki loaders expose answers, not
        # decomposed support facts. Preserve the gold answers as required facts
        # until a dataset-specific fact adapter is added.
        required_facts=_answers(query),
        chunks=chunks,
        settings={
            "dataset": dataset,
            "qid": query.qid,
            "arm": arm,
            "embedding_model": PINNED_EMBEDDING_MODEL,
            "embedding_dim": PINNED_EMBEDDING_DIM,
            "chunk_strategy": "auto",
            **query.strata,
            **settings,
        },
        metadata={
            "source_tokens": source_tokens,
            "context_tokens": context_tokens,
            "retrieval_latency_ms": round(retrieval_latency_ms, 1),
            "required_facts_source": "dataset_answers",
            **(metadata or {}),
        },
    )


async def _build_dataset_cases(
    *,
    dataset: str,
    subset: int,
    seed: int,
    dsn: str,
    arms: set[str],
) -> list[JudgeInput]:
    bundle = get_loader(dataset)(subset=subset, seed=seed)
    namespace = namespace_for(dataset, "lede_spacy")
    rag = GraphRAG(
        dsn=dsn,
        namespace=namespace,
        embedding_model=PINNED_EMBEDDING_MODEL,
        embedding_dim=PINNED_EMBEDDING_DIM,
        llm_base_url="",
    )
    await rag.connect()
    cases: list[JudgeInput] = []
    try:
        for query in bundle.queries:
            docs, docs_kind = _query_docs(bundle, query)
            docs_context = _docs_text(docs)
            docs_tokens = token_count(docs_context)

            retrieved: dict[int, tuple[str, float]] = {}
            for arm in sorted(arms):
                if not arm.startswith("chunks_"):
                    continue
                try:
                    top_k = int(arm.rsplit("_", 1)[1])
                except ValueError:
                    continue
                t0 = time.perf_counter()
                rag.config.top_k = top_k
                result = await rag.query(query.question, mode="hybrid", namespace=namespace)
                latency_ms = (time.perf_counter() - t0) * 1000
                context = _chunks_text(result.chunks)
                retrieved[top_k] = (context, latency_ms)
                cases.append(
                    _case(
                        dataset=dataset,
                        query=query,
                        arm=arm,
                        chunks=[c.content for c in result.chunks],
                        source_tokens=token_count(context),
                        retrieval_latency_ms=latency_ms,
                        settings={"retrieval_mode": "hybrid", "top_k": top_k},
                    )
                )

            if any("chunks10" in arm or arm.endswith("chunk_summary") for arm in arms):
                if 10 not in retrieved:
                    t0 = time.perf_counter()
                    rag.config.top_k = 10
                    result = await rag.query(query.question, mode="hybrid", namespace=namespace)
                    retrieved[10] = (
                        _chunks_text(result.chunks),
                        (time.perf_counter() - t0) * 1000,
                    )
                chunks10, chunks10_latency_ms = retrieved[10]
            else:
                chunks10, chunks10_latency_ms = "", 0.0

            summaries: dict[str, str] = {}
            if "doc_summary_facts" in arms or "doc_summary_facts_plus_chunks10" in arms:
                summaries["doc_summary_facts"] = _summarize_facts(
                    docs_context,
                    query.question,
                    max_length=_budget_for_tokens(docs_tokens),
                    max_facts=30,
                    include_toc=False,
                    use_hints=False,
                )
            if "hint_doc_summary_facts" in arms or "hint_doc_summary_facts_plus_chunks10" in arms:
                summaries["hint_doc_summary_facts"] = _summarize_facts(
                    docs_context,
                    query.question,
                    max_length=_budget_for_tokens(docs_tokens),
                    max_facts=30,
                    include_toc=False,
                    use_hints=True,
                )

            for arm in ("doc_summary_facts", "hint_doc_summary_facts"):
                if arm not in arms:
                    continue
                summary = summaries[arm]
                cases.append(
                    _case(
                        dataset=dataset,
                        query=query,
                        arm=arm,
                        chunks=[summary],
                        source_tokens=docs_tokens,
                        retrieval_latency_ms=0.0,
                        settings={"retrieval_mode": docs_kind, "summary_context": arm},
                        metadata={"docs": len(docs)},
                    )
                )

            for base_arm in ("doc_summary_facts", "hint_doc_summary_facts"):
                arm = f"{base_arm}_plus_chunks10"
                if arm not in arms:
                    continue
                summary = summaries[base_arm]
                cases.append(
                    _case(
                        dataset=dataset,
                        query=query,
                        arm=arm,
                        chunks=[summary, f"Retrieved chunks:\n{chunks10}"],
                        source_tokens=docs_tokens + token_count(chunks10),
                        retrieval_latency_ms=chunks10_latency_ms,
                        settings={
                            "retrieval_mode": docs_kind,
                            "summary_context": base_arm,
                            "top_k": 10,
                        },
                        metadata={"docs": len(docs)},
                    )
                )

            if "toc_doc_summary_plus_chunk_summary" in arms:
                toc_summary = _summarize_facts(
                    docs_context,
                    query.question,
                    max_length=_budget_for_tokens(docs_tokens),
                    max_facts=30,
                    include_toc=True,
                    use_hints=True,
                )
                chunk_summary = _summarize_facts(
                    chunks10,
                    query.question,
                    max_length=max(2000, min(16_000, token_count(chunks10) * 2)),
                    max_facts=12,
                    include_toc=False,
                    use_hints=True,
                )
                cases.append(
                    _case(
                        dataset=dataset,
                        query=query,
                        arm="toc_doc_summary_plus_chunk_summary",
                        chunks=[toc_summary, f"Retrieved summary:\n{chunk_summary}"],
                        source_tokens=docs_tokens + token_count(chunks10),
                        retrieval_latency_ms=chunks10_latency_ms,
                        settings={
                            "retrieval_mode": docs_kind,
                            "summary_context": "toc_doc_summary_plus_chunk_summary",
                            "top_k": 10,
                        },
                        metadata={"docs": len(docs)},
                    )
                )
    finally:
        await rag.close()
    return cases


async def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="emit llm-judge cases for showcase benchmarks")
    parser.add_argument("--dataset", default="mhr", help="mhr,musique,twowiki or all")
    parser.add_argument("--subset", type=int, default=5)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--dsn", default=DEFAULT_DSN)
    parser.add_argument("--arms", default=",".join(DEFAULT_ARMS))
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    datasets = ["mhr", "musique", "twowiki"] if args.dataset == "all" else args.dataset.split(",")
    arms = {arm.strip() for arm in args.arms.split(",") if arm.strip()}
    all_cases: list[JudgeInput] = []
    for dataset in datasets:
        all_cases.extend(
            await _build_dataset_cases(
                dataset=dataset,
                subset=args.subset,
                seed=args.seed,
                dsn=args.dsn,
                arms=arms,
            )
        )

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as handle:
        for case in all_cases:
            record = asdict(case)
            record.update(record.pop("metadata"))
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    print(f"wrote {len(all_cases)} llm-judge cases to {out}")


if __name__ == "__main__":
    asyncio.run(main())
