"""Showcase sweep — does summarizing retrieved chunks beat sending raw chunks?

Runs three arms against the loaded 3rd-party bench data (Postgres only):

  - ``chunks_llm``   : retrieve top-K → send RAW chunks to the LLM → answer
  - ``summary_llm``  : retrieve top-K → lede summary → send SUMMARY to the LLM
  - ``summary_only`` : lede summary IS the answer (zero LLM calls)

crossed with knob combos:
  - retrieval_expansion ∈ {off, moderate}
  - keep_headings ∈ {off, on}   (summary arms only)

Per (dataset, question, config) it records: context tokens sent to the LLM,
LLM call count, wall-clock latency, and a judged accuracy score (0/0.5/1.0)
of the produced answer vs the gold reference.

Usage:
    OPENAI_API_KEY=$(grep -oE 'sk-[A-Za-z0-9_-]+' ../.openai) \
      uv run python -m benchmarks.showcase.sweep --dataset all --subset 10

Defaults to the bench DSN (port 5437, bge-large dim 1024) used by the e2e harness.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import httpx
import tiktoken

from benchmarks.e2e.config import DEFAULT_DSN, PINNED_EMBEDDING_DIM, PINNED_EMBEDDING_MODEL
from benchmarks.e2e.datasets import get as get_loader
from benchmarks.e2e.ingest import namespace_for
from pg_raggraph import GraphRAG
from pg_raggraph.summary import summarize_chunks

_ENC = tiktoken.get_encoding("cl100k_base")
_CACHE_DIR = Path("benchmarks/showcase/.llm_cache")
_GEN_MODEL = os.environ.get("PGRG_SHOWCASE_GEN_MODEL", "gpt-5-mini")
_JUDGE_MODEL = os.environ.get("PGRG_SHOWCASE_JUDGE_MODEL", "gpt-5-mini")
_OPENAI_BASE = "https://api.openai.com/v1"


def _api_key() -> str:
    key = os.environ.get("OPENAI_API_KEY", "")
    if key:
        return key
    # Fall back to the repo-local key file used by the e2e harness.
    for path in ("../.openai", "../../.openai"):
        p = Path(path)
        if p.exists():
            m = re.search(r"sk-[A-Za-z0-9_-]+", p.read_text())
            if m:
                return m.group(0)
    raise RuntimeError("No OPENAI_API_KEY (env or ../.openai). Set it before running.")


def _ntokens(text: str) -> int:
    return len(_ENC.encode(text or ""))


# --- cached OpenAI-compatible chat (so re-runs are free) ---
_CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _cache_path(key: str) -> Path:
    return _CACHE_DIR / f"{key}.json"


async def _chat(client: httpx.AsyncClient, key: str, model: str, prompt: str) -> str:
    cache_id = hashlib.sha256(f"{model}\x00{prompt}".encode()).hexdigest()[:32]
    cp = _cache_path(cache_id)
    if cp.exists():
        return json.loads(cp.read_text())["content"]
    body: dict = {"model": model, "messages": [{"role": "user", "content": prompt}]}
    if model.startswith("gpt-5"):
        body["reasoning_effort"] = "minimal"
    else:
        body["temperature"] = 0.0
    r = await client.post(
        f"{_OPENAI_BASE}/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json=body,
    )
    r.raise_for_status()
    content = r.json()["choices"][0]["message"]["content"]
    cp.write_text(json.dumps({"content": content}))
    return content


_GEN_PROMPT = (
    "Answer the question using ONLY the context. Be concise — a short phrase or "
    "sentence. If the context is insufficient, say 'Insufficient information'.\n\n"
    "Question: {q}\n\nContext:\n{ctx}\n\nAnswer:"
)

_JUDGE_PROMPT = (
    "You grade whether a candidate answer answers the same question as the "
    "reference answer(s). Do not require identical wording or every supporting "
    "fact; focus on semantic equivalence for the asked question.\n"
    "Question: {q}\n"
    "Candidate answer: {cand}\n"
    "Reference answer(s): {ref}\n\n"
    "Respond with strict JSON only: "
    '{{"score": <1.0|0.5|0.0>, "reason": "<short>"}}\n'
    "Scoring: 1.0 = answers the question equivalently; "
    "0.5 = partially answers / one of several refs / missing a hop; "
    "0.0 = wrong or 'insufficient' when the reference is a real answer."
)


async def _judge(client: httpx.AsyncClient, key: str, q: str, cand: str, refs: list[str]) -> float:
    prompt = _JUDGE_PROMPT.format(q=q, cand=cand or "(empty)", ref=" || ".join(refs))
    text = await _chat(client, key, _JUDGE_MODEL, prompt)
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return 0.0
    try:
        return float(json.loads(m.group(0)).get("score", 0.0))
    except (ValueError, json.JSONDecodeError):
        return 0.0


@dataclass
class Row:
    dataset: str
    qid: str
    arm: str
    expansion: str
    headings: str  # "on" | "off" | "n/a"
    context_tokens: int
    llm_calls: int
    latency_ms: float
    score: float


CONFIGS = [
    # (arm, expansion, headings)
    ("chunks_llm", "off", "n/a"),
    ("chunks_llm", "moderate", "n/a"),
    ("summary_llm", "off", "off"),
    ("summary_llm", "off", "on"),
    ("summary_llm", "moderate", "off"),
    ("summary_llm", "moderate", "on"),
    ("summary_only", "off", "off"),
    ("summary_only", "off", "on"),
    ("summary_only", "moderate", "off"),
    ("summary_only", "moderate", "on"),
]


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
        llm_base_url="",  # retrieval only; generation is a direct call here
        top_k=top_k,
    )
    await rag.connect()
    rows: list[Row] = []
    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            for q in bundle.queries:
                # Retrieve once per expansion setting (shared across arms).
                retr: dict[str, object] = {}
                for exp in ("off", "moderate"):
                    rag.config.retrieval_expansion = exp
                    t0 = time.perf_counter()
                    res = await rag.query(q.question, mode="naive", namespace=ns)
                    retr[exp] = (res, (time.perf_counter() - t0) * 1000)

                for arm, exp, headings in CONFIGS:
                    res, retr_ms = retr[exp]
                    chunks = res.chunks
                    if arm == "chunks_llm":
                        ctx = "\n\n".join(c.content for c in chunks)
                        ctx_tok = _ntokens(ctx)
                        t0 = time.perf_counter()
                        ans = await _chat(
                            client, key, _GEN_MODEL, _GEN_PROMPT.format(q=q.question, ctx=ctx)
                        )
                        gen_ms = (time.perf_counter() - t0) * 1000
                        calls = 1
                    else:
                        rag.config.summary_keep_headings = headings == "on"
                        t0 = time.perf_counter()
                        summary = summarize_chunks(q.question, res, rag.config)
                        sum_ms = (time.perf_counter() - t0) * 1000
                        ctx_tok = _ntokens(summary)
                        if arm == "summary_llm":
                            t1 = time.perf_counter()
                            ans = await _chat(
                                client,
                                key,
                                _GEN_MODEL,
                                _GEN_PROMPT.format(q=q.question, ctx=summary),
                            )
                            gen_ms = sum_ms + (time.perf_counter() - t1) * 1000
                            calls = 1
                        else:  # summary_only
                            ans = summary
                            gen_ms = sum_ms
                            calls = 0
                    score = await _judge(client, key, q.question, ans, q.answers)
                    rows.append(
                        Row(
                            dataset=ds,
                            qid=q.qid,
                            arm=arm,
                            expansion=exp,
                            headings=headings,
                            context_tokens=ctx_tok,
                            llm_calls=calls,
                            latency_ms=round(retr_ms + gen_ms, 1),
                            score=score,
                        )
                    )
                print(f"  {ds} {q.qid[:24]} done", file=sys.stderr)
    finally:
        await rag.close()
    return rows


def _aggregate(rows: list[Row]) -> str:
    """Markdown comparison table aggregated by config across all rows."""
    from collections import defaultdict

    groups: dict[tuple, list[Row]] = defaultdict(list)
    for r in rows:
        groups[(r.arm, r.expansion, r.headings)].append(r)

    # Baseline = chunks_llm / off, for token-reduction reference.
    base = groups.get(("chunks_llm", "off", "n/a"), [])
    base_tok = (sum(r.context_tokens for r in base) / len(base)) if base else 0.0

    lines = [
        "| arm | expansion | headings | n | avg ctx tokens | tok reduction | llm calls | accuracy | avg latency ms |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for (arm, exp, hd), rs in sorted(groups.items()):
        n = len(rs)
        avg_tok = sum(r.context_tokens for r in rs) / n
        red = f"{(1 - avg_tok / base_tok) * 100:.0f}%" if base_tok else "—"
        calls = sum(r.llm_calls for r in rs)
        acc = sum(r.score for r in rs) / n
        lat = sum(r.latency_ms for r in rs) / n
        lines.append(
            f"| {arm} | {exp} | {hd} | {n} | {avg_tok:.0f} | {red} | {calls} | "
            f"{acc * 100:.0f}% | {lat:.0f} |"
        )
    return "\n".join(lines)


async def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="summary-vs-chunks showcase sweep")
    p.add_argument("--dataset", default="all", help="mhr,musique,twowiki or all")
    p.add_argument("--subset", type=int, default=10)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--top-k", type=int, default=10)
    p.add_argument("--dsn", default=os.environ.get("PGRG_BENCH_DSN", DEFAULT_DSN))
    p.add_argument("--out", default="benchmarks/showcase/results")
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
    table = _aggregate(all_rows)
    (out / "summary.md").write_text(
        f"# Showcase sweep — summary vs chunks\n\n"
        f"Datasets: {', '.join(datasets)} | subset={a.subset} | top_k={a.top_k} | "
        f"gen={_GEN_MODEL} judge={_JUDGE_MODEL}\n\n{table}\n"
    )
    print("\n" + table, file=sys.stderr)
    print(f"\nwrote {out}/rows.jsonl and {out}/summary.md", file=sys.stderr)


if __name__ == "__main__":
    asyncio.run(main())
