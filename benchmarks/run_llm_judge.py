"""LLM-judge benchmark for pg-raggraph on PG-docs and NTSB corpora.

Why this script exists alongside `run_benchmark.py`:
  * `run_benchmark.py` measures *keyword recall* — % of expected keywords
    found in retrieved chunks. Cheap, deterministic, zero LLM cost. But
    it has known limitations: synonym blindness, "right keywords in
    wrong context", no measurement of answer quality.
  * `run_llm_judge.py` (this script) measures *answer quality* via LLM
    judge — generates a grounded answer with `rag.ask()`, then scores
    it 0-3 against the question using a separate LLM call. This matches
    the methodology used in `benchmarks/age-bakeoff/` for the SCOTUS
    head-to-head. More credible; uses the local vLLM as both the
    answer-generator and judge so cost stays at $0.

Outputs:
  * `benchmarks/llm-judge-results-<timestamp>.json` — full per-question
    rows with answer text, judge score, and rationale.
  * Console summary table printed at the end.

Usage:
  uv run python benchmarks/run_llm_judge.py --corpus postgres
  uv run python benchmarks/run_llm_judge.py --corpus ntsb
  uv run python benchmarks/run_llm_judge.py --corpus both
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from datetime import datetime
from pathlib import Path

import httpx

from pg_raggraph import GraphRAG

DSN = os.environ.get(
    "PGRG_DSN", "postgresql://postgres:postgres@localhost:5434/pg_raggraph"
)
LLM_URL = os.environ.get("PGRG_TEST_LLM_URL", "http://192.168.1.193:8000/v1")
LLM_MODEL = os.environ.get(
    "PGRG_TEST_LLM_MODEL", "Intel/Qwen3-Coder-Next-int4-AutoRound"
)

BENCH_DIR = Path(__file__).parent

# ---------------------------------------------------------------------------
# Question sets
# ---------------------------------------------------------------------------

# Same 10 PG-docs questions as `run_benchmark.py` so results are directly
# comparable across the two methodologies.
POSTGRES_QUESTIONS = [
    "What are recursive CTEs used for in PostgreSQL?",
    "How do you create a full-text search index in PostgreSQL?",
    "What's the difference between HNSW and IVFFlat indexes in pgvector?",
    "How does PostgreSQL handle transactions and MVCC?",
    "What are the steps to back up a PostgreSQL database?",
    "How do you partition a large table in PostgreSQL?",
    "How do I build a RAG application with PostgreSQL and pgvector?",
    "What's the role of vacuuming in PostgreSQL?",
    "How do triggers interact with rules in PostgreSQL?",
    "What are the options for high availability in PostgreSQL?",
]

# NTSB corpus question set — written 2026-04-29 against the
# `kg-rag-eval/ntsb-aviation-incident-accident-reports/` corpus. 10 questions
# spanning single-incident factual queries and cross-incident pattern
# questions (the latter are where graph mode is supposed to earn its keep).
NTSB_QUESTIONS = [
    "What was the probable cause of the Cirrus SR22 accident?",
    "How did weather conditions contribute to the helicopter incidents in the corpus?",
    "What role did pilot fatigue play in any of the accidents?",
    "How does pilot certification level correlate with incident outcomes?",
    "What patterns emerge across engine failure incidents?",
    "What were the key findings about runway excursion incidents?",
    "How did the NTSB classify accidents involving inadequate preflight planning?",
    "What aircraft systems were most commonly cited as contributing factors?",
    "How does pilot experience (hours flown) relate to incident severity?",
    "What recurring maintenance issues appear in mechanical-failure reports?",
]

# ---------------------------------------------------------------------------
# Judge — local vLLM via httpx
# ---------------------------------------------------------------------------

JUDGE_PROMPT = """You are evaluating whether a RAG system's answer is correct \
for a given question. You will be given the question, the system's answer, \
and the source chunks the system retrieved.

Score the answer on this 0-3 rubric:
  3 = FULLY_CORRECT — the answer directly addresses the question, is supported \
by the retrieved chunks, and is factually accurate.
  2 = MOSTLY_CORRECT — addresses the core of the question and is largely \
supported by chunks, but has minor gaps or imprecision.
  1 = PARTIAL — the answer touches the topic but misses the question, OR \
makes claims unsupported by the retrieved chunks.
  0 = WRONG — the answer is incorrect, off-topic, or fabricated.

