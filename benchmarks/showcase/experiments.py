"""10-strategy bake-off: can we make the summary context beat plain chunks?

Each strategy turns the retrieved top-K chunks into an LLM context string; we
then generate an answer (gpt-5-mini) and judge it vs gold. Measures context
tokens, accuracy, latency. All arms feed the LLM (extractive summaries can't
abstain on 'insufficient information' golds, so summary-only is not tested here).

Strategies:
  1. chunks            - raw chunks (control / baseline RAG)
  2. summary           - concat → lede.summarize (control, current behavior)
  3. summary_long      - same, max_length=4000 (does more budget recover acc?)
  4. summary_facts     - summary + appended lede.key_facts (facts augment prose)
  5. facts_only        - lede.key_facts(15) only (facts replace prose)
  6. per_chunk_summary - summarize EACH chunk (short) then concat (option B)
  7. per_chunk_facts   - key_facts per chunk then concat (option B, facts)
  8. summary_plus_top2 - summary + top-2 chunks verbatim (breadth + detail)
  9. hint_focus_high   - summarize with hint_focus=0.95 (max query focus)
  10. correlate_facts  - lede.correlate_facts structured S-R-V facts

Usage:
    uv run python -m benchmarks.showcase.experiments --dataset all --subset 30
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
from lede.extract import correlate_facts, key_facts, top_terms

from benchmarks.e2e.config import DEFAULT_DSN, PINNED_EMBEDDING_DIM, PINNED_EMBEDDING_MODEL
from benchmarks.e2e.datasets import get as get_loader
from benchmarks.e2e.ingest import namespace_for
from benchmarks.showcase.sweep import _GEN_MODEL, _GEN_PROMPT, _api_key, _chat, _judge, _ntokens
from pg_raggraph import GraphRAG


def _hints(question: str) -> list[str]:
    return [t for t in top_terms(question, n=6) if t and t.strip()]


def _summary(text: str, hints, *, max_length=2000, hint_focus=0.5, keep_headings=True) -> str:
    return lede.summarize(
        text,
        max_length=max_length,
        hints=hints or None,
        hint_focus=hint_focus,
        hint_mode="soft",
        keep_headings=keep_headings,
    ).summary


def build_context(strategy: str, question: str, chunks) -> str:
    """Turn retrieved chunks into the LLM context string for a given strategy."""
    hints = _hints(question)
    concat = "\n\n".join(c.content for c in chunks)
    if strategy == "chunks":
        return concat
    if strategy == "summary":
        return _summary(concat, hints)
    if strategy == "summary_long":
        return _summary(concat, hints, max_length=4000)
    if strategy == "summary_facts":
        facts = key_facts(concat, max_facts=10, hints=hints or None)
        return _summary(concat, hints) + "\n\nKey facts:\n" + "\n".join(f"- {f}" for f in facts)
    if strategy == "facts_only":
        facts = key_facts(concat, max_facts=15, hints=hints or None)
        return "\n".join(f"- {f}" for f in facts)
    if strategy == "per_chunk_summary":
        return "\n\n".join(
            _summary(c.content, hints, max_length=250, keep_headings=False) for c in chunks
        )
    if strategy == "per_chunk_facts":
        out = []
        for c in chunks:
            out.extend(key_facts(c.content, max_facts=3, hints=hints or None))
        return "\n".join(f"- {f}" for f in out)
    if strategy == "summary_plus_top2":
        top2 = "\n\n".join(c.content for c in chunks[:2])
        return _summary(concat, hints) + "\n\nTop sources:\n" + top2
    if strategy == "hint_focus_high":
        return _summary(concat, hints, hint_focus=0.95)
    if strategy == "correlate_facts":
        pfs = correlate_facts(concat, hints=hints or None)
        return "\n".join(f"- {getattr(p, 'text', str(p))}" for p in pfs)
    raise ValueError(f"unknown strategy {strategy}")


STRATEGIES = [
    "chunks",
    "summary",
    "summary_long",
    "summary_facts",
    "facts_only",
    "per_chunk_summary",
    "per_chunk_facts",
    "summary_plus_top2",
    "hint_focus_high",
    "correlate_facts",
]


@dataclass
class Row:
    dataset: str
    qid: str
    strategy: str
    context_tokens: int
    latency_ms: float
    score: float


async def _run_dataset(
    ds: str, subset: int, seed: int, dsn: str, key: str, top_k: int
) -> list[Row]:
    bundle = get_loader(ds)(subset=subset, seed=seed)
    ns = namespace_for(ds, "lede_spacy")
    rag = GraphRAG(
        dsn=dsn,
        namespace=ns,
        embedding_model=PINNED_EMBEDDING_MODEL,
        embedding_dim=PINNED_EMBEDDING_DIM,
        llm_base_url="",
        top_k=top_k,
    )
    await rag.connect()
    rows: list[Row] = []
    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            for q in bundle.queries:
                res = await rag.query(q.question, mode="naive", namespace=ns)
                for strat in STRATEGIES:
                    t0 = time.perf_counter()
                    try:
                        ctx = build_context(strat, q.question, res.chunks)
                    except Exception as e:  # a strategy failing shouldn't kill the sweep
                        print(f"  ! {strat} failed on {q.qid[:16]}: {e}", file=sys.stderr)
                        continue
                    ctx_tok = _ntokens(ctx)
                    ans = await _chat(
                        client, key, _GEN_MODEL, _GEN_PROMPT.format(q=q.question, ctx=ctx)
                    )
                    lat = (time.perf_counter() - t0) * 1000
                    score = await _judge(client, key, q.question, ans, q.answers)
                    rows.append(Row(ds, q.qid, strat, ctx_tok, round(lat, 1), score))
                print(f"  {ds} {q.qid[:24]} done", file=sys.stderr)
    finally:
        await rag.close()
    return rows


def _aggregate(rows: list[Row]) -> str:
    by_strat: dict[str, list[Row]] = defaultdict(list)
    for r in rows:
        by_strat[r.strategy].append(r)
    base = by_strat.get("chunks", [])
    base_tok = (sum(r.context_tokens for r in base) / len(base)) if base else 0.0

    lines = [
        "| strategy | n | avg ctx tokens | tok reduction | accuracy | avg latency ms |",
        "|---|---|---|---|---|---|",
    ]
    # Order by accuracy desc for readability.
    ordered = sorted(by_strat.items(), key=lambda kv: -sum(r.score for r in kv[1]) / len(kv[1]))
    for strat, rs in ordered:
        n = len(rs)
        avg_tok = sum(r.context_tokens for r in rs) / n
        red = f"{(1 - avg_tok / base_tok) * 100:.0f}%" if base_tok else "—"
        acc = sum(r.score for r in rs) / n
        lat = sum(r.latency_ms for r in rs) / n
        lines.append(f"| {strat} | {n} | {avg_tok:.0f} | {red} | {acc * 100:.0f}% | {lat:.0f} |")
    return "\n".join(lines)


async def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="10-strategy summarization bake-off")
    p.add_argument("--dataset", default="all")
    p.add_argument("--subset", type=int, default=30)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--top-k", type=int, default=10)
    p.add_argument("--dsn", default=DEFAULT_DSN)
    p.add_argument("--out", default="benchmarks/showcase/experiments_results")
    a = p.parse_args(argv)

    datasets = ["mhr", "musique", "twowiki"] if a.dataset == "all" else a.dataset.split(",")
    key = _api_key()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    all_rows: list[Row] = []
    for ds in datasets:
        print(f"=== {ds} (subset={a.subset}) ===", file=sys.stderr)
        all_rows.extend(await _run_dataset(ds, a.subset, a.seed, a.dsn, key, a.top_k))

    (out / "rows.jsonl").write_text("\n".join(json.dumps(asdict(r)) for r in all_rows))
    # Overall + per-dataset tables.
    table = _aggregate(all_rows)
    per_ds = []
    for ds in datasets:
        ds_rows = [r for r in all_rows if r.dataset == ds]
        if ds_rows:
            per_ds.append(f"\n## {ds}\n\n{_aggregate(ds_rows)}")
    (out / "summary.md").write_text(
        f"# 10-strategy summarization bake-off\n\n"
        f"Datasets: {', '.join(datasets)} | subset={a.subset} | top_k={a.top_k} | gen={_GEN_MODEL}\n\n"
        f"## Overall\n\n{table}\n" + "\n".join(per_ds) + "\n"
    )
    print("\n" + table, file=sys.stderr)
    print(f"\nwrote {out}/summary.md", file=sys.stderr)


if __name__ == "__main__":
    asyncio.run(main())
