#!/usr/bin/env python
"""Factorial end-to-end accuracy benchmark.

For each of the 12 factorial.* tables (A/B/C/D × bge-small/bge-base/nomic),
runs all 30 scotus questions end-to-end:
  1. Embed query with the cell's model
  2. Vector-search top-10 chunks from factorial.{table}
  3. Generate answer with LLM (gpt-4.1-mini)
  4. Judge answer against gold (gpt-4.1-mini)
  5. Record per-cell verdict counts

Writes:
  results/diagnostics/factorial-accuracy-fp32.json
  results/diagnostics/factorial-accuracy-fp32-REPORT.md
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path

import psycopg
import yaml
from dotenv import load_dotenv
from fastembed import TextEmbedding
from openai import AsyncOpenAI

# ── env ──────────────────────────────────────────────────────────────────────
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)

# ── constants ─────────────────────────────────────────────────────────────────
MODEL_GEN = "gpt-4.1-mini"
MODEL_JUDGE = "gpt-4.1-mini"

# gpt-4.1-mini pricing: $0.40/1M input, $1.60/1M output
_IN_RATE = 0.40 / 1_000_000
_OUT_RATE = 1.60 / 1_000_000

HARD_BUDGET_USD = 4.0
CELL_CONCURRENCY = 4

CELLS = [
    # (chunking, embedding, table, model_name, dim)
    ("A", "bge-small", "a_bge_small", "BAAI/bge-small-en-v1.5", 384),
    ("A", "bge-base",  "a_bge_base",  "BAAI/bge-base-en-v1.5",  768),
    ("A", "nomic",     "a_nomic",     "nomic-ai/nomic-embed-text-v1.5", 768),
    ("B", "bge-small", "b_bge_small", "BAAI/bge-small-en-v1.5", 384),
    ("B", "bge-base",  "b_bge_base",  "BAAI/bge-base-en-v1.5",  768),
    ("B", "nomic",     "b_nomic",     "nomic-ai/nomic-embed-text-v1.5", 768),
    ("C", "bge-small", "c_bge_small", "BAAI/bge-small-en-v1.5", 384),
    ("C", "bge-base",  "c_bge_base",  "BAAI/bge-base-en-v1.5",  768),
    ("C", "nomic",     "c_nomic",     "nomic-ai/nomic-embed-text-v1.5", 768),
    ("D", "bge-small", "d_bge_small", "BAAI/bge-small-en-v1.5", 384),
    ("D", "bge-base",  "d_bge_base",  "BAAI/bge-base-en-v1.5",  768),
    ("D", "nomic",     "d_nomic",     "nomic-ai/nomic-embed-text-v1.5", 768),
]

# ── answer + judge prompts (reused from age_bakeoff.engines.openai_answerer
#    and age_bakeoff.scorers.llm_judge for result comparability) ───────────────
_ANSWER_SYSTEM = (
    "You answer questions using only the provided context chunks. "
    "If the context does not contain the answer, say so. "
    "Be concise — 1-3 sentences unless the question demands more."
)
_ANSWER_USER_TEMPLATE = "Question: {question}\n\nContext:\n{context}\n\nAnswer:"

_JUDGE_SYSTEM = """You are grading an AI-generated answer against a reference answer.

Return strict JSON: {"verdict": "fully_correct | partially_correct | wrong | hallucinated", "rationale": "one short sentence"}

