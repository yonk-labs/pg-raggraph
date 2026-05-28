"""Bench C — A/B gate end-to-end smoke.

Drives the full #47→#48→#49→#50 chain on a tiny synthetic corpus to prove
the pipeline composes. The production `compute_verdict(runner_outputs)` path
still raises NotImplementedError (waiting for the LLM-judge wiring), so this
smoke computes the per-metric payload from the runner output and feeds it
through `compute_verdict.from_premeasured(...)` — the same code path the
unit tests use, exercised against real runner output instead of fixtures.

What this proves:
  - PR #47 (`resolve_entity_lookup`) is callable from PR #48's graph_leg.
  - PR #48's `run_harness_mode` produces `ABRunnerOutput` instances for both
    naive_vector and graph_leg modes against a real (synthetic) corpus.
  - PR #49's `run_ab_matrix` orchestrates `{corpora × modes}` and emits per-cell
    JSON + a manifest.
  - PR #50's `compute_verdict.from_premeasured` consumes a payload built from
    the runner output and produces an ABVerdict.
  - PR #50's `write_verdict_report` lands `verdict.json` + `verdict.md` +
    `latency.json`.

What this does NOT do:
  - Drive the production `compute_verdict(runner_outputs, judge_config)` path
    (currently NotImplementedError — that wires up when the LLM-judge call
    against actual chunkshop bakeoff corpora lands).
  - Run on chunkshop's bakeoff-scotus / bakeoff-ntsb corpora (needs chunkshop
    ingest + paid LLM key for a meaningful verdict signal).

Run:
  uv run python -m benchmarks.ab_gate_smoke
"""

from __future__ import annotations

import asyncio
import json
import tempfile
import time
from pathlib import Path

from pg_raggraph import GraphRAG
from pg_raggraph.ab_gate import (
    GoldQuestion,
    compute_verdict,
    run_ab_matrix,
    write_verdict_report,
)


DSN = "postgresql://postgres:postgres@localhost:5434/pg_raggraph"
NS = "bench_ab_smoke"


CORPUS = [
    {
        "text": "Bostock v. Clayton County established Title VII protections.",
        "source_id": "/repo/bench/bostock.md",
    },
    {
        "text": "Title VII forbids employment discrimination based on sex.",
        "source_id": "/repo/bench/title-vii.md",
    },
    {
        "text": "Clayton County argued that the statute did not apply.",
        "source_id": "/repo/bench/clayton-arg.md",
    },
    {
        "text": "The Supreme Court ruled 6-3 in favor of Bostock.",
        "source_id": "/repo/bench/scotus-ruling.md",
    },
]

GOLD = [
    GoldQuestion(
        id="q1",
        question="What protection did Bostock establish?",
        gold_answer="Title VII protections",
        required_facts=["Title VII"],
    ),
    GoldQuestion(
        id="q2",
        question="What did Clayton County argue?",
        gold_answer="The statute did not apply",
        required_facts=["statute"],
    ),
]


def _compute_metrics_from_cell(cell_path: Path, gold: list[GoldQuestion]) -> dict:
    """Compute recall@10 + MRR + fake judge tallies from a single cell's
    ABRunnerOutput JSON.

    This is what production compute_verdict() will eventually do per cell;
    inlining here lets the smoke drive from_premeasured() with real data.

    The "fake judge" assigns a 50/50 win to keep the smoke deterministic.
    Real wiring will replace this with llm-judge's evaluate_cases output.
    """
    data = json.loads(cell_path.read_text())
    results = data.get("results", [])

    recalls: list[int] = []
    rrs: list[float] = []

    for case, gq in zip(results, gold):
        retrieved = case.get("retrieved", [])
        gold_terms_lower = [
            t.lower()
            for t in ([gq.gold_answer] if gq.gold_answer else []) + (gq.required_facts or [])
        ]

        hit_rank = None
        for r in retrieved[:10]:
            snippet = (r.get("content_snippet") or "").lower()
            if any(t in snippet for t in gold_terms_lower if t):
                hit_rank = r.get("rank")
                break

        recalls.append(1 if hit_rank is not None else 0)
        rrs.append(1.0 / hit_rank if hit_rank else 0.0)

    n = max(len(gold), 1)
    recall_at_10 = sum(recalls) / n
    mrr = sum(rrs) / n
    return {
        "recall_at_10": recall_at_10,
        "mrr": mrr,
        "judge_wins": n // 2,  # synthetic 50/50
        "judge_total": n,
    }


