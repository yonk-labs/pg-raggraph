"""Run accuracy benchmarks across all ingested corpora.

For each corpus, runs a curated set of questions in all 4 query modes
and measures keyword recall (% of expected keywords in retrieved chunks).
"""

import asyncio
import csv
import io
import os
import time

from pg_raggraph import GraphRAG

with open("/home/yonk/yonk-tools/pg-agent/.openai") as f:
    os.environ["OPENAI_API_KEY"] = f.read().strip().split("=", 1)[1]

TEST_DSN = "postgresql://postgres:postgres@localhost:5434/pg_raggraph"
BENCH_DIR = os.path.dirname(os.path.abspath(__file__))


def extract_keywords(answer: str, max_kw: int = 8) -> list[str]:
    """Extract salient keywords (numbers, proper nouns) from a gold answer."""
    import re

    numbers = re.findall(r"\$[\d,]+(?:\.\d+)?|\d+(?:,\d{3})+(?:\.\d+)?|\d+\.\d+%?", answer)
    proper_nouns = re.findall(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*", answer)
    quoted = re.findall(r'"([^"]+)"', answer)

    seen = set()
    result = []
    for kw in numbers + proper_nouns + quoted:
        kw_lower = kw.lower()
        if kw_lower not in seen and len(kw) > 2:
            seen.add(kw_lower)
            result.append(kw_lower)
        if len(result) >= max_kw:
            break
    return result


def load_sec_questions() -> list[dict]:
    """Load SEC 10-Q gold questions."""
    path = os.path.join(BENCH_DIR, "kg-rag-eval", "sec-10-q", "data", "v1", "qna_data.csv")
    with open(path) as f:
        content = f.read().lstrip("\ufeff")
    reader = csv.DictReader(io.StringIO(content))
    rows = list(reader)
    for r in rows:
        r["expected_keywords"] = extract_keywords(r.get("Answer", ""))
    return rows


PG_QUESTIONS = [
    {
        "Question": "What are recursive CTEs used for in PostgreSQL?",
        "expected_keywords": ["recursive", "cte", "with", "hierarchy"],
    },
    {
        "Question": "How do you create a full-text search index?",
        "expected_keywords": ["gin", "tsvector", "to_tsvector", "index"],
    },
    {
        "Question": "What's the difference between HNSW and IVFFlat indexes?",
        "expected_keywords": ["hnsw", "ivfflat", "approximate", "nearest"],
    },
    {
        "Question": "How does PostgreSQL handle transactions and MVCC?",
        "expected_keywords": ["mvcc", "transaction", "snapshot", "isolation"],
    },
    {
        "Question": "What are the steps to back up a PostgreSQL database?",
        "expected_keywords": ["pg_dump", "backup", "wal", "archive"],
    },
    {
        "Question": "How do you partition a large table?",
        "expected_keywords": ["partition", "range", "list", "hash"],
    },
    {
        "Question": "How do I build a RAG application with PostgreSQL?",
        "expected_keywords": ["pgvector", "embedding", "vector", "similarity"],
    },
    {
        "Question": "What's the role of vacuuming in PostgreSQL?",
        "expected_keywords": ["vacuum", "dead", "bloat", "autovacuum"],
    },
    {
        "Question": "How do triggers interact with rules in PostgreSQL?",
        "expected_keywords": ["trigger", "rule", "row", "statement"],
    },
    {
        "Question": "What are the options for high availability?",
        "expected_keywords": ["replication", "streaming", "standby", "failover"],
    },
]

NTSB_QUESTIONS = [
    {
        "Question": "What common factors contributed to incidents in these reports?",
        "expected_keywords": ["pilot", "weather", "fuel", "engine"],
    },
    {
        "Question": "What types of aircraft were involved?",
        "expected_keywords": ["cessna", "beech", "piper", "single"],
    },
    {
        "Question": "How did pilot experience affect incident outcomes?",
        "expected_keywords": ["hours", "certificate", "student", "private"],
    },
    {
        "Question": "What FAA regulations were cited?",
        "expected_keywords": ["part 91", "cfr", "faa"],
    },
    {
        "Question": "What weather conditions were present during incidents?",
        "expected_keywords": ["wind", "visibility", "clouds", "weather"],
    },
]

SCOTUS_QUESTIONS = [
    {
        "Question": "Which cases involved Apple as a party?",
        "expected_keywords": ["apple", "antitrust", "pepper"],
    },
    {
        "Question": "What was the decision in cases about free speech?",
        "expected_keywords": ["first amendment", "speech", "free"],
    },
    {
        "Question": "Which justices dissented most often?",
        "expected_keywords": ["dissent", "thomas", "alito", "gorsuch"],
    },
    {
        "Question": "What antitrust cases were heard recently?",
        "expected_keywords": ["antitrust", "monopoly", "sherman"],
    },
    {
        "Question": "Which cases were decided 5-4?",
        "expected_keywords": ["5-4", "majority", "minority", "5", "4"],
    },
    {
        "Question": "What cases involved the Fourth Amendment?",
        "expected_keywords": ["fourth amendment", "search", "seizure"],
    },
    {
        "Question": "Which cases mentioned Chevron deference?",
        "expected_keywords": ["chevron", "deference", "agency"],
    },
    {
        "Question": "What cases involved the Environmental Protection Agency?",
        "expected_keywords": ["epa", "environmental", "clean"],
    },
]


async def benchmark_corpus(namespace: str, questions: list, max_q: int = None):
    """Run benchmark on one corpus."""
    if max_q:
        questions = questions[:max_q]

    rag = GraphRAG(
        dsn=TEST_DSN,
        namespace=namespace,
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4o-mini",
        llm_api_key=os.environ["OPENAI_API_KEY"],
        ingest_profile="balanced",
    )
    await rag.connect()

    modes = ["naive", "naive_boost", "smart", "local", "global", "hybrid"]
    results = {m: {"hits": 0, "total": 0, "latencies": []} for m in modes}

    for i, q in enumerate(questions, 1):
        expected = q.get("expected_keywords", [])
        if not expected:
            continue

        for mode in modes:
            try:
                r = await rag.query(q["Question"], mode=mode, namespace=namespace)
                content = " ".join(c.content.lower() for c in r.chunks)
                hits = sum(1 for k in expected if k.lower() in content)
                results[mode]["hits"] += hits
                results[mode]["total"] += len(expected)
                results[mode]["latencies"].append(r.latency_ms)
            except Exception as e:
                print(f"    Error in {mode}: {e}")

    await rag.close()

    summary = {}
    for mode in modes:
        r = results[mode]
        summary[mode] = {
            "accuracy": r["hits"] / r["total"] * 100 if r["total"] else 0,
            "avg_lat": sum(r["latencies"]) / len(r["latencies"]) if r["latencies"] else 0,
            "p95_lat": sorted(r["latencies"])[int(len(r["latencies"]) * 0.95)]
            if len(r["latencies"]) > 1
            else 0,
            "n": len(questions),
        }
    return summary


async def main():
    print("=" * 75)
    print("CROSS-CORPUS BENCHMARKS")
    print("=" * 75)

    # Load SEC questions from gold file
    sec_all = load_sec_questions()
    sec_q = [q for q in sec_all if "Multi-Doc" in q.get("Question Type", "")][:20]
    print(f"\nLoaded {len(sec_q)} SEC Multi-Doc questions")

    benchmarks = [
        ("PostgreSQL Docs", "bench_pg", PG_QUESTIONS),
        ("NTSB Aviation", "bench_ntsb", NTSB_QUESTIONS),
        ("SCOTUS (6 years)", "bench_scotus", SCOTUS_QUESTIONS),
        ("SEC 10-Q (Multi-Doc)", "bench_sec", sec_q),
    ]

    all_results = {}
    for label, ns, questions in benchmarks:
        print(f"\n{'-' * 75}")
        print(f"Benchmarking: {label} ({ns})")
        print(f"Questions: {len(questions)}")
        t0 = time.perf_counter()
        summary = await benchmark_corpus(ns, questions)
        elapsed = time.perf_counter() - t0
        all_results[label] = summary
        print(f"  Ran in {elapsed:.1f}s")

        for mode in ["naive", "naive_boost", "smart", "local", "global", "hybrid"]:
            s = summary[mode]
            print(
                f"  {mode:<13} acc={s['accuracy']:>5.1f}%  "
                f"avg={s['avg_lat']:>5.0f}ms  p95={s['p95_lat']:>5.0f}ms"
            )

    # Final comparison table
    print("\n" + "=" * 90)
    print("FINAL RESULTS — Accuracy by Mode (higher is better)")
    print("=" * 90)
    print()
    print(
        f"  {'Corpus':<22} {'N':>4} "
        f"{'naive':>9} {'boost':>9} {'smart':>9} "
        f"{'local':>9} {'global':>9} {'hybrid':>9}"
    )
    print("  " + "-" * 85)
    for label, s in all_results.items():
        n = s["naive"]["n"]
        row = f"  {label:<22} {n:>4}"
        for m in ["naive", "naive_boost", "smart", "local", "global", "hybrid"]:
            row += f"  {s[m]['accuracy']:>6.1f}%"
        print(row)

    print("\n  Latency by Mode (avg ms)")
    print(
        f"  {'Corpus':<22} {'naive':>9} {'boost':>9} {'smart':>9} "
        f"{'local':>9} {'global':>9} {'hybrid':>9}"
    )
    print("  " + "-" * 85)
    for label, s in all_results.items():
        row = f"  {label:<22}"
        for m in ["naive", "naive_boost", "smart", "local", "global", "hybrid"]:
            row += f"  {s[m]['avg_lat']:>6.0f}ms"
        print(row)

    # Save results
    import json

    results_path = os.path.join(BENCH_DIR, "cross_corpus_results.json")
    with open(results_path, "w") as f:
        json.dump(all_results, f, indent=2)
    print(f"\n  Saved: {results_path}")


if __name__ == "__main__":
    asyncio.run(main())
