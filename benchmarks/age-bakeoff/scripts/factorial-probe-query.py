#!/usr/bin/env python
"""Probe the 12 factorial.* tables with 4 scotus probes and produce the report.

Reads:
  - factorial.{a,b,c,d}_{bge_small,bge_base,nomic} tables (embedding, original_content)
  - benchmarks/age-bakeoff/questions/scotus.yaml (required_facts per probe)

For each (cell, probe):
  1. Embed the probe question with the cell's embedder model.
  2. SELECT id, original_content FROM factorial.{table}
        ORDER BY embedding <=> $1::vector LIMIT 50.
  3. Compute rank_of_first_gold_chunk, top10_hit, top50_hit,
     per_fact_recall_at_10, required_facts_matched, required_facts_missed
     via case-insensitive substring match of required_facts against original_content.

Writes:
  - results/diagnostics/factorial-probe.json
  - results/diagnostics/factorial-probe-REPORT.md (TL;DR + 12-row ranked table + DECISION line)
"""
from __future__ import annotations
import json
import os
import sys
import time
from pathlib import Path

import psycopg
import yaml
from fastembed import TextEmbedding

PROBES = ["scotus-q-018", "scotus-q-004", "scotus-q-008", "scotus-q-025"]
FAILING_PROBES = ["scotus-q-004", "scotus-q-008", "scotus-q-025"]

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


def load_probes(yaml_path: Path) -> dict:
    data = yaml.safe_load(yaml_path.read_text())
    by_id = {q["id"]: q for q in data["questions"]}
    return {qid: by_id[qid] for qid in PROBES}


def probe_cell(conn, table: str, probes: dict, embedder: TextEmbedding) -> dict:
    results = {}
    for qid, q in probes.items():
        qvec = list(embedder.embed([q["question"]]))[0].tolist()
        vec_lit = "[" + ",".join(f"{x:.6f}" for x in qvec) + "]"
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT id, original_content FROM factorial.{table} "
                "ORDER BY embedding <=> %s::vector LIMIT 50",
                (vec_lit,),
            )
            rows = cur.fetchall()
        facts = q["required_facts"]
        facts_lower = [f.lower() for f in facts]

        rank_first_gold = None
        top10_hit = False
        top50_hit = False
        matched = set()
        for i, (_, original) in enumerate(rows, start=1):
            ol = original.lower()
            for f, fl in zip(facts, facts_lower):
                if fl in ol:
                    if rank_first_gold is None:
                        rank_first_gold = i
                    if i <= 10:
                        matched.add(f)
                        top10_hit = True
                    if i <= 50:
                        top50_hit = True

        missed = [f for f in facts if f not in matched]
        per_fact_recall = len(matched) / len(facts) if facts else 0.0
        results[qid] = {
            "rank_of_first_gold_chunk": rank_first_gold,
            "top10_hit": top10_hit,
            "top50_hit": top50_hit,
            "per_fact_recall_at_10": round(per_fact_recall, 4),
            "required_facts_matched": sorted(matched),
            "required_facts_missed": sorted(missed),
        }
    return results


