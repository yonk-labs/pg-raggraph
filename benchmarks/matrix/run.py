"""Config-driven benchmark matrix case builder.

This is the "beast" harness entry point. It prepares audit-ready cases for
``llm-judge`` from a configurable matrix of workloads, retrieval modes, top-k
values, and context assembly strategies.

The first implementation intentionally reuses the existing e2e benchmark
datasets and preloaded ``bench_<dataset>_lede_spacy`` namespaces. It separates
retrieval from answer-context assembly so the same retrieval can be compared as
raw chunks, selected full documents, summaries, and summary+facts variants.

Usage:
    uv run python -m benchmarks.matrix.run --config benchmarks/matrix/smoke.yaml
    uv run llm-judge evaluate --config .matrix-runs/<run-id>/llm_judge.yaml
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import subprocess
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from benchmarks.e2e.config import DEFAULT_DSN, PINNED_EMBEDDING_DIM, PINNED_EMBEDDING_MODEL
from benchmarks.e2e.datasets import get as get_loader
from benchmarks.e2e.datasets._common import CorpusDoc, DatasetBundle, Query
from pg_raggraph import GraphRAG
from pg_raggraph import __version__ as PGRG_VERSION
from pg_raggraph.chunking import token_count
from pg_raggraph.context import _budget_for_tokens, _summarize_facts

CONTEXT_STRATEGIES = {
    "classic_chunks",
    "full_selected_docs",
    "doc_summary_facts",
    "hint_doc_summary_facts",
    "doc_summary_toc_facts",
    "doc_summary_facts_plus_chunks",
    "hint_doc_summary_facts_plus_chunks",
    "toc_doc_summary_plus_chunk_summary",
    # --- summary-density experiment (Phase C) ---------------------------
    # Full-doc summary+facts at 1.5x / 2x / 3x the default char budget.
    "doc_summary_facts_x1_5",
    "doc_summary_facts_x2",
    "doc_summary_facts_x3",
    # Summary *source* comparison at default density: summarize the
    # retrieved chunks instead of (or in addition to) the full document.
    "chunk_summary_facts",
    "doc_and_chunk_summary_facts",
    # "Beat classic RAG@25" challengers: a summary (+headers/TOC +facts) of
    # the 25 retrieved chunks and/or full doc, plus the top-5 raw chunks.
    "chunk_summary_toc_facts_plus_top5",
    "doc_summary_toc_facts_plus_top5",
    "doc_and_chunk_summary_toc_facts_plus_top5",
}

# Phase E coverage-parameterized doc strategies + per-doc granularity.
# "<base>@<N>" feeds the top-N parent docs; per_doc_* summarizes each separately.
_COVERAGE_STRATEGIES = {
    "full_selected_docs@3",
    "full_selected_docs@5",
    "full_selected_docs@10",
    "doc_summary_facts@3",
    "doc_summary_facts@5",
    "doc_summary_facts@10",
    "per_doc_summary_facts",
    "per_doc_summary_facts@3",
    "per_doc_summary_facts@5",
    "per_doc_summary_facts@10",
    "per_doc5_chunksum_top5",
}
CONTEXT_STRATEGIES = CONTEXT_STRATEGIES | _COVERAGE_STRATEGIES

_COVERAGE_RE = re.compile(r"@(\d+)$")


def _coverage(strategy: str) -> tuple[str, int | None]:
    """Split a "<base>@<N>" strategy into (base, N); N is None if absent."""
    m = _COVERAGE_RE.search(strategy)
    if m:
        return strategy[: m.start()], int(m.group(1))
    return strategy, None


# Top-N raw chunks appended by the *_plus_top5 challenger strategies.
_PLUS_TOP_N = 5
# Default-density char budget multipliers for the density sweep.
_DENSITY_MULTIPLIERS = {
    "doc_summary_facts_x1_5": 1.5,
    "doc_summary_facts_x2": 2.0,
    "doc_summary_facts_x3": 3.0,
}


@dataclass
class MatrixCase:
    id: str
    question: str
    answer: str
    expected: list[str]
    required_facts: list[str]
    chunks: list[str]
    settings: dict[str, Any]
    source_tokens: int
    context_tokens: int
    retrieval_latency_ms: float
    assembly_latency_ms: float
    selected_documents: list[str]
    skipped: bool = False
    error: str | None = None


@dataclass(frozen=True)
class Shape:
    """One materialized ingest shape.

    A shape is everything that changes stored chunks/embeddings. Retrieval and
    context assembly axes deliberately sit outside this object so they can be
    swept repeatedly without re-chunking or re-embedding.
    """

    id: str
    namespace: str
    dataset: str
    arm: str
    embedding_model: str
    embedding_dim: int
    embedding_provider: str
    embedding_base_url: str
    chunk_strategy: str
    chunk_max_tokens: int
    chunk_overlap_tokens: int
    skip_extraction: bool
    fact_extractor: str


@dataclass
class ShapeStageStats:
    shape_id: str
    namespace: str
    documents: int
    chunks: int
    entities: int
    relationships: int
    wall_seconds: float
    skipped_existing: bool
    error: str | None = None


def _git_sha() -> str:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], stderr=subprocess.DEVNULL
        )
        return out.decode().strip()
    except Exception:
        return "unknown"


def _read_config(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError("matrix config must be a mapping")
    return data


def _docs_by_id(bundle: DatasetBundle) -> dict[str, CorpusDoc]:
    return {doc.source_id: doc for doc in bundle.corpus_docs}


def _slug(value: str, *, limit: int = 18) -> str:
    safe = "".join(ch.lower() if ch.isalnum() else "_" for ch in value)
    safe = "_".join(part for part in safe.split("_") if part)
    return (safe or "x")[:limit]


def _short_hash(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:8]


def _axis_values(cfg: dict[str, Any], key: str, default: list[Any]) -> list[Any]:
    value = cfg.get(key, default)
    if value is None:
        return default
    if isinstance(value, list):
        return value
    return [value]


def _embedding_shapes(config: dict[str, Any]) -> list[dict[str, Any]]:
    ingest_cfg = config.get("ingest") or {}
    embeddings = ingest_cfg.get("embeddings")
    if not embeddings:
        return [
            {
                "model": PINNED_EMBEDDING_MODEL,
                "dim": PINNED_EMBEDDING_DIM,
                "provider": "local",
                "base_url": "",
            }
        ]
    return [dict(item) for item in embeddings]


def _shape_namespace(
    *, run_prefix: str, dataset: str, arm: str, embedding: dict, chunk: dict
) -> str:
    parts = [
        _slug(run_prefix, limit=10),
        _slug(dataset, limit=10),
        _slug(arm, limit=10),
        _slug(str(embedding.get("model", "embed")).split("/")[-1], limit=12),
        _slug(str(chunk.get("strategy", "auto")), limit=12),
        str(chunk.get("max_tokens", 512)),
        str(chunk.get("overlap_tokens", 50)),
    ]
    base = "mx_" + "_".join(parts)
    suffix = _short_hash("|".join(parts))
    return f"{base[:55]}_{suffix}"


def _workload_shapes(config: dict[str, Any], workload: dict[str, Any], run_id: str) -> list[Shape]:
    ingest_cfg = config.get("ingest") or {}
    arms = _axis_values(
        workload, "arms", _axis_values(ingest_cfg, "arms", [workload.get("arm", "lede_spacy")])
    )
    chunk_strategies = _axis_values(
        ingest_cfg, "chunk_strategies", [ingest_cfg.get("chunk_strategy", "auto")]
    )
    chunk_max_tokens = [int(v) for v in _axis_values(ingest_cfg, "chunk_max_tokens", [512])]
    chunk_overlap_tokens = [int(v) for v in _axis_values(ingest_cfg, "chunk_overlap_tokens", [50])]
    embeddings = _embedding_shapes(config)
    shapes: list[Shape] = []
    dataset = workload["name"]
    for arm in arms:
        for embedding in embeddings:
            for chunk_strategy in chunk_strategies:
                for max_tokens in chunk_max_tokens:
                    for overlap_tokens in chunk_overlap_tokens:
                        chunk = {
                            "strategy": chunk_strategy,
                            "max_tokens": max_tokens,
                            "overlap_tokens": overlap_tokens,
                        }
                        namespace = workload.get("namespace") or _shape_namespace(
                            run_prefix=(config.get("suite") or {}).get("namespace_prefix", run_id),
                            dataset=dataset,
                            arm=str(arm),
                            embedding=embedding,
                            chunk=chunk,
                        )
                        shape_id = (
                            f"{dataset}:{arm}:"
                            f"emb={_slug(str(embedding.get('model', PINNED_EMBEDDING_MODEL)).split('/')[-1])}:"
                            f"chunk={_slug(str(chunk_strategy))}:"
                            f"tok={max_tokens}:ov={overlap_tokens}"
                        )
                        shapes.append(
                            Shape(
                                id=shape_id,
                                namespace=namespace,
                                dataset=dataset,
                                arm=str(arm),
                                embedding_model=str(
                                    embedding.get("model", PINNED_EMBEDDING_MODEL)
                                ),
                                embedding_dim=int(embedding.get("dim", PINNED_EMBEDDING_DIM)),
                                embedding_provider=str(embedding.get("provider", "local")),
                                embedding_base_url=str(embedding.get("base_url", "")),
                                chunk_strategy=str(chunk_strategy),
                                chunk_max_tokens=max_tokens,
                                chunk_overlap_tokens=overlap_tokens,
                                skip_extraction=bool(ingest_cfg.get("skip_extraction", False)),
                                fact_extractor=str(ingest_cfg.get("fact_extractor", arm)),
                            )
                        )
    return shapes


def _answers(query: Query) -> list[str]:
    return [answer for answer in query.answers if answer and answer.strip()]


def _chunks_text(chunks) -> str:
    return "\n\n".join(c.content for c in chunks)


def _case_id(
    *,
    run_id: str,
    dataset: str,
    query: Query,
    shape: Shape,
    mode: str,
    top_k: int,
    retrieval_strategy: str,
    rerank: bool,
    strategy: str,
) -> str:
    return (
        f"{run_id}:{dataset}:{query.qid}:shape:{shape.id}:"
        f"mode:{mode}:retrieval:{retrieval_strategy}:rerank:{int(rerank)}:"
        f"topk:{top_k}:ctx:{strategy}"
    )


def _context_tokens(chunks: list[str]) -> int:
    return token_count("\n\n".join(chunks))


def _selected_docs_for_chunks(
    docs_by_id: dict[str, CorpusDoc],
    chunks,
    *,
    max_docs: int,
) -> list[CorpusDoc]:
    seen: set[str] = set()
    docs: list[CorpusDoc] = []
    for chunk in chunks:
        source = chunk.document_source
        if not source or source in seen:
            continue
        doc = docs_by_id.get(source)
        if doc is None:
            continue
        seen.add(source)
        docs.append(doc)
        if len(docs) >= max_docs:
            break
    return docs


def _make_case(
    *,
    run_id: str,
    dataset: str,
    query: Query,
    shape: Shape,
    mode: str,
    top_k: int,
    retrieval_strategy: str,
    rerank: bool,
    strategy: str,
    chunks: list[str],
    source_tokens: int,
    retrieval_latency_ms: float,
    assembly_latency_ms: float,
    selected_documents: list[str],
    extra_settings: dict[str, Any] | None = None,
    skipped: bool = False,
    error: str | None = None,
) -> MatrixCase:
    context_tokens = _context_tokens(chunks)
    return MatrixCase(
        id=_case_id(
            run_id=run_id,
            dataset=dataset,
            query=query,
            shape=shape,
            mode=mode,
            top_k=top_k,
            retrieval_strategy=retrieval_strategy,
            rerank=rerank,
            strategy=strategy,
        ),
        question=query.question,
        answer="",
        expected=_answers(query),
        required_facts=_answers(query),
        chunks=chunks,
        settings={
            "run_id": run_id,
            "dataset": dataset,
            "qid": query.qid,
            "shape_id": shape.id,
            "namespace": shape.namespace,
            "arm": shape.arm,
            "retrieval_mode": mode,
            "retrieval_strategy": retrieval_strategy,
            "rerank": rerank,
            "top_k": top_k,
            "context_strategy": strategy,
            "embedding_model": shape.embedding_model,
            "embedding_dim": shape.embedding_dim,
            "embedding_provider": shape.embedding_provider,
            "chunk_strategy": shape.chunk_strategy,
            "chunk_max_tokens": shape.chunk_max_tokens,
            "chunk_overlap_tokens": shape.chunk_overlap_tokens,
            "config_label": _config_label(
                shape=shape,
                mode=mode,
                retrieval_strategy=retrieval_strategy,
                rerank=rerank,
                top_k=top_k,
                context_strategy=strategy,
            ),
            "pg_raggraph_version": PGRG_VERSION,
            "git_sha": _git_sha(),
            **query.strata,
            **(extra_settings or {}),
        },
        source_tokens=source_tokens,
        context_tokens=context_tokens,
        retrieval_latency_ms=round(retrieval_latency_ms, 1),
        assembly_latency_ms=round(assembly_latency_ms, 1),
        selected_documents=selected_documents,
        skipped=skipped,
        error=error,
    )


def _config_label(
    *,
    shape: Shape,
    mode: str,
    retrieval_strategy: str,
    rerank: bool,
    top_k: int,
    context_strategy: str,
) -> str:
    return (
        f"{shape.dataset}|{shape.arm}|{shape.chunk_strategy}|"
        f"{shape.chunk_max_tokens}/{shape.chunk_overlap_tokens}|"
        f"{_slug(shape.embedding_model.split('/')[-1], limit=16)}|"
        f"{mode}|{retrieval_strategy}|rerank={int(rerank)}|"
        f"top_k={top_k}|{context_strategy}"
    )


def _as_record(case: MatrixCase) -> dict[str, Any]:
    return asdict(case)


def _build_llm_judge_config(
    config: dict[str, Any], input_path: Path, out_dir: Path
) -> dict[str, Any]:
    judge_cfg = config.get("judge") or {}
    answer_cfg = config.get("answer") or {}
    mode = judge_cfg.get("mode", "accurate")
    llm_config: dict[str, Any] = {
        "input": str(input_path),
        "profile": "default",
        "out": str(out_dir / "llm-judge"),
        "mode": mode,
        "generate_answer": True,
        "cache_dir": str(out_dir / "cache"),
        "resume": bool(config.get("run", {}).get("resume", True)),
        "concurrency": int(
            judge_cfg.get("concurrency", config.get("run", {}).get("concurrency", 1))
        ),
        "retries": int(judge_cfg.get("retries", 2)),
        "parse_retries": int(judge_cfg.get("parse_retries", 2)),
        "timeout": float(judge_cfg.get("timeout", 180)),
        "temperature": float(judge_cfg.get("temperature", 0.0)),
        "max_tokens": int(judge_cfg.get("max_tokens", 1200)),
        "strict_json_fallback": bool(judge_cfg.get("strict_json_fallback", True)),
        "answer": answer_cfg,
    }
    if "providers" in judge_cfg:
        llm_config["judges"] = judge_cfg["providers"]
    elif "provider" in judge_cfg:
        llm_config["judge"] = {
            key: value
            for key, value in judge_cfg.items()
            if key
            in {
                "provider",
                "model",
                "base_url",
                "api_key_env",
                "command",
                "timeout",
                "temperature",
                "retries",
                "max_tokens",
                "disable_response_format",
                "strict_json_fallback",
            }
        }
    return llm_config


async def _retrieve(
    rag: GraphRAG,
    query: Query,
    *,
    namespace: str,
    mode: str,
    top_k: int,
    retrieval_strategy: str | None,
    rerank: bool,
    summary_base_mode: str | None,
    metadata_filters: dict[str, Any] | None,
):
    rag.config.top_k = top_k
    t0 = time.perf_counter()
    result = await rag.query(
        query.question,
        mode=mode,
        namespace=namespace,
        retrieval_strategy=retrieval_strategy,
        rerank=rerank,
        summary_base_mode=summary_base_mode,
        metadata_filters=metadata_filters,
    )
    return result, (time.perf_counter() - t0) * 1000


def _graphrag_kwargs(config: dict[str, Any], shape: Shape) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "dsn": config.get("dsn") or DEFAULT_DSN,
        "namespace": shape.namespace,
        "embedding_model": shape.embedding_model,
        "embedding_dim": shape.embedding_dim,
        "embedding_provider": shape.embedding_provider,
        "chunk_strategy": shape.chunk_strategy,
        "chunk_max_tokens": shape.chunk_max_tokens,
        "chunk_overlap_tokens": shape.chunk_overlap_tokens,
        "fact_extractor": shape.fact_extractor,
        "skip_extraction": shape.skip_extraction,
    }
    if shape.embedding_base_url:
        kwargs["embedding_base_url"] = shape.embedding_base_url
    if shape.fact_extractor != "llm":
        kwargs["llm_base_url"] = ""

    for key, value in (config.get("graphrag") or {}).items():
        kwargs[key] = value
    return kwargs


async def _stage_shape(
    *,
    config: dict[str, Any],
    bundle: DatasetBundle,
    shape: Shape,
) -> ShapeStageStats:
    ingest_cfg = config.get("ingest") or {}
    refresh = bool(ingest_cfg.get("refresh_shapes", False))
    reuse_existing = bool(ingest_cfg.get("reuse_existing_shapes", True))

    rag = GraphRAG(**_graphrag_kwargs(config, shape))
    await rag.connect()
    try:
        if refresh:
            await rag.delete(shape.namespace)

        existing = await rag.status(shape.namespace)
        if reuse_existing and existing["documents"] > 0:
            return ShapeStageStats(
                shape_id=shape.id,
                namespace=shape.namespace,
                wall_seconds=0.0,
                documents=existing["documents"],
                chunks=existing["chunks"],
                entities=existing["entities"],
                relationships=existing.get("relationships", 0),
                skipped_existing=True,
            )

        records = [
            {
                "text": doc.text,
                "source_id": doc.source_id,
                "metadata": doc.metadata,
            }
            for doc in bundle.corpus_docs
        ]
        t0 = time.perf_counter()
        await rag.ingest_records(records, namespace=shape.namespace)
        wall = time.perf_counter() - t0
        status = await rag.status(shape.namespace)
        return ShapeStageStats(
            shape_id=shape.id,
            namespace=shape.namespace,
            wall_seconds=wall,
            documents=status["documents"],
            chunks=status["chunks"],
            entities=status["entities"],
            relationships=status.get("relationships", 0),
            skipped_existing=False,
        )
    except Exception as exc:
        return ShapeStageStats(
            shape_id=shape.id,
            namespace=shape.namespace,
            wall_seconds=0.0,
            documents=0,
            chunks=0,
            entities=0,
            relationships=0,
            skipped_existing=False,
            error=f"{type(exc).__name__}: {exc}",
        )
    finally:
        await rag.close()


def _assemble_strategy(
    *,
    strategy: str,
    query: Query,
    retrieved_chunks,
    retrieved_text: str,
    docs: list[CorpusDoc],
    max_context_tokens: int,
) -> tuple[list[str], int, list[str], bool, str | None]:
    t0 = time.perf_counter()
    del t0  # Assembly latency is measured by caller around this function.
    doc_text = "\n\n".join(doc.text for doc in docs)
    doc_tokens = token_count(doc_text)
    retrieved_tokens = token_count(retrieved_text)
    selected_ids = [doc.source_id for doc in docs]

    # --- Phase E: coverage-parameterized doc strategies ("<base>@<N>") ------
    # "@N" selects the top-N parent docs (the caller provides up to
    # max_selected_docs of them). This isolates two variables:
    #   * coverage  — how many docs we feed (3/5/10)
    #   * granularity — concat-then-summarize vs summarize-each-doc-separately
    base_name, coverage_n = _coverage(strategy)
    if base_name in {"full_selected_docs", "doc_summary_facts", "per_doc_summary_facts"} and (
        coverage_n is not None or base_name == "per_doc_summary_facts"
    ):
        sel = docs[:coverage_n] if coverage_n else docs
        if not sel:
            return [], 0, selected_ids, True, "no selected documents for coverage strategy"
        sel_ids = [d.source_id for d in sel]
        sel_text = "\n\n".join(d.text for d in sel)
        sel_tokens = token_count(sel_text)

        if base_name == "full_selected_docs":
            chunks = [d.text for d in sel]
            ctoks = _context_tokens(chunks)
            err = (
                f"context_tokens {ctoks} exceeds max_context_tokens {max_context_tokens}"
                if ctoks > max_context_tokens
                else None
            )
            return chunks, sel_tokens, sel_ids, err is not None, err

        if base_name == "doc_summary_facts":
            # Concatenate the top-N docs, then summarize the blob once.
            return (
                [
                    _summarize_facts(
                        sel_text,
                        query.question,
                        max_length=_budget_for_tokens(sel_tokens),
                        max_facts=30,
                        include_toc=False,
                        use_hints=False,
                    )
                ],
                sel_tokens,
                sel_ids,
                False,
                None,
            )

        # per_doc_summary_facts: summarize each doc on its own, then concat the
        # per-doc summaries. Avoids blurring facts across docs the way a single
        # summary of concatenated text can.
        parts = [
            f"[{d.source_id}]\n"
            + _summarize_facts(
                d.text,
                query.question,
                max_length=_budget_for_tokens(token_count(d.text)),
                max_facts=12,
                include_toc=False,
                use_hints=False,
            )
            for d in sel
        ]
        return parts, sel_tokens, sel_ids, False, None

    # Kitchen sink: per-doc summaries (top-5) + a summary of all retrieved
    # chunks + the top-5 raw chunks. Tests whether stacking every leg helps or
    # dilutes.
    if strategy == "per_doc5_chunksum_top5":
        sel = docs[:5]
        if not sel:
            return [], 0, selected_ids, True, "no selected documents for per_doc5_chunksum_top5"
        sel_text = "\n\n".join(d.text for d in sel)
        top5 = [c.content for c in retrieved_chunks[:_PLUS_TOP_N]]
        top5_text = "\n\n".join(top5)
        parts = [
            f"[{d.source_id}]\n"
            + _summarize_facts(
                d.text,
                query.question,
                max_length=_budget_for_tokens(token_count(d.text)),
                max_facts=12,
                include_toc=True,
                use_hints=True,
            )
            for d in sel
        ]
        parts.append(
            "Retrieved-chunk summary:\n"
            + _summarize_facts(
                retrieved_text,
                query.question,
                max_length=_budget_for_tokens(retrieved_tokens),
                max_facts=20,
                include_toc=False,
                use_hints=True,
            )
        )
        parts.append(f"Top {_PLUS_TOP_N} chunks:\n{top5_text}")
        return (
            parts,
            token_count(sel_text) + retrieved_tokens + token_count(top5_text),
            [d.source_id for d in sel],
            False,
            None,
        )

    if strategy == "classic_chunks":
        chunks = [chunk.content for chunk in retrieved_chunks]
        return chunks, retrieved_tokens, selected_ids, False, None

    if strategy == "full_selected_docs":
        chunks = [doc.text for doc in docs]
        context_tokens = _context_tokens(chunks)
        if context_tokens > max_context_tokens:
            return (
                chunks,
                doc_tokens,
                selected_ids,
                True,
                f"context_tokens {context_tokens} exceeds max_context_tokens {max_context_tokens}",
            )
        return chunks, doc_tokens, selected_ids, False, None

    if not doc_text.strip():
        return [], 0, selected_ids, True, "no selected documents for summary strategy"

    if strategy == "doc_summary_facts":
        return (
            [
                _summarize_facts(
                    doc_text,
                    query.question,
                    max_length=_budget_for_tokens(doc_tokens),
                    max_facts=30,
                    include_toc=False,
                    use_hints=False,
                )
            ],
            doc_tokens,
            selected_ids,
            False,
            None,
        )

    if strategy == "hint_doc_summary_facts":
        return (
            [
                _summarize_facts(
                    doc_text,
                    query.question,
                    max_length=_budget_for_tokens(doc_tokens),
                    max_facts=30,
                    include_toc=False,
                    use_hints=True,
                )
            ],
            doc_tokens,
            selected_ids,
            False,
            None,
        )

    if strategy == "doc_summary_toc_facts":
        return (
            [
                _summarize_facts(
                    doc_text,
                    query.question,
                    max_length=_budget_for_tokens(doc_tokens),
                    max_facts=30,
                    include_toc=True,
                    use_hints=True,
                )
            ],
            doc_tokens,
            selected_ids,
            False,
            None,
        )

    if strategy in {"doc_summary_facts_plus_chunks", "hint_doc_summary_facts_plus_chunks"}:
        use_hints = strategy.startswith("hint_")
        summary = _summarize_facts(
            doc_text,
            query.question,
            max_length=_budget_for_tokens(doc_tokens),
            max_facts=30,
            include_toc=False,
            use_hints=use_hints,
        )
        return (
            [summary, f"Retrieved chunks:\n{retrieved_text}"],
            doc_tokens + retrieved_tokens,
            selected_ids,
            False,
            None,
        )

    if strategy == "toc_doc_summary_plus_chunk_summary":
        doc_summary = _summarize_facts(
            doc_text,
            query.question,
            max_length=_budget_for_tokens(doc_tokens),
            max_facts=30,
            include_toc=True,
            use_hints=True,
        )
        chunk_summary = _summarize_facts(
            retrieved_text,
            query.question,
            max_length=max(2000, min(16_000, retrieved_tokens * 2)),
            max_facts=12,
            include_toc=False,
            use_hints=True,
        )
        return (
            [doc_summary, f"Retrieved summary:\n{chunk_summary}"],
            doc_tokens + retrieved_tokens,
            selected_ids,
            False,
            None,
        )

    # --- Phase C: summary-density sweep (full-doc summary, scaled budget) --
    if strategy in _DENSITY_MULTIPLIERS:
        budget = int(_budget_for_tokens(doc_tokens) * _DENSITY_MULTIPLIERS[strategy])
        return (
            [
                _summarize_facts(
                    doc_text,
                    query.question,
                    max_length=budget,
                    max_facts=30,
                    include_toc=False,
                    use_hints=False,
                )
            ],
            doc_tokens,
            selected_ids,
            False,
            None,
        )

    # --- Phase C: summary source — chunks vs full doc vs both --------------
    if strategy == "chunk_summary_facts":
        return (
            [
                _summarize_facts(
                    retrieved_text,
                    query.question,
                    max_length=_budget_for_tokens(retrieved_tokens),
                    max_facts=30,
                    include_toc=False,
                    use_hints=False,
                )
            ],
            retrieved_tokens,
            selected_ids,
            False,
            None,
        )

    if strategy == "doc_and_chunk_summary_facts":
        doc_summary = _summarize_facts(
            doc_text,
            query.question,
            max_length=_budget_for_tokens(doc_tokens),
            max_facts=30,
            include_toc=False,
            use_hints=False,
        )
        chunk_summary = _summarize_facts(
            retrieved_text,
            query.question,
            max_length=_budget_for_tokens(retrieved_tokens),
            max_facts=30,
            include_toc=False,
            use_hints=False,
        )
        return (
            [f"Document summary:\n{doc_summary}", f"Retrieved-chunk summary:\n{chunk_summary}"],
            doc_tokens + retrieved_tokens,
            selected_ids,
            False,
            None,
        )

    # --- Phase C: "beat classic RAG@25" — summary(+TOC+facts) + top-5 raw --
    if strategy in {
        "chunk_summary_toc_facts_plus_top5",
        "doc_summary_toc_facts_plus_top5",
        "doc_and_chunk_summary_toc_facts_plus_top5",
    }:
        top5 = [chunk.content for chunk in retrieved_chunks[:_PLUS_TOP_N]]
        top5_text = "\n\n".join(top5)
        top5_tokens = token_count(top5_text)
        parts: list[str] = []
        if strategy != "chunk_summary_toc_facts_plus_top5":
            parts.append(
                "Document summary:\n"
                + _summarize_facts(
                    doc_text,
                    query.question,
                    max_length=_budget_for_tokens(doc_tokens),
                    max_facts=30,
                    include_toc=True,
                    use_hints=True,
                )
            )
        if strategy != "doc_summary_toc_facts_plus_top5":
            parts.append(
                "Retrieved-chunk summary:\n"
                + _summarize_facts(
                    retrieved_text,
                    query.question,
                    max_length=_budget_for_tokens(retrieved_tokens),
                    max_facts=30,
                    include_toc=True,
                    use_hints=True,
                )
            )
        parts.append(f"Top {_PLUS_TOP_N} chunks:\n{top5_text}")
        # Tokens counted: the summarized source(s) plus the verbatim top-5.
        summarized_tokens = 0
        if strategy != "chunk_summary_toc_facts_plus_top5":
            summarized_tokens += doc_tokens
        if strategy != "doc_summary_toc_facts_plus_top5":
            summarized_tokens += retrieved_tokens
        return (
            parts,
            summarized_tokens + top5_tokens,
            selected_ids,
            False,
            None,
        )

    raise ValueError(f"unknown context strategy {strategy!r}; known: {sorted(CONTEXT_STRATEGIES)}")


async def _run_workload(
    *,
    config: dict[str, Any],
    workload: dict[str, Any],
    run_id: str,
) -> tuple[list[MatrixCase], list[ShapeStageStats]]:
    dataset = workload["name"]
    subset = int(workload.get("subset", 5))
    seed = int(workload.get("seed", 42))
    bundle = get_loader(dataset)(subset=subset, seed=seed)
    docs_by_id = _docs_by_id(bundle)
    shapes = _workload_shapes(config, workload, run_id)

    retrieval_cfg = config.get("retrieval") or {}
    modes = list(retrieval_cfg.get("modes") or ["hybrid"])
    top_ks = [int(value) for value in retrieval_cfg.get("top_k", [25])]
    retrieval_strategies = list(
        retrieval_cfg.get("strategies")
        or retrieval_cfg.get("retrieval_strategies")
        or ["weighted"]
    )
    rerank_values = [bool(value) for value in _axis_values(retrieval_cfg, "rerank", [False])]
    summary_base_modes = list(retrieval_cfg.get("summary_base_modes") or ["hybrid"])
    metadata_filter_presets = retrieval_cfg.get("metadata_filter_presets") or [{"label": "none"}]
    max_docs = int(
        (config.get("baselines") or {})
        .get("full_document", {})
        .get("max_docs", (config.get("context") or {}).get("max_selected_docs", 3))
    )
    max_context_tokens = int(
        (config.get("baselines") or {}).get("full_document", {}).get("max_context_tokens", 120_000)
    )
    context_strategies = list(
        (config.get("context") or {}).get("strategies") or ["classic_chunks"]
    )

    cases: list[MatrixCase] = []
    stage_stats: list[ShapeStageStats] = []
    for shape in shapes:
        stat = await _stage_shape(config=config, bundle=bundle, shape=shape)
        stage_stats.append(stat)
        if stat.error:
            for query in bundle.queries:
                cases.append(
                    _make_case(
                        run_id=run_id,
                        dataset=dataset,
                        query=query,
                        shape=shape,
                        mode="ERROR",
                        top_k=0,
                        retrieval_strategy="ERROR",
                        rerank=False,
                        strategy="ERROR",
                        chunks=[],
                        source_tokens=0,
                        retrieval_latency_ms=0.0,
                        assembly_latency_ms=0.0,
                        selected_documents=[],
                        skipped=True,
                        error=stat.error,
                    )
                )
            continue

        rag = GraphRAG(**_graphrag_kwargs(config, shape))
        await rag.connect()
        try:
            for query in bundle.queries:
                for mode in modes:
                    mode_summary_bases = summary_base_modes if mode == "summary" else [None]
                    for summary_base_mode in mode_summary_bases:
                        mode_retrieval_strategies = (
                            retrieval_strategies if mode in {"naive", "naive_boost"} else ["n/a"]
                        )
                        for retrieval_strategy in mode_retrieval_strategies:
                            for rerank in rerank_values:
                                for metadata_preset in metadata_filter_presets:
                                    metadata_label = str(metadata_preset.get("label", "none"))
                                    metadata_filters = metadata_preset.get("filters")
                                    for top_k in top_ks:
                                        try:
                                            result, retrieval_latency_ms = await _retrieve(
                                                rag,
                                                query,
                                                namespace=shape.namespace,
                                                mode=mode,
                                                top_k=top_k,
                                                retrieval_strategy=(
                                                    retrieval_strategy
                                                    if mode in {"naive", "naive_boost"}
                                                    else None
                                                ),
                                                rerank=rerank,
                                                summary_base_mode=summary_base_mode,
                                                metadata_filters=metadata_filters,
                                            )
                                            retrieved_text = _chunks_text(result.chunks)
                                            selected_docs = _selected_docs_for_chunks(
                                                docs_by_id, result.chunks, max_docs=max_docs
                                            )
                                            for strategy in context_strategies:
                                                t0 = time.perf_counter()
                                                (
                                                    chunks,
                                                    source_tokens,
                                                    selected_ids,
                                                    skipped,
                                                    error,
                                                ) = _assemble_strategy(
                                                    strategy=strategy,
                                                    query=query,
                                                    retrieved_chunks=result.chunks,
                                                    retrieved_text=retrieved_text,
                                                    docs=selected_docs,
                                                    max_context_tokens=max_context_tokens,
                                                )
                                                assembly_latency_ms = (
                                                    time.perf_counter() - t0
                                                ) * 1000
                                                cases.append(
                                                    _make_case(
                                                        run_id=run_id,
                                                        dataset=dataset,
                                                        query=query,
                                                        shape=shape,
                                                        mode=mode,
                                                        top_k=top_k,
                                                        retrieval_strategy=retrieval_strategy,
                                                        rerank=rerank,
                                                        strategy=strategy,
                                                        chunks=chunks,
                                                        source_tokens=source_tokens,
                                                        retrieval_latency_ms=retrieval_latency_ms,
                                                        assembly_latency_ms=assembly_latency_ms,
                                                        selected_documents=selected_ids,
                                                        extra_settings={
                                                            "summary_base_mode": summary_base_mode,
                                                            "metadata_filter_preset": metadata_label,
                                                        },
                                                        skipped=skipped,
                                                        error=error,
                                                    )
                                                )
                                        except Exception as exc:
                                            cases.append(
                                                _make_case(
                                                    run_id=run_id,
                                                    dataset=dataset,
                                                    query=query,
                                                    shape=shape,
                                                    mode=mode,
                                                    top_k=top_k,
                                                    retrieval_strategy=retrieval_strategy,
                                                    rerank=rerank,
                                                    strategy="ERROR",
                                                    chunks=[],
                                                    source_tokens=0,
                                                    retrieval_latency_ms=0.0,
                                                    assembly_latency_ms=0.0,
                                                    selected_documents=[],
                                                    extra_settings={
                                                        "summary_base_mode": summary_base_mode,
                                                        "metadata_filter_preset": metadata_label,
                                                    },
                                                    skipped=True,
                                                    error=f"{type(exc).__name__}: {exc}",
                                                )
                                            )
        finally:
            await rag.close()
    return cases, stage_stats


def _write_cases(path: Path, cases: list[MatrixCase]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for case in cases:
            handle.write(json.dumps(_as_record(case), ensure_ascii=False, sort_keys=True) + "\n")


def _write_summary(path: Path, cases: list[MatrixCase], config: dict[str, Any]) -> None:
    by_strategy: dict[str, list[MatrixCase]] = {}
    for case in cases:
        by_strategy.setdefault(case.settings["context_strategy"], []).append(case)
    lines = [
        "# Matrix Prepared Cases",
        "",
        f"- Run ID: `{config.get('run', {}).get('id', 'matrix')}`",
        f"- Generated at: `{datetime.now(timezone.utc).isoformat()}`",
        f"- Cases: {len(cases)}",
        "",
        "| context strategy | n | avg source tokens | avg context tokens | skipped/errors |",
        "|---|---:|---:|---:|---:|",
    ]
    for strategy, rows in sorted(by_strategy.items()):
        n = len(rows)
        avg_src = sum(row.source_tokens for row in rows) / n if n else 0
        avg_ctx = sum(row.context_tokens for row in rows) / n if n else 0
        skipped = sum(1 for row in rows if row.skipped or row.error)
        lines.append(f"| {strategy} | {n} | {avg_src:.0f} | {avg_ctx:.0f} | {skipped} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_shape_manifest(path: Path, stats: list[ShapeStageStats]) -> None:
    path.write_text(
        json.dumps([asdict(stat) for stat in stats], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


async def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="prepare pg-raggraph benchmark matrix cases")
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--out", type=Path, help="override run output directory")
    args = parser.parse_args(argv)

    config = _read_config(args.config)
    run_cfg = config.get("run") or {}
    run_id = run_cfg.get("id") or f"matrix-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
    out_dir = args.out or Path(run_cfg.get("output_dir") or f".matrix-runs/{run_id}")
    out_dir.mkdir(parents=True, exist_ok=True)

    all_cases: list[MatrixCase] = []
    all_stage_stats: list[ShapeStageStats] = []
    for workload in config.get("workloads") or []:
        cases, stage_stats = await _run_workload(config=config, workload=workload, run_id=run_id)
        all_cases.extend(cases)
        all_stage_stats.extend(stage_stats)

    cases_path = out_dir / "input.jsonl"
    _write_cases(cases_path, all_cases)
    _write_summary(out_dir / "prepared-summary.md", all_cases, config)
    _write_shape_manifest(out_dir / "shape-manifest.json", all_stage_stats)
    llm_config = _build_llm_judge_config(config, cases_path, out_dir)
    (out_dir / "llm_judge.yaml").write_text(
        yaml.safe_dump(llm_config, sort_keys=False), encoding="utf-8"
    )
    print(f"wrote {len(all_cases)} matrix cases to {cases_path}")
    print(f"wrote {len(all_stage_stats)} shape records to {out_dir / 'shape-manifest.json'}")
    print(f"wrote llm-judge config to {out_dir / 'llm_judge.yaml'}")
    print(f"run: uv run llm-judge evaluate --config {out_dir / 'llm_judge.yaml'}")


if __name__ == "__main__":
    asyncio.run(main())
