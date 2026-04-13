"""Run pg-raggraph benchmarks on real-world corpora.

Ingests:
1. SEC 10-Q filings (20 docs, 195 QnA pairs with gold answers)
2. NTSB aviation incident reports (20 docs)
3. PostgreSQL documentation + blogs (31 docs)

Compares naive (vector+BM25) vs local (graph) vs hybrid modes
across real questions with measurable accuracy.

Usage:
  uv run python benchmarks/run_benchmark.py --corpus sec-10q
  uv run python benchmarks/run_benchmark.py --corpus postgres
  uv run python benchmarks/run_benchmark.py --corpus all
"""

import argparse
import asyncio
import csv
import io
import os
import time

from pg_raggraph import GraphRAG

TEST_DSN = "postgresql://postgres:postgres@localhost:5434/pg_raggraph"
LLM_URL = os.environ.get("PGRG_TEST_LLM_URL", "http://192.168.1.193:8000/v1")
LLM_MODEL = os.environ.get("PGRG_TEST_LLM_MODEL", "Intel/Qwen3-Coder-Next-int4-AutoRound")

BENCH_DIR = os.path.dirname(__file__)
CORPORA = {
    "sec-10q": {
        "path": os.path.join(BENCH_DIR, "kg-rag-eval", "extracted", "sec-10q"),
        "namespace": "bench_sec",
        "qna_csv": os.path.join(
            BENCH_DIR, "kg-rag-eval", "sec-10-q", "data", "v1", "qna_data.csv"
        ),
    },
    "ntsb": {
        "path": os.path.join(BENCH_DIR, "kg-rag-eval", "extracted", "ntsb"),
        "namespace": "bench_ntsb",
        "qna_csv": None,
    },
    "postgres": {
        "path": os.path.join(BENCH_DIR, "postgres-docs"),
        "namespace": "bench_pg",
        "qna_csv": None,  # We'll define our own PG questions
    },
}


def load_sec_questions() -> list[dict]:
    """Load the SEC 10-Q QnA pairs."""
    csv_path = CORPORA["sec-10q"]["qna_csv"]
    with open(csv_path) as f:
        content = f.read().lstrip("\ufeff")
    reader = csv.DictReader(io.StringIO(content))
    return list(reader)