def main():
    root = Path(__file__).resolve().parent.parent
    probes_path = root / "questions" / "scotus.yaml"
    out_dir = root / "results" / "diagnostics"
    out_dir.mkdir(parents=True, exist_ok=True)

    dsn = os.environ["AGE_BAKEOFF_PGRG_DSN"]
    probes = load_probes(probes_path)

    # Cache embedders by model_name so we only load each once
    embedders: dict[str, TextEmbedding] = {}
    def get_embedder(model_name: str) -> TextEmbedding:
        if model_name not in embedders:
            print(f"[probe] loading embedder {model_name}", flush=True)
            embedders[model_name] = TextEmbedding(model_name=model_name)
        return embedders[model_name]

    out = {
        "experiment": "factorial-chunking-embedding",
        "corpus": "scotus",
        "probes": list(probes.keys()),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "variants": [],
    }

    with psycopg.connect(dsn) as conn:
        for chunking, embedding, table, model_name, dim in CELLS:
            print(f"[probe] cell {chunking}/{embedding} -> factorial.{table}", flush=True)
            emb = get_embedder(model_name)
            with conn.cursor() as cur:
                cur.execute(f"SELECT COUNT(*), COUNT(DISTINCT doc_id) FROM factorial.{table}")
                n_chunks, n_docs = cur.fetchone()
            per_probe = probe_cell(conn, table, probes, emb)
            out["variants"].append({
                "chunking": chunking,
                "embedding": embedding,
                "table": table,
                "n_chunks": n_chunks,
                "n_docs": n_docs,
                "embed_dim": dim,
                "per_probe": per_probe,
            })

    json_path = out_dir / "factorial-probe.json"
    json_path.write_text(json.dumps(out, indent=2))

    # Build report
    rows = []
    for v in out["variants"]:
        ranks = [v["per_probe"][p]["rank_of_first_gold_chunk"] for p in FAILING_PROBES]
        ranks_num = [r if r is not None else 10_000 for r in ranks]
        avg_rank = sum(ranks_num) / len(ranks_num)
        rows.append((avg_rank, v))
    rows.sort(key=lambda x: x[0])

    def _fmt(r):
        return "∞" if r is None else str(r)

    lines = []
    lines.append("# Factorial Chunking × Embedding Probe Report\n")
    lines.append(f"Generated: {out['generated_at']}\n")
    n_docs_first = out["variants"][0]["n_docs"] if out["variants"] else 0
    lines.append(f"Corpus: scotus ({n_docs_first} docs ingested)\n")
    lines.append("\n## 12-row table (sorted by avg rank of first gold across 3 failing probes)\n")
    lines.append("| chunking | embedding | n_chunks | avg_rank_failing | q-004 rank | q-008 rank | q-025 rank | q-018 rank (control) |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for avg_rank, v in rows:
        pp = v["per_probe"]
        lines.append(
            f"| {v['chunking']} | {v['embedding']} | {v['n_chunks']} | "
            f"{avg_rank:.1f} | "
            f"{_fmt(pp['scotus-q-004']['rank_of_first_gold_chunk'])} | "
            f"{_fmt(pp['scotus-q-008']['rank_of_first_gold_chunk'])} | "
            f"{_fmt(pp['scotus-q-025']['rank_of_first_gold_chunk'])} | "
            f"{_fmt(pp['scotus-q-018']['rank_of_first_gold_chunk'])} |"
        )

    # Decision: Adopt if any cell lifts required_facts_matched on the 3 failing probes by >=30% vs A/bge-small baseline
    baseline = next((v for v in out["variants"] if v["chunking"] == "A" and v["embedding"] == "bge-small"), None)
    lines.append("\n## Decision\n")
    if baseline is None:
        lines.append("Baseline A/bge-small not present in results. Cannot compute decision.\n")
        lines.append("DECISION: INSUFFICIENT_DATA\n")
    else:
        baseline_matched = sum(
            len(baseline["per_probe"][p]["required_facts_matched"]) for p in FAILING_PROBES
        )
        best_avg, best = rows[0]
        best_matched = sum(
            len(best["per_probe"][p]["required_facts_matched"]) for p in FAILING_PROBES
        )
        delta = best_matched - baseline_matched
        lines.append(
            f"Baseline (A/bge-small) required_facts_matched across failing probes: **{baseline_matched}**"
        )
        lines.append(
            f"Best cell ({best['chunking']}/{best['embedding']}) matched: **{best_matched}**  (delta={delta:+d})\n"
        )
        threshold_delta = max(2, int(0.3 * baseline_matched))
        if delta >= threshold_delta:
            decision = f"ADOPT_CELL={best['chunking']}/{best['embedding']}"
        else:
            decision = "NO_LIFT_NEXT=ENTITY_DRILL"
        lines.append(f"DECISION: {decision}\n")

    md_path = out_dir / "factorial-probe-REPORT.md"
    md_path.write_text("\n".join(lines))
    print(f"[probe] wrote {json_path} and {md_path}", flush=True)


if __name__ == "__main__":
    sys.exit(main() or 0)
