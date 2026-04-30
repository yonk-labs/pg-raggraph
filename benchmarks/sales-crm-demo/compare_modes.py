"""Run the 5 sample CRM queries through every retrieval mode and compare.

Captures: answer, latency, chunk count, smart-router sub-mode (when applicable).
LLM-judges each answer for relative quality so the per-mode comparison
isn't just qualitative.
"""

from __future__ import annotations

import asyncio
import json
import os
import time

import httpx

from pg_raggraph import GraphRAG

DSN = os.environ.get("PGRG_DSN", "postgresql://postgres:postgres@localhost:5434/pg_raggraph")
NAMESPACE = os.environ.get("PGRG_NAMESPACE", "sales_crm_demo_small")

MODES = ["naive", "naive_boost", "local", "global", "hybrid", "smart"]

QUESTIONS = [
    "What objections came up most often in our closed-won deals?",
    "What customers bought ClarityDB Guardian and what was their main pain point?",
    "Which products were mentioned alongside competitor products?",
    "What's the most common reason we win deals?",
    "Which industries had the most won deals?",
]

OPENAI_URL = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
OPENAI_KEY = os.environ["OPENAI_API_KEY"]
JUDGE_MODEL = "gpt-4o-mini"

JUDGE_PROMPT = """You are evaluating a RAG system's answer to a question \
about a corpus of sales call notes (won deals).

Score the answer on this 0-3 rubric:
  3 = STRONG — directly answers the question with specific names/details \
grounded in the retrieved context. Cites multiple distinct sources.
  2 = OK — touches the question with some specifics, but partial or shallow.
  1 = WEAK — vague, generic, or covers only one example when the question \
implies aggregation.
  0 = WRONG/EMPTY — fabricated, off-topic, or honestly declines but the \
corpus DOES likely contain the answer.

Important: if the system honestly declines AND the corpus genuinely lacks \
the info (e.g., closed-won notes don't dwell on objections), score 2 — \
that's correct behavior.

Return ONLY a JSON object: {"score": 0|1|2|3, "rationale": "brief reason"}"""


async def judge(client, question, answer, chunk_excerpts):
    user_content = (
        f"QUESTION:\n{question}\n\n"
        f"SYSTEM ANSWER:\n{answer}\n\n"
        f"RETRIEVED CHUNKS (top 3):\n"
        + "\n\n---\n\n".join(c[:500] for c in chunk_excerpts)
    )
    resp = await client.post(
        f"{OPENAI_URL}/chat/completions",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {OPENAI_KEY}",
        },
        json={
            "model": JUDGE_MODEL,
            "messages": [
                {"role": "system", "content": JUDGE_PROMPT},
                {"role": "user", "content": user_content},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.0,
        },
        timeout=60,
    )
    resp.raise_for_status()
    raw = resp.json()["choices"][0]["message"]["content"]
    try:
        d = json.loads(raw)
        return int(d.get("score", 0)), d.get("rationale", "")[:200]
    except (json.JSONDecodeError, ValueError, TypeError):
        return 0, raw[:100]


async def main():
    rag = GraphRAG(
        dsn=DSN,
        namespace=NAMESPACE,
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4o-mini",
        llm_api_key=OPENAI_KEY,
    )
    await rag.connect()

    rows = []
    async with httpx.AsyncClient() as client:
        for qi, q in enumerate(QUESTIONS, 1):
            print(f"\n[Q{qi}] {q[:80]}")
            for mode in MODES:
                t0 = time.perf_counter()
                try:
                    result = await rag.ask(q, mode=mode, namespace=NAMESPACE)
                    answer = (result.answer or "").strip()
                    latency_ms = (time.perf_counter() - t0) * 1000
                    excerpts = [c.content for c in result.chunks[:3]]
                except Exception as e:
                    rows.append({
                        "qid": qi, "question": q, "mode": mode,
                        "answer": "", "score": 0, "rationale": f"error: {e}",
                        "latency_ms": 0, "chunks": 0,
                        "effective_mode": mode,
                    })
                    print(f"  {mode:14s} ERROR: {e}")
                    continue
                score, rationale = await judge(client, q, answer, excerpts)
                rows.append({
                    "qid": qi, "question": q, "mode": mode,
                    "effective_mode": result.query_mode,
                    "answer": answer[:300],
                    "score": score, "rationale": rationale,
                    "latency_ms": round(latency_ms, 0),
                    "chunks": len(result.chunks),
                })
                print(
                    f"  {mode:14s} score={score} lat={latency_ms:>5.0f}ms "
                    f"effective={result.query_mode}"
                )

    await rag.close()

    # Aggregate by mode
    by_mode = {m: [] for m in MODES}
    for r in rows:
        by_mode[r["mode"]].append(r)

    print()
    print("=" * 70)
    print("AGGREGATE — judge score (avg, OpenAI gpt-4o-mini, 0-3 rubric)")
    print("=" * 70)
    print(f"{'mode':<14}{'avg score':>10}{'avg lat':>10}{'wins':>8}")
    print("-" * 50)
    for mode in MODES:
        rs = by_mode[mode]
        if not rs:
            continue
        avg_score = sum(r["score"] for r in rs) / len(rs)
        avg_lat = sum(r["latency_ms"] for r in rs) / len(rs)
        # "wins" = number of questions where this mode tied for top score
        wins = 0
        for qi in {r["qid"] for r in rs}:
            top = max(r["score"] for r in rows if r["qid"] == qi)
            mine = next(r["score"] for r in rs if r["qid"] == qi)
            if mine == top:
                wins += 1
        print(f"{mode:<14}{avg_score:>10.2f}{avg_lat:>9.0f}ms{wins:>8d}")

    out_path = "benchmarks/sales-crm-demo/_logs/mode-comparison.json"
    with open(out_path, "w") as f:
        json.dump({"rows": rows}, f, indent=2)
    print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
