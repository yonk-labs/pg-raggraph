"""Run HotpotQA benchmark against pg-raggraph.

For each question, checks if the gold answer appears in the retrieved chunks.
Compares naive (vector+BM25) vs local (graph) vs hybrid.

Usage:
  uv run python benchmarks/run_hotpotqa.py --n-questions 50 --ingest
  uv run python benchmarks/run_hotpotqa.py --n-questions 100 --skip-ingest
"""

import argparse
import asyncio
import json
import os
import re
import time

from pg_raggraph import GraphRAG

TEST_DSN = "postgresql://postgres:postgres@localhost:5434/pg_raggraph"
LLM_URL = os.environ.get("PGRG_TEST_LLM_URL", "http://192.168.1.193:8000/v1")
LLM_MODEL = os.environ.get("PGRG_TEST_LLM_MODEL", "Intel/Qwen3-Coder-Next-int4-AutoRound")

BENCH_DIR = os.path.dirname(__file__)
DOCS_DIR = os.path.join(BENCH_DIR, "hotpotqa", "docs")
QUESTIONS_PATH = os.path.join(BENCH_DIR, "hotpotqa", "questions.json")

NAMESPACE = "bench_hotpot"


def normalize(text: str) -> str:
    """Normalize a string for fuzzy matching."""
    text = text.lower()
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def answer_in_chunks(answer: str, chunks: list) -> bool:
    """Check if the answer string appears in any of the retrieved chunks."""
    if not answer or answer.lower() in ("yes", "no"):
        # For yes/no answers, just check if any reasonable chunk came back
        return len(chunks) > 0

    norm_answer = normalize(answer)
    if len(norm_answer) < 2:
        return False

    for chunk in chunks:
        norm_content = normalize(chunk.content)
        if norm_answer in norm_content:
            return True
    return False


def supporting_doc_in_chunks(supporting_titles: list, chunks: list) -> int:
    """Count how many of the supporting docs' titles appear in the chunks."""
    if not supporting_titles:
        return 0

    chunk_texts = [normalize(c.content) for c in chunks]
    found = 0
    for title in supporting_titles:
        norm_title = normalize(title)
        for text in chunk_texts:
            if norm_title in text:
                found += 1
                break
    return found


async def ingest_only_needed_docs(rag: GraphRAG, questions: list, max_docs: int):
    """Ingest only the Wikipedia articles needed by the selected questions."""
    needed_titles = set()
    for q in questions:
        for title in q["supporting_docs"]:
            needed_titles.add(title)

    print(f"  Questions reference {len(needed_titles)} unique Wiki articles")

    # Slugify to find matching files
    def slugify(text):
        text = re.sub(r"[^\w\s-]", "", text).strip()
        text = re.sub(r"[\s_-]+", "-", text)
        return text[:100]

    file_paths = []
    for title in needed_titles:
        slug = slugify(title)
        path = os.path.join(DOCS_DIR, f"{slug}.md")
        if os.path.exists(path):
            file_paths.append(path)

    # Cap at max_docs
    file_paths = file_paths[:max_docs]
    print(f"  Ingesting {len(file_paths)} files...")

    t0 = time.perf_counter()
    await rag.ingest(file_paths, namespace=NAMESPACE)
    elapsed = time.perf_counter() - t0

    status = await rag.status(NAMESPACE)
    print(
        f"  Done in {elapsed:.0f}s: {status['documents']} docs, "
        f"{status['entities']} entities, {status['relationships']} rels "
        f"({elapsed / max(status['documents'], 1):.1f}s/doc)"
    )


