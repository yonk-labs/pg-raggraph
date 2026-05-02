"""Run the MuSiQue benchmark against pg-raggraph.

For each (question, mode) pair:
  - call rag.ask() to get an answer and retrieved chunks
  - score EM / F1 vs the gold answer (MuSiQue's official metrics)
  - score "supporting recall" — fraction of gold supporting docs that
    appear in the top-k retrieved chunks
  - optionally LLM-judge with local Qwen and/or OpenAI gpt-4o-mini

Aggregations: by mode, and by hop class (2hop / 3hop / 4hop).

Usage:
  uv run python benchmarks/musique/run.py --judge both
  uv run python benchmarks/musique/run.py --judge local --modes naive,hybrid
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import string
import sys
import time
from collections import Counter
from pathlib import Path

import httpx

from pg_raggraph import GraphRAG

ROOT = Path(__file__).parent
QUESTIONS_PATH = ROOT / "questions.json"
RESULTS_DIR = ROOT / "_results"
NAMESPACE = "bench_musique"
DSN = os.environ.get("PGRG_DSN", "postgresql://postgres:postgres@localhost:5434/pg_raggraph")
ANSWER_URL = os.environ.get("PGRG_TEST_LLM_URL", "http://192.168.1.193:8000/v1")
ANSWER_MODEL = os.environ.get("PGRG_TEST_LLM_MODEL", "Intel/Qwen3-Coder-Next-int4-AutoRound")

DEFAULT_MODES = ["naive", "naive_boost", "hybrid", "smart"]


# ---------------------------------------------------------------------------
# EM / F1 — SQuAD-style normalization, MuSiQue's official metric scheme
# ---------------------------------------------------------------------------

_ARTICLES = re.compile(r"\b(a|an|the)\b", re.UNICODE)
_PUNCT_TABLE = str.maketrans("", "", string.punctuation)


def _normalize(text: str) -> str:
    text = text.lower()
    text = text.translate(_PUNCT_TABLE)
    text = _ARTICLES.sub(" ", text)
    text = " ".join(text.split())
    return text


def em(pred: str, golds: list[str]) -> int:
    p = _normalize(pred)
    return int(any(p == _normalize(g) for g in golds))


def f1(pred: str, golds: list[str]) -> float:
    """Token-overlap F1, max over gold answers."""
    p_tokens = _normalize(pred).split()
    if not p_tokens:
        return 0.0
    best = 0.0
    for g in golds:
        g_tokens = _normalize(g).split()
        if not g_tokens:
            continue
        common = Counter(p_tokens) & Counter(g_tokens)
        overlap = sum(common.values())
        if overlap == 0:
            continue
        precision = overlap / len(p_tokens)
        recall = overlap / len(g_tokens)
        score = 2 * precision * recall / (precision + recall)
        if score > best:
            best = score
    return best


# ---------------------------------------------------------------------------
# Supporting recall — did retrieval find the gold paragraphs?
# ---------------------------------------------------------------------------


def supporting_recall(supporting: list[dict], retrieved_chunks: list) -> float:
    """Fraction of gold supporting paragraphs found in retrieved chunks.

    Match heuristic: the supporting paragraph's title appears as the
    document source / metadata for any retrieved chunk. We compare
    against the chunk's content (which always starts with `# Title`
    because that's how prepare.py wrote the docs).
    """
    if not supporting:
        return 1.0
    titles = [s["title"] for s in supporting]
    chunk_texts = [(c.content or "")[:300].lower() for c in retrieved_chunks]
    found = 0
    for title in titles:
        norm = title.lower()
        if any(norm in t for t in chunk_texts):
            found += 1
    return found / len(titles)


# ---------------------------------------------------------------------------
# LLM judge (mirrors run_llm_judge.py)
# ---------------------------------------------------------------------------

JUDGE_PROMPT = """You are evaluating whether a RAG system's answer is correct \
for a given question. You will be given the question, the gold answer, the \
system's answer, and the source chunks the system retrieved.

