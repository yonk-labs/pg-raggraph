"""Ground larger-context summary experiments in real benchmark data.

This harness answers the questions raised after the first 2.5K-token sweep:

* How good is the LLM with no retrieved context?
* What happens when we send query/full-corpus documents directly?
* How do raw retrieved chunks scale at top_k=10/20/30?
* Does a precomputed full-document summary/fact layer help when prepended to
  retrieved chunks?
* Does TOC + facts + chunk summary improve the large-context story?

The script is intentionally separate from ``experiments.py``. That file ranks
small-context summary variants; this one is for larger-context grounding.

Usage:
    uv run python -m benchmarks.showcase.grounding --dataset mhr --subset 5
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path

import httpx
import lede
from lede.extract import key_facts, toc, top_terms

from benchmarks.e2e.config import DEFAULT_DSN, PINNED_EMBEDDING_DIM, PINNED_EMBEDDING_MODEL
from benchmarks.e2e.datasets import get as get_loader
from benchmarks.e2e.datasets._common import CorpusDoc, DatasetBundle, Query
from benchmarks.e2e.ingest import namespace_for
from benchmarks.showcase.sweep import _GEN_MODEL, _api_key, _chat, _judge, _ntokens
from pg_raggraph import GraphRAG

_CTX_PROMPT = (
    "Answer the question using ONLY the context. Be concise. If the context is "
    "insufficient, say 'Insufficient information'.\n\n"
    "Question: {q}\n\nContext:\n{ctx}\n\nAnswer:"
)

_PRIOR_PROMPT = (
    "Answer the question as best you can from your own knowledge. Be concise. "
    "If you do not know, say 'Insufficient information'.\n\n"
    "Question: {q}\n\nAnswer:"
)


@dataclass
class Row:
    dataset: str
    qid: str
    arm: str
    source_tokens: int
    context_tokens: int
    latency_ms: float
    score: float
    skipped: bool = False
    note: str = ""


def _hints(question: str) -> list[str]:
    return [t for t in top_terms(question, n=8) if t and t.strip()]


def _summarize_facts(
    text: str,
    question: str,
    *,
    max_length: int,
    max_facts: int,
    include_toc: bool = False,
    use_hints: bool = True,
) -> str:
    hints = _hints(question) if use_hints else []
    parts: list[str] = []
    if include_toc:
        outline = toc(text)
        if outline:
            parts.append("Table of contents:\n" + "\n".join(str(x) for x in outline))
    summary = lede.summarize(
        text,
        max_length=max_length,
        hints=hints or None,
        hint_focus=0.5,
        hint_mode="soft",
        keep_headings=True,
    ).summary
    if summary:
        parts.append(summary)
    facts = key_facts(text, max_facts=max_facts, hints=hints or None)
    if facts:
        parts.append("Key facts:\n" + "\n".join(f"- {f}" for f in facts))
    return "\n\n".join(parts)


def _query_docs(bundle: DatasetBundle, query: Query) -> tuple[list[CorpusDoc], str]:
    """Return query-associated docs when the loader exposes that mapping."""
    raw_qid = query.qid.split(":q:", 1)[-1]
    docs = [d for d in bundle.corpus_docs if d.metadata.get("from_query") == raw_qid]
    if docs:
        return docs, "query_docs"
    return bundle.corpus_docs, "full_corpus"


def _docs_text(docs: list[CorpusDoc]) -> str:
    return "\n\n".join(d.text for d in docs)


def _chunks_text(chunks) -> str:
    return "\n\n".join(c.content for c in chunks)


def _budget_for_tokens(source_tokens: int) -> int:
    return min(64_000, max(8_000, int(source_tokens * 4 * 0.12)))


async def _answer_and_score(
    client: httpx.AsyncClient,
    key: str,
    q: Query,
    *,
    arm: str,
    context: str,
    source_tokens: int,
    prompt: str = _CTX_PROMPT,
    note: str = "",
) -> Row:
    t0 = time.perf_counter()
    ans = await _chat(client, key, _GEN_MODEL, prompt.format(q=q.question, ctx=context))
    score = await _judge(client, key, q.question, ans, q.answers)
    return Row(
        dataset=q.qid.split(":q:", 1)[0],
        qid=q.qid,
        arm=arm,
        source_tokens=source_tokens,
        context_tokens=_ntokens(context),
        latency_ms=round((time.perf_counter() - t0) * 1000, 1),
        score=score,
        note=note,
    )


async def _run_dataset(
    ds: str,
    subset: int,
    seed: int,
    dsn: str,
    key: str,
    top_ks: list[int],
    max_direct_tokens: int,
) -> list[Row]:
    bundle = get_loader(ds)(subset=subset, seed=seed)
    ns = namespace_for(ds, "lede_spacy")
    rag = GraphRAG(
        dsn=dsn,
        namespace=ns,
        embedding_model=PINNED_EMBEDDING_MODEL,
        embedding_dim=PINNED_EMBEDDING_DIM,
        llm_base_url="",
    )
    await rag.connect()
    rows: list[Row] = []
    doc_summary_cache: dict[tuple[str, str], str] = {}
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            for q in bundle.queries:
                # A. LLM prior: no retrieval, no context.
                rows.append(
                    await _answer_and_score(
                        client,
                        key,
                        q,
                        arm="llm_prior",
                        context="",
                        source_tokens=0,
                        prompt=_PRIOR_PROMPT,
                    )
                )

                # B. Query docs when available; otherwise full corpus.
                docs, docs_kind = _query_docs(bundle, q)
                docs_ctx = _docs_text(docs)
                docs_tok = _ntokens(docs_ctx)
                if docs_tok <= max_direct_tokens:
                    rows.append(
                        await _answer_and_score(
                            client,
                            key,
                            q,
                            arm=f"{docs_kind}_llm",
                            context=docs_ctx,
                            source_tokens=docs_tok,
                            note=f"{len(docs)} docs",
                        )
                    )
                else:
                    rows.append(
                        Row(
                            ds,
                            q.qid,
                            f"{docs_kind}_llm",
                            docs_tok,
                            0,
                            0.0,
                            0.0,
                            skipped=True,
                            note=f"{docs_tok} tokens exceeds --max-direct-tokens",
                        )
                    )

                # C. Raw retrieved chunks at multiple top-Ks.
                retrieved: dict[int, str] = {}
                for k in top_ks:
                    rag.config.top_k = k
                    res = await rag.query(q.question, mode="hybrid", namespace=ns)
                    ctx = _chunks_text(res.chunks)
                    retrieved[k] = ctx
                    rows.append(
                        await _answer_and_score(
                            client,
                            key,
                            q,
                            arm=f"chunks_{k}",
                            context=ctx,
                            source_tokens=_ntokens(ctx),
                        )
                    )

                anchor_k = min(top_ks)
                anchor_chunks = retrieved[anchor_k]

                # D/E. Precomputed full/query-doc summary + facts, with and without hints.
                for use_hints, label in (
                    (False, "doc_summary_facts"),
                    (True, "hint_doc_summary_facts"),
                ):
                    # Hint-biased summaries are question-specific. Non-hinted
                    # full-corpus summaries can be reused across questions.
                    owner = q.qid if (docs_kind == "query_docs" or use_hints) else ds
                    cache_key = (owner, label)
                    if cache_key not in doc_summary_cache:
                        doc_summary_cache[cache_key] = _summarize_facts(
                            docs_ctx,
                            q.question,
                            max_length=_budget_for_tokens(docs_tok),
                            max_facts=30,
                            include_toc=False,
                            use_hints=use_hints,
                        )
                    summary = doc_summary_cache[cache_key]
                    rows.append(
                        await _answer_and_score(
                            client,
                            key,
                            q,
                            arm=label,
                            context=summary,
                            source_tokens=docs_tok,
                            note=docs_kind,
                        )
                    )
                    rows.append(
                        await _answer_and_score(
                            client,
                            key,
                            q,
                            arm=f"{label}_plus_chunks{anchor_k}",
                            context=summary + "\n\nRetrieved chunks:\n" + anchor_chunks,
                            source_tokens=docs_tok + _ntokens(anchor_chunks),
                            note=docs_kind,
                        )
                    )

                # F. Full/query-doc TOC + facts summary, then chunk summary.
                toc_summary = _summarize_facts(
                    docs_ctx,
                    q.question,
                    max_length=_budget_for_tokens(docs_tok),
                    max_facts=30,
                    include_toc=True,
                    use_hints=True,
                )
                chunk_summary = _summarize_facts(
                    anchor_chunks,
                    q.question,
                    max_length=max(2000, min(16_000, _ntokens(anchor_chunks) * 2)),
                    max_facts=12,
                    include_toc=False,
                    use_hints=True,
                )
                rows.append(
                    await _answer_and_score(
                        client,
                        key,
                        q,
                        arm="toc_doc_summary_plus_chunk_summary",
                        context=toc_summary + "\n\nRetrieved summary:\n" + chunk_summary,
                        source_tokens=docs_tok + _ntokens(anchor_chunks),
                        note=docs_kind,
                    )
                )
                print(f"  {ds} {q.qid[:24]} done", file=sys.stderr)
    finally:
        await rag.close()
    return rows


def _aggregate(rows: list[Row]) -> str:
    groups: dict[str, list[Row]] = defaultdict(list)
    for r in rows:
        if not r.skipped:
            groups[r.arm].append(r)
    lines = [
        "| arm | n | avg source tokens | avg ctx tokens | compression | accuracy | latency ms |",
        "|---|---|---|---|---|---|---|",
    ]
    for arm, rs in sorted(
        groups.items(), key=lambda kv: -sum(r.score for r in kv[1]) / len(kv[1])
    ):
        n = len(rs)
        src = sum(r.source_tokens for r in rs) / n
        ctx = sum(r.context_tokens for r in rs) / n
        comp = f"{(1 - ctx / src) * 100:.0f}%" if src else "n/a"
        acc = sum(r.score for r in rs) / n
        lat = sum(r.latency_ms for r in rs) / n
        lines.append(
            f"| {arm} | {n} | {src:.0f} | {ctx:.0f} | {comp} | {acc * 100:.0f}% | {lat:.0f} |"
        )
    return "\n".join(lines)


async def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="larger-context grounding sweep")
    p.add_argument("--dataset", default="all", help="mhr,musique,twowiki or all")
    p.add_argument("--subset", type=int, default=5)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--top-ks", default="10,20,30")
    p.add_argument("--max-direct-tokens", type=int, default=120_000)
    p.add_argument("--dsn", default=DEFAULT_DSN)
    p.add_argument("--out", default="benchmarks/showcase/grounding_results")
    a = p.parse_args(argv)

    datasets = ["mhr", "musique", "twowiki"] if a.dataset == "all" else a.dataset.split(",")
    top_ks = [int(x) for x in a.top_ks.split(",") if x.strip()]
    key = _api_key()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    all_rows: list[Row] = []
    for ds in datasets:
        print(f"=== {ds} (subset={a.subset}) ===", file=sys.stderr)
        all_rows.extend(
            await _run_dataset(
                ds,
                a.subset,
                a.seed,
                a.dsn,
                key,
                top_ks,
                a.max_direct_tokens,
            )
        )

    (out / "rows.jsonl").write_text("\n".join(json.dumps(asdict(r)) for r in all_rows))
    table = _aggregate(all_rows)
    per_ds = []
    for ds in datasets:
        ds_rows = [r for r in all_rows if r.dataset == ds]
        if ds_rows:
            per_ds.append(f"\n## {ds}\n\n{_aggregate(ds_rows)}")
    (out / "summary.md").write_text(
        f"# Larger-context grounding sweep\n\n"
        f"Datasets: {', '.join(datasets)} | subset={a.subset} | "
        f"top_ks={','.join(map(str, top_ks))} | gen={_GEN_MODEL}\n\n"
        f"## Overall\n\n{table}\n" + "\n".join(per_ds) + "\n"
    )
    print("\n" + table, file=sys.stderr)
    print(f"\nwrote {out}/summary.md", file=sys.stderr)


if __name__ == "__main__":
    asyncio.run(main())