Return ONLY a JSON object: {"score": 0|1|2|3, "rationale": "brief reason"}"""


async def llm_judge(
    client: httpx.AsyncClient,
    question: str,
    answer: str,
    chunk_excerpts: list[str],
) -> tuple[int, str]:
    """Score one (question, answer, chunks) triple via the local vLLM judge."""
    user_content = (
        f"QUESTION:\n{question}\n\n"
        f"SYSTEM ANSWER:\n{answer}\n\n"
        f"RETRIEVED CHUNKS (top {len(chunk_excerpts)}):\n"
        + "\n\n---\n\n".join(c[:600] for c in chunk_excerpts)
    )
    resp = await client.post(
        f"{LLM_URL}/chat/completions",
        json={
            "model": LLM_MODEL,
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
    raw = resp.json()["choices"][0]["message"]["content"]
    try:
        data = json.loads(raw)
        score = int(data.get("score", 0))
        rationale = data.get("rationale", "")[:300]
    except (json.JSONDecodeError, ValueError, TypeError):
        # Fallback: try to extract a digit 0-3 from the raw text.
        score = 0
        rationale = f"unparseable judge response: {raw[:200]}"
    return max(0, min(3, score)), rationale


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


async def run_corpus(
    corpus_key: str, namespace: str, questions: list[str]
) -> dict:
    """Run all modes × all questions; LLM-judge each answer."""
    rag = GraphRAG(
        dsn=DSN,
        namespace=namespace,
        llm_base_url=LLM_URL,
        llm_model=LLM_MODEL,
    )
    await rag.connect()

    modes = ["naive", "naive_boost", "smart", "local", "global", "hybrid"]
    rows: list[dict] = []
    print(f"\n  Corpus: {corpus_key}  ({len(questions)} Qs × {len(modes)} modes "
          f"= {len(questions) * len(modes)} answers + judges)")

    async with httpx.AsyncClient() as client:
        for qi, question in enumerate(questions, 1):
            for mode in modes:
                t0 = time.perf_counter()
                try:
                    result = await rag.ask(question, mode=mode, namespace=namespace)
                    answer = (result.answer or "").strip()
                    chunk_excerpts = [c.content for c in result.chunks[:3]]
                    latency_ms = (time.perf_counter() - t0) * 1000
                except Exception as e:
                    rows.append({
                        "corpus": corpus_key,
                        "question": question,
                        "mode": mode,
                        "answer": "",
                        "score": 0,
                        "rationale": f"ask() failed: {e}",
                        "latency_ms": 0,
                    })
                    continue

                if not answer:
                    rows.append({
                        "corpus": corpus_key,
                        "question": question,
                        "mode": mode,
                        "answer": "",
                        "score": 0,
                        "rationale": "empty answer",
                        "latency_ms": latency_ms,
                    })
                    continue

                score, rationale = await llm_judge(
                    client, question, answer, chunk_excerpts
                )
                rows.append({
                    "corpus": corpus_key,
                    "question": question,
                    "mode": mode,
                    "answer": answer[:500],
                    "score": score,
                    "rationale": rationale,
                    "latency_ms": latency_ms,
                })
            print(f"    Q{qi}/{len(questions)} done")

    await rag.close()

    # Aggregate per mode
    by_mode = {m: {"scores": [], "lats": []} for m in modes}
    for r in rows:
        by_mode[r["mode"]]["scores"].append(r["score"])
        by_mode[r["mode"]]["lats"].append(r["latency_ms"])

    summary = {
        "corpus": corpus_key,
        "namespace": namespace,
        "n_questions": len(questions),
        "n_modes": len(modes),
        "by_mode": {
            m: {
                # avg_score / 3 = normalized accuracy proxy on 0-1
                "avg_score_0_3": round(
                    sum(d["scores"]) / max(len(d["scores"]), 1), 2
                ),
                "accuracy_pct": round(
                    sum(d["scores"]) / max(len(d["scores"]) * 3, 1) * 100, 1
                ),
                "fully_correct": sum(1 for s in d["scores"] if s == 3),
                "wrong_or_empty": sum(1 for s in d["scores"] if s == 0),
                "avg_latency_ms": round(
                    sum(d["lats"]) / max(len(d["lats"]), 1), 0
                )
                if d["lats"]
                else 0,
            }
            for m, d in by_mode.items()
        },
    }
    return {"summary": summary, "rows": rows}


def print_summary(corpus_key: str, summary: dict):
    print(f"\n  ======= {corpus_key} (LLM-judge, n={summary['n_questions']}) =======")
    print(f"  {'Mode':<13} {'Score (0-3)':>12} {'Acc %':>8} "
          f"{'Fully':>6} {'Wrong':>6} {'Lat ms':>8}")
    print("  " + "-" * 60)
    for mode in ["naive", "naive_boost", "smart", "local", "global", "hybrid"]:
        s = summary["by_mode"][mode]
        print(
            f"  {mode:<13} {s['avg_score_0_3']:>12} {s['accuracy_pct']:>7}% "
            f"{s['fully_correct']:>6} {s['wrong_or_empty']:>6} "
            f"{int(s['avg_latency_ms']):>8}"
        )


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default="both", choices=["postgres", "ntsb", "both"])
    args = ap.parse_args()

    plan = []
    if args.corpus in ("postgres", "both"):
        plan.append(("postgres", "bench_pg", POSTGRES_QUESTIONS))
    if args.corpus in ("ntsb", "both"):
        plan.append(("ntsb", "bench_ntsb", NTSB_QUESTIONS))

    all_results: list[dict] = []
    for corpus_key, namespace, questions in plan:
        result = await run_corpus(corpus_key, namespace, questions)
        all_results.append(result)
        print_summary(corpus_key, result["summary"])

    # Persist
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = BENCH_DIR / f"llm-judge-results-{ts}.json"
    out.write_text(json.dumps(
        {
            "generated_at": datetime.now().isoformat(),
            "judge_model": LLM_MODEL,
            "judge_url": LLM_URL,
            "results": [r["summary"] for r in all_results],
            "rows": [row for r in all_results for row in r["rows"]],
        },
        indent=2,
        default=str,
    ))
    print(f"\n  Wrote {out}")


if __name__ == "__main__":
    asyncio.run(main())