Score the answer on this 0-3 rubric:
  3 = FULLY_CORRECT — the system answer matches the gold answer (or a clear \
synonym / equivalent phrasing) and is supported by the chunks.
  2 = MOSTLY_CORRECT — addresses the gold answer with minor imprecision \
(e.g., partial name, missing qualifier).
  1 = PARTIAL — touches the topic but misses the gold answer, OR makes \
claims unsupported by the retrieved chunks.
  0 = WRONG — the system answer is incorrect, off-topic, fabricated, or empty.

Return ONLY a JSON object: {"score": 0|1|2|3, "rationale": "brief reason"}"""


class JudgeConfig:
    def __init__(self, kind: str):
        if kind == "local":
            self.url = ANSWER_URL
            self.model = ANSWER_MODEL
            self.api_key = ""
            self.label = f"local ({ANSWER_MODEL.split('/')[-1]})"
        elif kind == "openai":
            self.url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
            self.model = os.environ.get("OPENAI_JUDGE_MODEL", "gpt-4o-mini")
            self.api_key = os.environ.get("OPENAI_API_KEY", "").strip()
            if not self.api_key:
                print(
                    "ERROR: --judge openai requires OPENAI_API_KEY in env.",
                    file=sys.stderr,
                )
                sys.exit(2)
            self.label = f"openai ({self.model})"
        else:
            raise ValueError(f"Unknown judge kind: {kind!r}")
        self.kind = kind


async def llm_judge(
    client: httpx.AsyncClient,
    judge: JudgeConfig,
    question: str,
    gold_answer: str,
    answer: str,
    chunk_excerpts: list[str],
) -> tuple[int, str]:
    user_content = (
        f"QUESTION:\n{question}\n\n"
        f"GOLD ANSWER:\n{gold_answer}\n\n"
        f"SYSTEM ANSWER:\n{answer}\n\n"
        f"RETRIEVED CHUNKS (top {len(chunk_excerpts)}):\n"
        + "\n\n---\n\n".join(c[:600] for c in chunk_excerpts)
    )
    headers = {"Content-Type": "application/json"}
    if judge.api_key:
        headers["Authorization"] = f"Bearer {judge.api_key}"
    try:
        resp = await client.post(
            f"{judge.url}/chat/completions",
            headers=headers,
            json={
                "model": judge.model,
                "messages": [
                    {"role": "system", "content": JUDGE_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                "response_format": {"type": "json_object"},
                "temperature": 0.0,
            },
            timeout=120,
        )
        resp.raise_for_status()
    except Exception as e:
        return 0, f"judge error: {e}"
    raw = resp.json()["choices"][0]["message"]["content"]
    try:
        data = json.loads(raw)
        score = int(data.get("score", 0))
        rationale = data.get("rationale", "")[:300]
    except (json.JSONDecodeError, ValueError, TypeError):
        score = 0
        rationale = f"unparseable: {raw[:200]}"
    return max(0, min(3, score)), rationale


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--modes",
        default=",".join(DEFAULT_MODES),
        help=f"Comma-separated list of modes (default: {','.join(DEFAULT_MODES)})",
    )
    parser.add_argument(
        "--judge",
        choices=["none", "local", "openai", "both"],
        default="local",
    )
    parser.add_argument("--limit", type=int, default=0, help="Cap on questions (0 = all)")
    parser.add_argument(
        "--short-answer",
        action="store_true",
        help="Tell rag.ask() to return a short factoid answer (≤10 tokens). "
        "Required for fair EM/F1 vs MuSiQue gold short-form answers.",
    )
    parser.add_argument(
        "--rerank",
        action="store_true",
        help="Enable cross-encoder reranking. Fetches top_k * rerank_factor "
        "candidates, rescore with BAAI/bge-reranker-base, trim back to top_k. "
        "Adds ~30-80 ms p50 latency, zero per-query LLM cost.",
    )
    parser.add_argument(
        "--out-tag",
        default=time.strftime("%Y%m%d-%H%M%S"),
        help="Tag suffix for the result file",
    )
    args = parser.parse_args()

    modes = [m.strip() for m in args.modes.split(",") if m.strip()]
    print(f"Modes: {modes}")
    print(f"Judge: {args.judge}")

    with open(QUESTIONS_PATH) as f:
        questions = json.load(f)
    if args.limit > 0:
        questions = questions[: args.limit]
    print(
        f"Questions: {len(questions)} (hop counts: "
        f"2hop={sum(1 for q in questions if q['hop_class'] == '2hop')}, "
        f"3hop={sum(1 for q in questions if q['hop_class'] == '3hop')}, "
        f"4hop={sum(1 for q in questions if q['hop_class'] == '4hop')})"
    )

    judge_local = JudgeConfig("local") if args.judge in ("local", "both") else None
    judge_openai = JudgeConfig("openai") if args.judge in ("openai", "both") else None

    rag = GraphRAG(
        dsn=DSN,
        namespace=NAMESPACE,
        llm_base_url=ANSWER_URL,
        llm_model=ANSWER_MODEL,
    )
    await rag.connect()

    rows: list[dict] = []
    total = len(questions) * len(modes)
    done = 0
    t_start = time.perf_counter()

    async with httpx.AsyncClient() as client:
        for q in questions:
            golds = [q["answer"]] + (q.get("answer_aliases") or [])
            for mode in modes:
                t0 = time.perf_counter()
                try:
                    result = await rag.ask(
                        q["question"],
                        mode=mode,
                        namespace=NAMESPACE,
                        short_answer=args.short_answer,
                        rerank=args.rerank,
                    )
                    answer = (result.answer or "").strip()
                    chunks = list(result.chunks)[:5]
                    latency_ms = (time.perf_counter() - t0) * 1000
                except Exception as e:
                    rows.append(
                        {
                            "qid": q["id"],
                            "hop_class": q["hop_class"],
                            "mode": mode,
                            "question": q["question"],
                            "gold": q["answer"],
                            "answer": "",
                            "em": 0,
                            "f1": 0.0,
                            "support_recall": 0.0,
                            "latency_ms": 0,
                            "error": str(e),
                        }
                    )
                    done += 1
                    continue

                row = {
                    "qid": q["id"],
                    "hop_class": q["hop_class"],
                    "mode": mode,
                    "question": q["question"],
                    "gold": q["answer"],
                    "gold_aliases": q.get("answer_aliases", []),
                    "answer": answer[:500],
                    "em": em(answer, golds),
                    "f1": round(f1(answer, golds), 3),
                    "support_recall": round(supporting_recall(q["supporting"], chunks), 3),
                    "latency_ms": round(latency_ms, 0),
                }
                if judge_local is not None:
                    score, rationale = await llm_judge(
                        client,
                        judge_local,
                        q["question"],
                        q["answer"],
                        answer,
                        [c.content for c in chunks[:3]],
                    )
                    row["qwen_score"] = score
                    row["qwen_rationale"] = rationale
                if judge_openai is not None:
                    score, rationale = await llm_judge(
                        client,
                        judge_openai,
                        q["question"],
                        q["answer"],
                        answer,
                        [c.content for c in chunks[:3]],
                    )
                    row["openai_score"] = score
                    row["openai_rationale"] = rationale

                rows.append(row)
                done += 1

            if done % 20 == 0 or done == total:
                elapsed = time.perf_counter() - t_start
                rate = done / max(elapsed, 1e-6)
                eta = (total - done) / max(rate, 1e-6)
                print(
                    f"  progress: {done}/{total}  "
                    f"({elapsed / 60:.1f}min elapsed, ETA {eta / 60:.1f}min)",
                    flush=True,
                )

    await rag.close()

    # ----- aggregate ------------------------------------------------------
    summary = aggregate(rows, modes, args.judge)

    RESULTS_DIR.mkdir(exist_ok=True)
    out_path = RESULTS_DIR / f"results-{args.out_tag}.json"
    with open(out_path, "w") as f:
        json.dump({"summary": summary, "rows": rows}, f, indent=2)
    print(f"\nSaved: {out_path}")

    print_summary(summary, args.judge)


def aggregate(rows: list[dict], modes: list[str], judge: str) -> dict:
    by_mode = {m: [] for m in modes}
    by_mode_hop: dict[str, dict[str, list]] = {
        m: {h: [] for h in ("2hop", "3hop", "4hop")} for m in modes
    }
    for r in rows:
        by_mode[r["mode"]].append(r)
        if r["hop_class"] in by_mode_hop[r["mode"]]:
            by_mode_hop[r["mode"]][r["hop_class"]].append(r)

    def stats(rs: list[dict]) -> dict:
        n = len(rs)
        if n == 0:
            return {"n": 0}
        out = {
            "n": n,
            "em_pct": round(sum(r["em"] for r in rs) / n * 100, 1),
            "f1_pct": round(sum(r["f1"] for r in rs) / n * 100, 1),
            "support_recall_pct": round(sum(r["support_recall"] for r in rs) / n * 100, 1),
            "avg_latency_ms": round(sum(r["latency_ms"] for r in rs) / n, 0),
        }
        if judge in ("local", "both") and rs[0].get("qwen_score") is not None:
            out["qwen_pct"] = round(
                sum(r.get("qwen_score", 0) for r in rs) / max(n * 3, 1) * 100, 1
            )
        if judge in ("openai", "both") and rs[0].get("openai_score") is not None:
            out["openai_pct"] = round(
                sum(r.get("openai_score", 0) for r in rs) / max(n * 3, 1) * 100, 1
            )
        return out

    return {
        "by_mode": {m: stats(by_mode[m]) for m in modes},
        "by_mode_hop": {
            m: {h: stats(by_mode_hop[m][h]) for h in ("2hop", "3hop", "4hop")} for m in modes
        },
    }


def print_summary(summary: dict, judge: str) -> None:
    print("\n" + "=" * 80)
    print("MUSIQUE BENCHMARK — by mode")
    print("=" * 80)
    cols = ["EM", "F1", "Support"]
    if judge in ("local", "both"):
        cols.append("Qwen")
    if judge in ("openai", "both"):
        cols.append("OpenAI")
    cols.append("Latency")
    header = f"{'Mode':<14}" + "".join(f"{c:<10}" for c in cols)
    print(header)
    print("-" * len(header))
    for mode, s in summary["by_mode"].items():
        line = f"{mode:<14}"
        line += f"{s.get('em_pct', 0):>6.1f}%   "
        line += f"{s.get('f1_pct', 0):>6.1f}%   "
        line += f"{s.get('support_recall_pct', 0):>6.1f}%   "
        if judge in ("local", "both"):
            line += f"{s.get('qwen_pct', 0):>6.1f}%   "
        if judge in ("openai", "both"):
            line += f"{s.get('openai_pct', 0):>6.1f}%   "
        line += f"{s.get('avg_latency_ms', 0):>6.0f}ms"
        print(line)

    print("\nMUSIQUE — by mode × hop")
    metric_cols = ["em_pct", "f1_pct", "support_recall_pct"]
    if judge in ("local", "both"):
        metric_cols.append("qwen_pct")
    if judge in ("openai", "both"):
        metric_cols.append("openai_pct")
    for metric in metric_cols:
        print(f"\n  {metric}:")
        print(f"  {'mode':<14}{'2hop':>9}{'3hop':>9}{'4hop':>9}")
        for mode, hops in summary["by_mode_hop"].items():
            row = f"  {mode:<14}"
            for h in ("2hop", "3hop", "4hop"):
                row += f"{hops[h].get(metric, 0):>8.1f}%"
            print(row)


if __name__ == "__main__":
    asyncio.run(main())