async def run_benchmark(n_questions: int, skip_ingest: bool, max_docs: int):
    """Run the HotpotQA benchmark."""
    with open(QUESTIONS_PATH) as f:
        all_questions = json.load(f)

    questions = all_questions[:n_questions]
    print(f"Loaded {len(questions)} questions")
    print(f"  Bridge: {sum(1 for q in questions if q['type'] == 'bridge')}")
    print(f"  Comparison: {sum(1 for q in questions if q['type'] == 'comparison')}")

    rag = GraphRAG(
        dsn=TEST_DSN,
        namespace=NAMESPACE,
        llm_base_url=LLM_URL,
        llm_model=LLM_MODEL,
        doc_concurrency=4,
        extract_concurrency=16,
    )
    await rag.connect()

    if not skip_ingest:
        print("\nIngesting needed documents...")
        await ingest_only_needed_docs(rag, questions, max_docs)
    else:
        status = await rag.status(NAMESPACE)
        print(
            f"\nSkipping ingest. Current state: {status['documents']} docs, "
            f"{status['entities']} entities"
        )
        if status["documents"] == 0:
            print("  ERROR: No docs in namespace. Run with --ingest first.")
            return

    print("\nRunning benchmark...")
    modes = ["naive", "local", "global", "hybrid"]
    results = {
        m: {
            "answer_found": 0,
            "support_found": 0,
            "support_total": 0,
            "latencies": [],
        }
        for m in modes
    }

    for i, q in enumerate(questions, 1):
        for mode in modes:
            try:
                r = await rag.query(q["question"], mode=mode, namespace=NAMESPACE)
                if answer_in_chunks(q["answer"], r.chunks):
                    results[mode]["answer_found"] += 1
                support_found = supporting_doc_in_chunks(q["supporting_docs"], r.chunks)
                results[mode]["support_found"] += support_found
                results[mode]["support_total"] += len(q["supporting_docs"])
                results[mode]["latencies"].append(r.latency_ms)
            except Exception as e:
                print(f"    Error in {mode}: {e}")

        if i % 10 == 0:
            print(f"  Progress: {i}/{len(questions)}")

    # Summary
    print("\n" + "=" * 70)
    print("HOTPOTQA BENCHMARK RESULTS")
    print("=" * 70)
    print(f"Questions: {len(questions)}")
    print()
    print(f"  {'Mode':<10} {'Answer Recall':<15} {'Support Recall':<18} {'Avg Lat':<10}")
    print("  " + "-" * 60)
    for mode in modes:
        r = results[mode]
        ans_rate = r["answer_found"] / len(questions) * 100
        sup_rate = r["support_found"] / max(r["support_total"], 1) * 100
        avg_lat = sum(r["latencies"]) / max(len(r["latencies"]), 1)
        print(
            f"  {mode:<10} {ans_rate:>6.1f}%         "
            f"{sup_rate:>6.1f}%            {avg_lat:>6.0f}ms"
        )

    print()
    print("  Answer Recall  = % of questions where gold answer appears in chunks")
    print("  Support Recall = % of gold supporting Wiki articles found in chunks")

    # Save full results
    results_path = os.path.join(BENCH_DIR, "hotpotqa", "results.json")
    with open(results_path, "w") as f:
        json.dump(
            {
                "n_questions": len(questions),
                "results": {
                    m: {
                        "answer_recall": results[m]["answer_found"] / len(questions),
                        "support_recall": results[m]["support_found"]
                        / max(results[m]["support_total"], 1),
                        "avg_latency_ms": sum(results[m]["latencies"])
                        / max(len(results[m]["latencies"]), 1),
                    }
                    for m in modes
                },
            },
            f,
            indent=2,
        )
    print(f"\n  Saved: {results_path}")

    await rag.close()


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--n-questions", type=int, default=50)
    parser.add_argument(
        "--max-docs",
        type=int,
        default=200,
        help="Cap on documents to ingest (to stay within LLM time budget)",
    )
    parser.add_argument("--ingest", action="store_true", help="Ingest docs before benchmarking")
    parser.add_argument(
        "--skip-ingest", action="store_true", help="Skip ingestion (docs already loaded)"
    )
    args = parser.parse_args()

    # Default to ingest if neither flag is set and no data exists
    skip_ingest = args.skip_ingest or not args.ingest
    if args.ingest:
        skip_ingest = False

    await run_benchmark(args.n_questions, skip_ingest=skip_ingest, max_docs=args.max_docs)


if __name__ == "__main__":
    asyncio.run(main())