Rubric:
- fully_correct: Contains every key fact from the reference. No contradictions.
- partially_correct: Contains some facts but misses important ones.
- wrong: Contradicts the reference or misses the main point.
- hallucinated: Invents facts not in the reference."""

_JUDGE_USER_TEMPLATE = (
    "Question: {question}\nReference answer: {gold}\nGenerated answer: {generated}\n"
    "Grade the generated answer."
)

# ── cost tracker ──────────────────────────────────────────────────────────────

class CostTracker:
    def __init__(self, budget_usd: float):
        self.budget_usd = budget_usd
        self.total_usd = 0.0
        self._lock = asyncio.Lock()

    async def record(self, prompt_tokens: int, completion_tokens: int) -> None:
        cost = prompt_tokens * _IN_RATE + completion_tokens * _OUT_RATE
        async with self._lock:
            self.total_usd += cost
            if self.total_usd > self.budget_usd:
                raise RuntimeError(
                    f"Hard budget exceeded: ${self.total_usd:.4f} > ${self.budget_usd:.2f}"
                )


# ── helpers ───────────────────────────────────────────────────────────────────

def load_questions(yaml_path: Path) -> list[dict]:
    data = yaml.safe_load(yaml_path.read_text())
    return data["questions"]


def get_embedder(model_name: str, cache: dict[str, TextEmbedding]) -> TextEmbedding:
    if model_name not in cache:
        logger.info("Loading embedder: %s", model_name)
        cache[model_name] = TextEmbedding(model_name=model_name)
    return cache[model_name]


def embed_query(embedder: TextEmbedding, text: str) -> str:
    vec = list(embedder.embed([text]))[0].tolist()
    return "[" + ",".join(f"{x:.6f}" for x in vec) + "]"


def vector_search(conn: psycopg.Connection, table: str, vec_lit: str, limit: int = 10) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT id, doc_id, seq_num, original_content, metadata "
            f"FROM factorial.{table} "
            f"ORDER BY embedding <=> %s::vector LIMIT %s",
            (vec_lit, limit),
        )
        rows = cur.fetchall()
    return [
        {"id": r[0], "doc_id": r[1], "seq_num": r[2], "content": r[3], "metadata": r[4]}
        for r in rows
    ]


async def generate_answer(
    client: AsyncOpenAI,
    question: str,
    chunks: list[dict],
    tracker: CostTracker,
) -> tuple[str, float]:
    context = "\n\n---\n\n".join(c["content"] for c in chunks)
    t0 = time.perf_counter()
    resp = await client.chat.completions.create(
        model=MODEL_GEN,
        messages=[
            {"role": "system", "content": _ANSWER_SYSTEM},
            {"role": "user", "content": _ANSWER_USER_TEMPLATE.format(
                question=question, context=context
            )},
        ],
        temperature=0,
    )
    elapsed_ms = (time.perf_counter() - t0) * 1000
    if resp.usage:
        await tracker.record(resp.usage.prompt_tokens, resp.usage.completion_tokens)
    return resp.choices[0].message.content or "", elapsed_ms


async def judge_answer(
    client: AsyncOpenAI,
    question: str,
    gold_answer: str,
    generated_answer: str,
    tracker: CostTracker,
) -> str:
    resp = await client.chat.completions.create(
        model=MODEL_JUDGE,
        messages=[
            {"role": "system", "content": _JUDGE_SYSTEM},
            {"role": "user", "content": _JUDGE_USER_TEMPLATE.format(
                question=question,
                gold=gold_answer,
                generated=generated_answer,
            )},
        ],
        response_format={"type": "json_object"},
        temperature=0,
    )
    if resp.usage:
        await tracker.record(resp.usage.prompt_tokens, resp.usage.completion_tokens)
    content = resp.choices[0].message.content or "{}"
    data = json.loads(content)
    return data.get("verdict", "wrong")


async def run_cell(
    chunking: str,
    embedding: str,
    table: str,
    model_name: str,
    questions: list[dict],
    dsn: str,
    embedder_cache: dict[str, TextEmbedding],
    client: AsyncOpenAI,
    tracker: CostTracker,
    semaphore: asyncio.Semaphore,
) -> dict:
    async with semaphore:
        cell_label = f"{chunking}/{embedding}"
        logger.info("cell %s: starting %d questions", cell_label, len(questions))

        embedder = get_embedder(model_name, embedder_cache)

        # Use a separate sync connection per cell (psycopg3 sync is fine here
        # since embedding is the bottleneck, not DB round-trips)
        conn = psycopg.connect(dsn)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT COUNT(*), COUNT(DISTINCT doc_id) FROM factorial.{table}"
                )
                n_chunks, n_docs = cur.fetchone()

            per_question = []
            verdict_counts = {
                "fully_correct": 0,
                "partially_correct": 0,
                "wrong": 0,
                "hallucinated": 0,
            }

            for i, q in enumerate(questions, start=1):
                qid = q["id"]
                question_text = q["question"]
                gold_answer = q["gold_answer"]

                # 1. Embed
                vec_lit = embed_query(embedder, question_text)

                # 2. Vector search
                t_ret = time.perf_counter()
                chunks = vector_search(conn, table, vec_lit, limit=10)
                retrieval_ms = (time.perf_counter() - t_ret) * 1000

                # 3. Generate answer
                generated_answer, gen_ms = await generate_answer(
                    client, question_text, chunks, tracker
                )

                # 4. Judge
                t_judge = time.perf_counter()
                verdict = await judge_answer(
                    client, question_text, gold_answer, generated_answer, tracker
                )
                judge_ms = (time.perf_counter() - t_judge) * 1000

                # normalise verdict to known set
                if verdict not in verdict_counts:
                    logger.warning("Unexpected verdict '%s' for %s, treating as 'wrong'", verdict, qid)
                    verdict = "wrong"

                verdict_counts[verdict] += 1
                per_question.append({
                    "qid": qid,
                    "verdict": verdict,
                    "generated_answer": generated_answer,
                    "gold_answer": gold_answer,
                    "retrieved_chunk_ids": [c["id"] for c in chunks],
                    "retrieval_ms": round(retrieval_ms, 1),
                    "latency_gen_ms": round(gen_ms, 1),
                    "latency_judge_ms": round(judge_ms, 1),
                })

                print(
                    f"  [{cell_label}] {i:2d}/30  {qid}  → {verdict}  "
                    f"(running cost ${tracker.total_usd:.3f})",
                    flush=True,
                )

        finally:
            conn.close()

        logger.info(
            "cell %s done: fully=%d partial=%d wrong=%d halluc=%d",
            cell_label,
            verdict_counts["fully_correct"],
            verdict_counts["partially_correct"],
            verdict_counts["wrong"],
            verdict_counts["hallucinated"],
        )

        return {
            "chunking": chunking,
            "embedding": embedding,
            "table": table,
            "n_chunks": n_chunks,
            "n_docs": n_docs,
            "fully_correct": verdict_counts["fully_correct"],
            "partially_correct": verdict_counts["partially_correct"],
            "wrong": verdict_counts["wrong"],
            "hallucinated": verdict_counts["hallucinated"],
            "total": len(questions),
            "per_question": per_question,
        }


async def main() -> None:
    # Accept either the explicit env var or the .env fallback key
    dsn = os.environ.get("AGE_BAKEOFF_PGRG_DSN") or os.environ.get("PGRG_DSN")
    if not dsn:
        sys.exit("AGE_BAKEOFF_PGRG_DSN (or PGRG_DSN) not set")

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        sys.exit("OPENAI_API_KEY not set")

    root = Path(__file__).resolve().parent.parent
    questions = load_questions(root / "questions" / "scotus.yaml")
    out_dir = root / "results" / "diagnostics"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Estimate cost upfront
    # 12 cells × 30 questions × (1 gen + 1 judge) = 720 calls
    # avg ~800 prompt tokens gen, ~100 output; ~500 prompt tokens judge, ~50 output
    est_cost = 12 * 30 * (
        (800 * _IN_RATE + 100 * _OUT_RATE) +  # gen
        (500 * _IN_RATE + 50 * _OUT_RATE)     # judge
    )
    print(f"Estimated cost: ${est_cost:.2f} (hard cap ${HARD_BUDGET_USD:.2f})", flush=True)
    if est_cost > HARD_BUDGET_USD:
        sys.exit(f"ABORT: estimated cost ${est_cost:.2f} exceeds hard cap ${HARD_BUDGET_USD:.2f}")

    tracker = CostTracker(budget_usd=HARD_BUDGET_USD)
    client = AsyncOpenAI()

    # Embedder cache shared across cells (load each model once)
    # Note: TextEmbedding is not thread-safe but asyncio is single-threaded,
    # so sharing across async tasks is fine.
    embedder_cache: dict[str, TextEmbedding] = {}

    semaphore = asyncio.Semaphore(CELL_CONCURRENCY)

    t_wall = time.perf_counter()
    tasks = [
        run_cell(
            chunking, embedding, table, model_name,
            questions, dsn, embedder_cache, client, tracker, semaphore,
        )
        for chunking, embedding, table, model_name, _ in CELLS
    ]
    variants = await asyncio.gather(*tasks)
    wall_sec = time.perf_counter() - t_wall

    generated_at = time.strftime("%Y-%m-%dT%H:%M:%S")
    result = {
        "experiment": "factorial-accuracy",
        "corpus": "scotus",
        "precision": "fp32",
        "generated_at": generated_at,
        "model_gen": MODEL_GEN,
        "model_judge": MODEL_JUDGE,
        "wall_sec": round(wall_sec, 1),
        "cost_usd_total": round(tracker.total_usd, 4),
        "variants": list(variants),
    }

    json_path = out_dir / "factorial-accuracy-fp32.json"
    json_path.write_text(json.dumps(result, indent=2))
    print(f"\nWrote {json_path}", flush=True)

    # ── build markdown report ─────────────────────────────────────────────────
    baseline_fully_correct = 10  # pgrg hybrid mode scotus baseline
    baseline_label = "pgrg/hybrid/gpt-4.1-mini"

    # Sort by fully_correct desc, then partially_correct desc
    sorted_variants = sorted(
        variants,
        key=lambda v: (v["fully_correct"], v["partially_correct"]),
        reverse=True,
    )
    best = sorted_variants[0]

    lines: list[str] = []
    lines.append("# Factorial End-to-End Accuracy Report (fp32)\n")
    lines.append(f"Generated: {generated_at}  |  Model gen/judge: {MODEL_GEN}  |  Wall time: {wall_sec/60:.1f} min")
    lines.append(f"\nTotal cost: **${tracker.total_usd:.4f}**\n")

    lines.append("## TL;DR\n")
    best_label = f"{best['chunking']}/{best['embedding']}"
    best_fc = best["fully_correct"]
    delta = best_fc - baseline_fully_correct
    delta_str = f"+{delta}" if delta >= 0 else str(delta)
    lines.append(
        f"Best cell: **{best_label}** with **{best_fc}/30** fully_correct "
        f"({delta_str} vs {baseline_label} baseline of {baseline_fully_correct}/30)."
    )
    lines.append(
        f"\nBaseline ({baseline_label}): {baseline_fully_correct} fully_correct, "
        f"7 partially_correct, 13 wrong (hybrid retrieval, same scotus corpus).\n"
    )

    lines.append("## 12-cell results (sorted by fully_correct)\n")
    lines.append("| chunking | embedding | n_chunks | fully | partial | wrong | halluc | total |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for v in sorted_variants:
        lines.append(
            f"| {v['chunking']} | {v['embedding']} | {v['n_chunks']} "
            f"| {v['fully_correct']} | {v['partially_correct']} "
            f"| {v['wrong']} | {v['hallucinated']} | {v['total']} |"
        )

    lines.append("\n## Decision\n")
    # Adopt if best cell beats baseline by >=2 fully_correct
    if delta >= 2:
        decision = f"ADOPT_CELL={best['chunking']}/{best['embedding']}"
    elif delta >= 1:
        decision = f"MARGINAL_LIFT_CELL={best['chunking']}/{best['embedding']}"
    else:
        decision = "NO_LIFT_OVER_BASELINE"

    lines.append(
        f"Best cell {best_label}: {best_fc}/30 fully_correct  "
        f"(delta {delta_str} vs hybrid baseline {baseline_fully_correct}/30)"
    )
    lines.append(f"\n**DECISION: {decision}**\n")

    md_path = out_dir / "factorial-accuracy-fp32-REPORT.md"
    md_path.write_text("\n".join(lines) + "\n")
    print(f"Wrote {md_path}", flush=True)

    print(
        f"\n=== DONE ===  wall={wall_sec/60:.1f}m  cost=${tracker.total_usd:.4f}  "
        f"best={best_label} ({best_fc}/30 fully_correct)",
        flush=True,
    )


if __name__ == "__main__":
    asyncio.run(main())