def extract_answer_keywords(answer: str, max_keywords: int = 8) -> list[str]:
    """Extract salient keywords from a gold answer.

    These become the 'expected in retrieval' set. A chunk is considered
    relevant if it contains multiple of these keywords.
    """
    import re

    # Find numbers (very important in financial docs)
    numbers = re.findall(r"\$[\d,]+(?:\.\d+)?|\d+(?:,\d{3})+(?:\.\d+)?|\d+\.\d+%?", answer)

    # Find capitalized multi-word terms (company names, products)
    proper_nouns = re.findall(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*", answer)

    # Find quoted strings
    quoted = re.findall(r'"([^"]+)"', answer)

    # Combine and dedupe (case-insensitive)
    all_kw = numbers + proper_nouns + quoted
    seen = set()
    result = []
    for kw in all_kw:
        kw_lower = kw.lower()
        if kw_lower not in seen and len(kw) > 2:
            seen.add(kw_lower)
            result.append(kw_lower)
        if len(result) >= max_keywords:
            break
    return result


# Hand-picked PostgreSQL questions to test
POSTGRES_QUESTIONS = [
    {
        "Question": "What are recursive CTEs used for in PostgreSQL?",
        "Question Type": "Single-Doc Single-Chunk RAG",
        "expected_keywords": ["recursive", "cte", "with", "hierarchy", "tree"],
    },
    {
        "Question": "How do you create a full-text search index in PostgreSQL?",
        "Question Type": "Single-Doc Multi-Chunk RAG",
        "expected_keywords": ["gin", "tsvector", "to_tsvector", "index", "text search"],
    },
    {
        "Question": "What's the difference between HNSW and IVFFlat indexes in pgvector?",
        "Question Type": "Multi-Doc RAG",
        "expected_keywords": ["hnsw", "ivfflat", "pgvector", "approximate", "nearest"],
    },
    {
        "Question": "How does PostgreSQL handle transactions and MVCC?",
        "Question Type": "Multi-Doc RAG",
        "expected_keywords": ["mvcc", "transaction", "snapshot", "isolation", "rollback"],
    },
    {
        "Question": "What are the steps to back up a PostgreSQL database?",
        "Question Type": "Single-Doc Multi-Chunk RAG",
        "expected_keywords": ["pg_dump", "pg_basebackup", "backup", "wal", "archive"],
    },
    {
        "Question": "How do you partition a large table in PostgreSQL?",
        "Question Type": "Single-Doc Multi-Chunk RAG",
        "expected_keywords": ["partition", "range", "list", "hash", "partitioned"],
    },
    {
        "Question": "How do I build a RAG application with PostgreSQL and pgvector?",
        "Question Type": "Multi-Doc RAG",
        "expected_keywords": ["pgvector", "embedding", "vector", "similarity", "rag"],
    },
    {
        "Question": "What's the role of vacuuming in PostgreSQL?",
        "Question Type": "Single-Doc Single-Chunk RAG",
        "expected_keywords": ["vacuum", "dead tuples", "bloat", "autovacuum", "analyze"],
    },
    {
        "Question": "How do triggers interact with rules in PostgreSQL?",
        "Question Type": "Multi-Doc RAG",
        "expected_keywords": ["trigger", "rule", "row", "statement", "before", "after"],
    },
    {
        "Question": "What are the options for high availability in PostgreSQL?",
        "Question Type": "Multi-Doc RAG",
        "expected_keywords": ["replication", "streaming", "standby", "failover", "wal"],
    },
]


async def ingest_corpus(corpus_key: str) -> dict:
    """Ingest a corpus and return stats."""
    corpus = CORPORA[corpus_key]
    rag = GraphRAG(
        dsn=TEST_DSN,
        namespace=corpus["namespace"],
        llm_base_url=LLM_URL,
        llm_model=LLM_MODEL,
    )
    await rag.connect()

    # Check if already ingested
    existing = await rag.status(corpus["namespace"])
    if existing["documents"] > 0:
        print(
            f"  Already ingested: {existing['documents']} docs, "
            f"{existing['entities']} entities, {existing['relationships']} rels"
        )
        await rag.close()
        return existing

    print(f"  Ingesting from {corpus['path']}...")
    t0 = time.perf_counter()
    await rag.ingest([corpus["path"]], namespace=corpus["namespace"])
    elapsed = time.perf_counter() - t0

    status = await rag.status(corpus["namespace"])
    status["ingest_seconds"] = elapsed
    print(
        f"  Done in {elapsed:.1f}s: {status['documents']} docs, "
        f"{status['chunks']} chunks, {status['entities']} entities, "
        f"{status['relationships']} relationships"
    )

    await rag.close()
    return status


async def run_benchmark(corpus_key: str, num_questions: int | None = None) -> dict:
    """Run benchmark questions against a corpus in all modes."""
    corpus = CORPORA[corpus_key]
    rag = GraphRAG(
        dsn=TEST_DSN,
        namespace=corpus["namespace"],
        llm_base_url=LLM_URL,
        llm_model=LLM_MODEL,
    )
    await rag.connect()

    # Load questions
    if corpus_key == "sec-10q":
        questions = load_sec_questions()
        # Add keyword extraction for scoring
        for q in questions:
            q["expected_keywords"] = extract_answer_keywords(q.get("Answer", ""))
    elif corpus_key == "postgres":
        questions = POSTGRES_QUESTIONS
    else:
        print(f"  No questions defined for {corpus_key}")
        await rag.close()
        return {}

    if num_questions:
        questions = questions[:num_questions]

    print(f"\n  Running {len(questions)} questions...")

    modes = ["naive", "local", "global", "hybrid"]
    results = {m: {"scores": [], "latencies": [], "chunks_found": []} for m in modes}

    for i, q in enumerate(questions, 1):
        question_text = q["Question"]
        expected = q["expected_keywords"]
        if not expected:
            continue

        for mode in modes:
            try:
                r = await rag.query(question_text, mode=mode, namespace=corpus["namespace"])
                content = " ".join(c.content.lower() for c in r.chunks)
                score = sum(1 for k in expected if k.lower() in content)
                results[mode]["scores"].append(score / len(expected) if expected else 0)
                results[mode]["latencies"].append(r.latency_ms)
                results[mode]["chunks_found"].append(len(r.chunks))
            except Exception as e:
                print(f"    Error in {mode}: {e}")
                results[mode]["scores"].append(0)
                results[mode]["latencies"].append(0)
                results[mode]["chunks_found"].append(0)

        if i % 10 == 0:
            print(f"    Progress: {i}/{len(questions)}")

    await rag.close()

    # Summarize
    summary = {}
    for mode in modes:
        scores = results[mode]["scores"]
        lats = results[mode]["latencies"]
        if scores:
            summary[mode] = {
                "avg_accuracy": sum(scores) / len(scores) * 100,
                "avg_latency": sum(lats) / len(lats),
                "max_latency": max(lats),
                "n_questions": len(scores),
            }

    return summary


def print_summary(corpus_key: str, summary: dict):
    """Print a human-readable summary."""
    print("\n  ╔══════════════════════════════════════════════════════════╗")
    print(f"  ║ Corpus: {corpus_key:<50} ║")
    print("  ╠══════════════════════════════════════════════════════════╣")
    print("  ║ Mode       Accuracy    Avg Lat     Max Lat    N      ║")
    print("  ╠══════════════════════════════════════════════════════════╣")
    for mode in ["naive", "local", "global", "hybrid"]:
        if mode in summary:
            s = summary[mode]
            print(
                f"  ║ {mode:<10} {s['avg_accuracy']:>6.1f}%    "
                f"{s['avg_latency']:>6.0f}ms    "
                f"{s['max_latency']:>6.0f}ms   "
                f"{s['n_questions']:>3}   ║"
            )
    print("  ╚══════════════════════════════════════════════════════════╝")


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", default="all", choices=["sec-10q", "ntsb", "postgres", "all"])
    parser.add_argument("--ingest-only", action="store_true")
    parser.add_argument("--skip-ingest", action="store_true")
    parser.add_argument("-n", type=int, default=None, help="Number of questions (for testing)")
    args = parser.parse_args()

    corpora_to_run = ["sec-10q", "ntsb", "postgres"] if args.corpus == "all" else [args.corpus]

    # Ingest phase
    if not args.skip_ingest:
        print("=" * 62)
        print(" INGESTION PHASE")
        print("=" * 62)
        for c in corpora_to_run:
            print(f"\nCorpus: {c}")
            await ingest_corpus(c)

    if args.ingest_only:
        return

    # Benchmark phase
    print("\n" + "=" * 62)
    print(" BENCHMARK PHASE")
    print("=" * 62)

    all_summaries = {}
    for c in corpora_to_run:
        if c == "ntsb":
            continue  # No questions defined
        print(f"\nCorpus: {c}")
        summary = await run_benchmark(c, num_questions=args.n)
        all_summaries[c] = summary
        print_summary(c, summary)

    # Final comparison
    print("\n" + "=" * 62)
    print(" FINAL RESULTS — Accuracy by Mode (higher is better)")
    print("=" * 62)
    print(f"\n  {'Corpus':<15} {'naive':>8} {'local':>8} {'global':>8} {'hybrid':>8}")
    print("  " + "-" * 52)
    for c, s in all_summaries.items():
        row = f"  {c:<15}"
        for m in ["naive", "local", "global", "hybrid"]:
            if m in s:
                row += f" {s[m]['avg_accuracy']:>7.1f}%"
            else:
                row += f" {'--':>8}"
        print(row)

    print("\n  (Accuracy = % of expected keywords found in retrieved chunks)")


if __name__ == "__main__":
    asyncio.run(main())
