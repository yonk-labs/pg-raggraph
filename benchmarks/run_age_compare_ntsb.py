"""pgrg vs Apache AGE on NTSB — apples-to-apples engine comparison.

Methodology (mirrors `benchmarks/age-bakeoff/`):
  1. Both engines see the SAME extraction (chunks + entities + relationships).
     We pull pgrg's already-ingested `bench_ntsb` extraction from the standard
     pg_raggraph DB and replay it into AGE's bake-off container DB. The point
     of variance is storage + retrieval engine, not extraction quality.
  2. Same 10 questions from `run_llm_judge.py:NTSB_QUESTIONS`.
  3. Both engines retrieve top-5 chunks for each question.
  4. Both ground an answer using the local vLLM (the answer-generator
     pgrg's `rag.ask()` already uses).
  5. The same answers are judged 0–3 by Qwen and OpenAI gpt-4o-mini.
  6. Output: side-by-side JSON + console table with both engines + both judges.

Why a separate script instead of extending the bake-off harness:
  * The harness consumes pre-built `extraction/data/*.json` and runs its own
    extraction pipeline. NTSB doesn't have one yet, and we already have the
    extraction on pgrg's side. Replaying that into AGE is the elegant shortcut.
  * Output schema stays compact for the cross-engine comparison the user asked
    for; the rigorous bake-off-style ntsb integration (questions/ntsb.yaml +
    extraction/data/ntsb.json + loader wiring) is its own follow-up.

Usage:
  uv run python benchmarks/run_age_compare_ntsb.py [--judge local|openai|both]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx

from pg_raggraph import GraphRAG

sys.path.insert(0, str(Path(__file__).parent / "age-bakeoff" / "src"))
from age_bakeoff.engines.age import AgeEngine  # noqa: E402
from age_bakeoff.models import (  # noqa: E402
    Chunk,
    ExtractedEntity,
    ExtractedRelationship,
    ExtractionOutput,
)

# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

PGRG_DSN = os.environ.get("PGRG_DSN", "postgresql://postgres:postgres@localhost:5434/pg_raggraph")
# AGE bake-off DB (separate Postgres container with shared_preload_libraries='age')
AGE_DSN = os.environ.get(
    "AGE_BAKEOFF_DSN", "postgresql://postgres:postgres@localhost:5435/age_bakeoff_age"
)

ANSWER_URL = os.environ.get("PGRG_TEST_LLM_URL", "http://192.168.1.193:8000/v1")
ANSWER_MODEL = os.environ.get("PGRG_TEST_LLM_MODEL", "Intel/Qwen3-Coder-Next-int4-AutoRound")

NAMESPACE = "bench_ntsb"

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
# Pull pgrg's bench_ntsb extraction → bake-off ExtractionOutput
# ---------------------------------------------------------------------------


async def export_pgrg_extraction() -> ExtractionOutput:
    rag = GraphRAG(dsn=PGRG_DSN, namespace=NAMESPACE)
    await rag.connect()
    try:
        # Chunks: id, document_id, content, sequence (use chunks.id as sequence proxy)
        chunk_rows = await rag.db.fetch_all(
            "SELECT c.id AS cid, d.source_path AS doc, c.content "
            "FROM chunks c JOIN documents d ON c.document_id = d.id "
            "WHERE d.namespace = %s ORDER BY c.id",
            (NAMESPACE,),
        )
        # Sequence per (document_id) for the bake-off Chunk model.
        per_doc_seq: dict[str, int] = {}
        chunks: list[Chunk] = []
        for r in chunk_rows:
            doc = r["doc"] or f"doc_{r['cid']}"
            seq = per_doc_seq.get(doc, 0)
            per_doc_seq[doc] = seq + 1
            chunks.append(
                Chunk(
                    id=str(r["cid"]),
                    document_id=str(doc),
                    content=r["content"],
                    sequence=seq,
                )
            )

        # Entities: id, name, entity_type, description
        entity_rows = await rag.db.fetch_all(
            "SELECT id, name, entity_type, description FROM entities "
            "WHERE namespace = %s ORDER BY id",
            (NAMESPACE,),
        )
        entities = [
            ExtractedEntity(
                id=str(r["id"]),
                name=r["name"],
                entity_type=r["entity_type"] or "unknown",
                description=r["description"] or "",
            )
            for r in entity_rows
        ]

        # Relationships: src_id, dst_id, rel_type, weight, description
        rel_rows = await rag.db.fetch_all(
            "SELECT src_id, dst_id, rel_type, weight, description "
            "FROM relationships WHERE namespace = %s ORDER BY id",
            (NAMESPACE,),
        )
        relationships = [
            ExtractedRelationship(
                src_id=str(r["src_id"]),
                dst_id=str(r["dst_id"]),
                rel_type=r["rel_type"] or "RELATED_TO",
                weight=float(r["weight"] or 1.0),
                description=r["description"] or "",
            )
            for r in rel_rows
        ]
    finally:
        await rag.close()

    return ExtractionOutput(
        corpus=NAMESPACE,
        chunks=chunks,
        entities=entities,
        relationships=relationships,
    )


# ---------------------------------------------------------------------------
# Local vLLM answerer (used for BOTH engines so the answer LLM is constant)
# ---------------------------------------------------------------------------


async def vllm_answer(
    client: httpx.AsyncClient, question: str, retrieved_contents: list[str]
) -> str:
    context = "\n\n---\n\n".join(c[:1500] for c in retrieved_contents[:5])
    resp = await client.post(
        f"{ANSWER_URL}/chat/completions",
        json={
            "model": ANSWER_MODEL,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You answer questions strictly from the provided "
                        "context chunks. If the context doesn't contain the "
                        "answer, say so. Be concise."
                    ),
                },
                {
                    "role": "user",
                    "content": f"CONTEXT:\n{context}\n\nQUESTION: {question}\n\nANSWER:",
                },
            ],
            "temperature": 0.0,
        },
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


# ---------------------------------------------------------------------------
# Judge (mirrors run_llm_judge.py)
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


async def judge_score(
    client: httpx.AsyncClient,
    judge_url: str,
    judge_model: str,
    judge_api_key: str,
    question: str,
    answer: str,
    chunks: list[str],
) -> tuple[int, str]:
    user_content = (
        f"QUESTION:\n{question}\n\nSYSTEM ANSWER:\n{answer}\n\n"
        f"RETRIEVED CHUNKS:\n" + "\n\n---\n\n".join(c[:600] for c in chunks)
    )
    headers = {"Content-Type": "application/json"}
    if judge_api_key:
        headers["Authorization"] = f"Bearer {judge_api_key}"
    resp = await client.post(
        f"{judge_url}/chat/completions",
        headers=headers,
        json={
            "model": judge_model,
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
        score = max(0, min(3, int(data.get("score", 0))))
        rationale = data.get("rationale", "")[:300]
    except (json.JSONDecodeError, ValueError, TypeError):
        score = 0
        rationale = f"unparseable: {raw[:200]}"
    return score, rationale


# ---------------------------------------------------------------------------
# Engines
# ---------------------------------------------------------------------------


async def query_pgrg(rag: GraphRAG, question: str, mode: str) -> tuple[list[str], float]:
    """Return (top-5 chunk contents, retrieval latency ms) from pgrg."""
    t0 = time.perf_counter()
    result = await rag.query(question, mode=mode, namespace=NAMESPACE)
    contents = [c.content for c in result.chunks[:5]]
    return contents, (time.perf_counter() - t0) * 1000


async def query_age(age: AgeEngine, question: str) -> tuple[list[str], float]:
    """Return (top-5 chunk contents, retrieval latency ms) from AGE."""
    t0 = time.perf_counter()
    response = await age.retrieve(question)
    contents = list(response.retrieved_chunk_contents[:5])
    return contents, (time.perf_counter() - t0) * 1000


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--judge",
        default="both",
        choices=["local", "openai", "both"],
        help="Which judge(s) to run.",
    )
    args = ap.parse_args()

    judges: list[tuple[str, str, str, str]] = []  # (label, url, model, api_key)
    if args.judge in ("local", "both"):
        judges.append(("qwen", ANSWER_URL, ANSWER_MODEL, ""))
    if args.judge in ("openai", "both"):
        key = os.environ.get("OPENAI_API_KEY", "").strip()
        if not key:
            print("ERROR: --judge openai|both requires OPENAI_API_KEY", file=sys.stderr)
            sys.exit(2)
        judges.append(
            (
                "openai",
                os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
                os.environ.get("OPENAI_JUDGE_MODEL", "gpt-4o-mini"),
                key,
            )
        )

    print("Pulling extraction from pgrg `bench_ntsb`…")
    extraction = await export_pgrg_extraction()
    print(
        f"  chunks={len(extraction.chunks)} entities={len(extraction.entities)} "
        f"relationships={len(extraction.relationships)}"
    )

    print("Bootstrapping + ingesting AGE…")
    age = AgeEngine(
        dsn=AGE_DSN,
        graph_name="bench_ntsb",
        namespace=NAMESPACE,
        retrieval_mode="hybrid",
        embedding_model="BAAI/bge-small-en-v1.5",
    )
    await age.cleanup()  # clean slate
    t0 = time.perf_counter()
    await age.ingest(extraction)
    print(f"  AGE ingest: {time.perf_counter() - t0:.1f}s")

    print("Wiring pgrg…")
    rag = GraphRAG(
        dsn=PGRG_DSN,
        namespace=NAMESPACE,
        llm_base_url=ANSWER_URL,
        llm_model=ANSWER_MODEL,
    )
    await rag.connect()

    # Answer + judge for each (question, engine, mode)
    rows: list[dict] = []
    pgrg_modes = ["naive", "naive_boost", "smart", "local", "global", "hybrid"]
    async with httpx.AsyncClient() as client:
        for qi, question in enumerate(NTSB_QUESTIONS, 1):
            print(f"  Q{qi}/{len(NTSB_QUESTIONS)}: {question[:60]}…")

            # AGE — single hybrid retrieval (the AGE engine doesn't expose
            # the same 6-mode menu pgrg does; its native mode is hybrid.
            # Comparison is "AGE hybrid" vs each pgrg mode).
            age_chunks, age_lat = await query_age(age, question)
            age_answer = await vllm_answer(client, question, age_chunks)

            # pgrg — all 6 modes
            pgrg_per_mode: dict[str, dict] = {}
            for mode in pgrg_modes:
                p_chunks, p_lat = await query_pgrg(rag, question, mode)
                p_ans = await vllm_answer(client, question, p_chunks)
                pgrg_per_mode[mode] = {
                    "answer": p_ans,
                    "chunks": p_chunks,
                    "retrieval_ms": p_lat,
                }

            for j_label, j_url, j_model, j_key in judges:
                # AGE
                age_score, age_rat = await judge_score(
                    client, j_url, j_model, j_key, question, age_answer, age_chunks
                )
                rows.append(
                    {
                        "question": question,
                        "engine": "age",
                        "mode": "hybrid",
                        "judge": j_label,
                        "score": age_score,
                        "rationale": age_rat,
                        "retrieval_ms": age_lat,
                        "answer": age_answer[:500],
                    }
                )
                # pgrg per mode
                for mode in pgrg_modes:
                    p = pgrg_per_mode[mode]
                    s, r = await judge_score(
                        client, j_url, j_model, j_key, question, p["answer"], p["chunks"]
                    )
                    rows.append(
                        {
                            "question": question,
                            "engine": "pgrg",
                            "mode": mode,
                            "judge": j_label,
                            "score": s,
                            "rationale": r,
                            "retrieval_ms": p["retrieval_ms"],
                            "answer": p["answer"][:500],
                        }
                    )

    await rag.close()

    # ---- Aggregate ------------------------------------------------------
    judge_labels = [j[0] for j in judges]
    cells = sorted({(r["engine"], r["mode"], r["judge"]) for r in rows})
    summary: dict = {"by_cell": {}}
    for engine, mode, judge in cells:
        cell_rows = [
            r for r in rows if r["engine"] == engine and r["mode"] == mode and r["judge"] == judge
        ]
        scores = [r["score"] for r in cell_rows]
        lats = [r["retrieval_ms"] for r in cell_rows]
        summary["by_cell"][f"{engine}/{mode}/{judge}"] = {
            "avg_score_0_3": round(sum(scores) / max(len(scores), 1), 2),
            "accuracy_pct": round(sum(scores) / max(len(scores) * 3, 1) * 100, 1),
            "fully_correct": sum(1 for s in scores if s == 3),
            "wrong_or_empty": sum(1 for s in scores if s == 0),
            "avg_retrieval_ms": round(sum(lats) / max(len(lats), 1), 1) if lats else 0,
            "n": len(scores),
        }

    # ---- Print comparison ---------------------------------------------
    print("\n" + "=" * 78)
    print(
        "NTSB — pgrg vs Apache AGE  (n=10 questions, same extraction, "
        "answer LLM = local vLLM Qwen3-Coder)"
    )
    print("=" * 78)
    for jlabel in judge_labels:
        print(f"\n  Judge: {jlabel}")
        print(
            f"  {'Engine/Mode':<22} {'Score (0-3)':>12} {'Acc %':>8} "
            f"{'Fully':>6} {'Wrong':>6} {'Retr ms':>9}"
        )
        print("  " + "-" * 70)
        order = [
            ("pgrg", "naive"),
            ("pgrg", "naive_boost"),
            ("pgrg", "smart"),
            ("pgrg", "local"),
            ("pgrg", "global"),
            ("pgrg", "hybrid"),
            ("age", "hybrid"),
        ]
        for engine, mode in order:
            key = f"{engine}/{mode}/{jlabel}"
            s = summary["by_cell"].get(key)
            if not s:
                continue
            label = f"{engine}/{mode}"
            print(
                f"  {label:<22} {s['avg_score_0_3']:>12} "
                f"{s['accuracy_pct']:>7}% {s['fully_correct']:>6} "
                f"{s['wrong_or_empty']:>6} {s['avg_retrieval_ms']:>9}"
            )

    # ---- Persist -------------------------------------------------------
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    bench_dir = Path(__file__).parent
    out = bench_dir / f"age-compare-ntsb-{ts}.json"
    out.write_text(
        json.dumps(
            {
                "generated_at": datetime.now().isoformat(),
                "corpus": "ntsb",
                "n_questions": len(NTSB_QUESTIONS),
                "answer_generator": {"url": ANSWER_URL, "model": ANSWER_MODEL},
                "judges": [
                    {"label": label, "url": url, "model": model} for label, url, model, _ in judges
                ],
                "summary": summary,
                "rows": rows,
            },
            indent=2,
            default=str,
        )
    )
    print(f"\n  Wrote {out}")


if __name__ == "__main__":
    asyncio.run(main())