def _build_premeasured_payload(cells: dict, gold: list[GoldQuestion]) -> dict:
    """Translate a (corpus, mode) -> Path map into the from_premeasured shape."""
    per_corpus: dict[str, dict[str, dict]] = {}
    for (corpus, mode), path in cells.items():
        metrics = _compute_metrics_from_cell(path, gold)
        per_corpus.setdefault(corpus, {})[mode] = metrics

    # Combined = single-corpus passthrough for this smoke
    only_corpus = next(iter(per_corpus))
    combined = {mode: dict(metrics) for mode, metrics in per_corpus[only_corpus].items()}

    return {"per_corpus": per_corpus, "combined": combined}


async def _ingest(rag: GraphRAG) -> None:
    """Use lede_spacy if available for symmetry with chunkshop ingest."""
    rag.config.fact_extractor = "lede_spacy"
    rag.config.llm_base_url = ""
    await rag.ingest_records(CORPUS, namespace=NS)


async def main() -> None:
    print("=== Bench C — A/B gate end-to-end smoke ===")
    print(f"  corpus: {len(CORPUS)} synthetic episodes")
    print(f"  gold:   {len(GOLD)} questions")
    print(f"  judge:  synthetic 50/50 (production wiring waits for llm-judge integration)")
    print()

    rag = GraphRAG(dsn=DSN, namespace=NS)
    await rag.connect()
    await rag.delete(NS)

    out_dir = Path(tempfile.mkdtemp(prefix="ab_smoke_"))
    print(f"  output: {out_dir}")
    print()

    try:
        # === Stage 1: ingest the synthetic corpus
        t0 = time.perf_counter()
        await _ingest(rag)
        t_ingest = time.perf_counter() - t0
        s = await rag.status(NS)
        print(f"[stage 1: ingest] {t_ingest:.2f}s — docs={s['documents']} "
              f"chunks={s['chunks']} ents={s['entities']} rels={s['relationships']}")

        # === Stage 2: run the A/B matrix
        t0 = time.perf_counter()
        cells = await run_ab_matrix(
            rag,
            corpora=[NS],
            modes=["naive_vector", "graph_leg"],
            gold_questions_per_corpus={NS: GOLD},
            output_dir=out_dir,
            top_k=5,
        )
        t_matrix = time.perf_counter() - t0
        print(f"[stage 2: A/B matrix] {t_matrix:.2f}s — {len(cells)} cells written")
        for (corpus, mode), path in cells.items():
            data = json.loads(path.read_text())
            n_results = len(data.get("results", []))
            avg_lat = (
                sum(r.get("latency_ms", 0) for r in data.get("results", [])) / max(n_results, 1)
            )
            print(f"  - {corpus} × {mode} → {path.name} ({n_results} results, "
                  f"{avg_lat:.1f}ms avg)")

        # === Stage 3: build premeasured payload from runner output
        t0 = time.perf_counter()
        payload = _build_premeasured_payload(cells, GOLD)
        verdict = compute_verdict.from_premeasured(payload)
        t_verdict = time.perf_counter() - t0
        print(f"[stage 3: verdict] {t_verdict:.2f}s — label={verdict.label}")
        print(f"  rationale (first line): {verdict.rationale.splitlines()[0]}")

        # === Stage 4: write the report
        # Extract per-case latency rows from the runner output for latency.json.
        latency_rows: list[dict] = []
        for (corpus, mode), path in cells.items():
            data = json.loads(path.read_text())
            for case in data.get("results", []):
                latency_rows.append({
                    "corpus": corpus,
                    "mode": mode,
                    "question_id": case.get("question_id"),
                    "latency_ms": case.get("latency_ms", 0),
                })
        write_verdict_report(verdict, out_dir=out_dir, latency_rows=latency_rows)
        artifacts = sorted(out_dir.glob("verdict*")) + sorted(out_dir.glob("latency*"))
        print(f"[stage 4: report]")
        for f in artifacts:
            print(f"  - {f.name} ({f.stat().st_size} bytes)")

        print()
        print("=== HEADLINE ===")
        total = t_ingest + t_matrix + t_verdict
        print(f"  Total wall: {total:.2f}s ({t_ingest:.2f} ingest + "
              f"{t_matrix:.2f} matrix + {t_verdict:.3f} verdict)")
        print(f"  Verdict: {verdict.label}")
        print(f"  Pipeline composed end-to-end via from_premeasured() seam.")
        print(f"  Output preserved at: {out_dir}")
    finally:
        await rag.delete(NS)
        await rag.close()


if __name__ == "__main__":
    asyncio.run(main())
