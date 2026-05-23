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
import json
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
from benchmarks.e2e.ingest import namespace_for
from benchmarks.showcase.grounding import _budget_for_tokens, _summarize_facts
from pg_raggraph import GraphRAG
from pg_raggraph import __version__ as PGRG_VERSION
from pg_raggraph.chunking import token_count

CONTEXT_STRATEGIES = {
    "classic_chunks",
    "full_selected_docs",
    "doc_summary_facts",
    "hint_doc_summary_facts",
    "doc_summary_toc_facts",
    "doc_summary_facts_plus_chunks",
    "hint_doc_summary_facts_plus_chunks",
    "toc_doc_summary_plus_chunk_summary",
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


def _answers(query: Query) -> list[str]:
    return [answer for answer in query.answers if answer and answer.strip()]


def _chunks_text(chunks) -> str:
    return "\n\n".join(c.content for c in chunks)


def _case_id(
    *,
    run_id: str,
    dataset: str,
    query: Query,
    mode: str,
    top_k: int,
    strategy: str,
) -> str:
    return f"{run_id}:{dataset}:{query.qid}:mode:{mode}:topk:{top_k}:ctx:{strategy}"


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
    mode: str,
    top_k: int,
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
            mode=mode,
            top_k=top_k,
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
            "retrieval_mode": mode,
            "top_k": top_k,
            "context_strategy": strategy,
            "embedding_model": PINNED_EMBEDDING_MODEL,
            "embedding_dim": PINNED_EMBEDDING_DIM,
            "chunk_strategy": "auto",
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
):
    rag.config.top_k = top_k
    t0 = time.perf_counter()
    result = await rag.query(query.question, mode=mode, namespace=namespace)
    return result, (time.perf_counter() - t0) * 1000


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

    raise ValueError(f"unknown context strategy {strategy!r}; known: {sorted(CONTEXT_STRATEGIES)}")


async def _run_workload(
    *,
    config: dict[str, Any],
    workload: dict[str, Any],
    run_id: str,
) -> list[MatrixCase]:
    dataset = workload["name"]
    subset = int(workload.get("subset", 5))
    seed = int(workload.get("seed", 42))
    bundle = get_loader(dataset)(subset=subset, seed=seed)
    docs_by_id = _docs_by_id(bundle)

    retrieval_cfg = config.get("retrieval") or {}
    modes = list(retrieval_cfg.get("modes") or ["hybrid"])
    top_ks = [int(value) for value in retrieval_cfg.get("top_k", [25])]
    namespace = workload.get("namespace") or namespace_for(
        dataset, workload.get("arm", "lede_spacy")
    )
    max_docs = int((config.get("baselines") or {}).get("full_document", {}).get("max_docs", 3))
    max_context_tokens = int(
        (config.get("baselines") or {}).get("full_document", {}).get("max_context_tokens", 120_000)
    )
    context_strategies = list(
        (config.get("context") or {}).get("strategies") or ["classic_chunks"]
    )

    rag = GraphRAG(
        dsn=config.get("dsn") or DEFAULT_DSN,
        namespace=namespace,
        embedding_model=PINNED_EMBEDDING_MODEL,
        embedding_dim=PINNED_EMBEDDING_DIM,
        llm_base_url="",
    )
    await rag.connect()
    cases: list[MatrixCase] = []
    try:
        for query in bundle.queries:
            for mode in modes:
                for top_k in top_ks:
                    try:
                        result, retrieval_latency_ms = await _retrieve(
                            rag,
                            query,
                            namespace=namespace,
                            mode=mode,
                            top_k=top_k,
                        )
                        retrieved_text = _chunks_text(result.chunks)
                        selected_docs = _selected_docs_for_chunks(
                            docs_by_id, result.chunks, max_docs=max_docs
                        )
                        for strategy in context_strategies:
                            t0 = time.perf_counter()
                            chunks, source_tokens, selected_ids, skipped, error = (
                                _assemble_strategy(
                                    strategy=strategy,
                                    query=query,
                                    retrieved_chunks=result.chunks,
                                    retrieved_text=retrieved_text,
                                    docs=selected_docs,
                                    max_context_tokens=max_context_tokens,
                                )
                            )
                            assembly_latency_ms = (time.perf_counter() - t0) * 1000
                            cases.append(
                                _make_case(
                                    run_id=run_id,
                                    dataset=dataset,
                                    query=query,
                                    mode=mode,
                                    top_k=top_k,
                                    strategy=strategy,
                                    chunks=chunks,
                                    source_tokens=source_tokens,
                                    retrieval_latency_ms=retrieval_latency_ms,
                                    assembly_latency_ms=assembly_latency_ms,
                                    selected_documents=selected_ids,
                                    extra_settings={"namespace": namespace},
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
                                mode=mode,
                                top_k=top_k,
                                strategy="ERROR",
                                chunks=[],
                                source_tokens=0,
                                retrieval_latency_ms=0.0,
                                assembly_latency_ms=0.0,
                                selected_documents=[],
                                extra_settings={"namespace": namespace},
                                skipped=True,
                                error=f"{type(exc).__name__}: {exc}",
                            )
                        )
    finally:
        await rag.close()
    return cases


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
    for workload in config.get("workloads") or []:
        all_cases.extend(await _run_workload(config=config, workload=workload, run_id=run_id))

    cases_path = out_dir / "input.jsonl"
    _write_cases(cases_path, all_cases)
    _write_summary(out_dir / "prepared-summary.md", all_cases, config)
    llm_config = _build_llm_judge_config(config, cases_path, out_dir)
    (out_dir / "llm_judge.yaml").write_text(
        yaml.safe_dump(llm_config, sort_keys=False), encoding="utf-8"
    )
    print(f"wrote {len(all_cases)} matrix cases to {cases_path}")
    print(f"wrote llm-judge config to {out_dir / 'llm_judge.yaml'}")
    print(f"run: uv run llm-judge evaluate --config {out_dir / 'llm_judge.yaml'}")


if __name__ == "__main__":
    asyncio.run(main())
