#!/usr/bin/env python3
"""Prepare the HorizonDB h2h corpus from Microsoft's accelerator repo.

Reads data/cases_final.csv from a local clone of
https://github.com/Azure-Samples/graphrag-legalcases-postgres (MIT) and writes:

  data/corpus.jsonl          one line per case: id, name, name_abbreviation,
                             court_id, decision_date, text, cites_in_corpus
  data/gold.json             the demo question + Microsoft's gold_dataset labels
  data/age_embeddings.jsonl  one fastembed bge-small-en-v1.5 embedding per case
                             (input text identical to Microsoft's embedding
                             input shape: name || LEFT(opinion_0, 8000))
  data/manifest.json         counts + sha256 of inputs for reproducibility

The corpus is the ENTIRE 410-case demo dataset Microsoft ships in-repo —
no slicing performed, so there is no slice-selection bias to defend.
(The "500K cases" figure in the HorizonDB doc refers to the full Caselaw
Access Project US Case Law dataset; the accelerator repo ships this 410-case
Washington-state sample, and its gold labels are defined against it.)

Usage:
    uv run --no-sync python benchmarks/age-bakeoff/horizondb-h2h/prepare_corpus.py \
        --accelerator-repo /path/to/graphrag-legalcases-postgres
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"

# Microsoft's gold_dataset, verbatim from
# src/backend/fastapi_app/setup_postgres_legal_seeddata.py (initialize_gold_dataset).
GOLD_LABELS: dict[str, str] = {
    "782330": "orig-vector",
    "615468": "gold-graph",
    "1095193": "gold-graph",
    "1034620": "gold-graph",
    "772283": "gold",
    "1186056": "gold-graph",
    "1127907": "gold-graph",
    "591482": "gold",
    "594079": "gold-graph",
    "561149": "gold",
    "1086651": "orig",
    "2601920": "gold-graph",
    "552773": "gold",
    "1346648": "orig-semantic",
    "4912975": "gold",
    "999494": "gold",
    "1005731": "gold-semantic",
    "828223": "gold",
    "4920250": "gold",
    "4933418": "gold",
    "798646": "gold",
    "768356": "gold-semantic",
    "1017660": "gold-vector",
    "4953587": "maybe-graph",
    "630224": "maybe-semantic",
    "481657": "maybe-semantic",
    "634444": "no",
    "4975399": "no",
    "1279441": "no",
    "1091260": "no",
    "821843": "no",
    "674990": "no",
    "5041745": "no",
    "4938756": "no",
    "473788": "gold-graph-appeals",
    "3977147": "no",
    "1352760": "no",
    "5752736": "no",
}

# The only question the accelerator defines gold labels for (their demo query,
# used verbatim across playground/, demo/ and sample_qa_data/).
GOLD_QUESTION = "Water leaking into the apartment from the floor above."

STRICT_PREFIXES = ("gold",)  # gold, gold-graph, gold-semantic, gold-vector, gold-graph-appeals
PLUS_PREFIXES = ("gold", "orig", "maybe")

EMBED_CHAR_LIMIT = 8000  # Microsoft: name || LEFT(opinion, 8000)


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--accelerator-repo",
        required=True,
        help="Path to a clone of Azure-Samples/graphrag-legalcases-postgres",
    )
    args = ap.parse_args()

    csv_path = Path(args.accelerator_repo) / "data" / "cases_final.csv"
    if not csv_path.exists():
        sys.exit(f"not found: {csv_path} — clone the accelerator repo first")

    DATA.mkdir(exist_ok=True)
    csv.field_size_limit(sys.maxsize)

    cases: dict[str, dict] = {}
    with open(csv_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            d = json.loads(row["data"])
            opinion = ""
            opinions = (d.get("casebody") or {}).get("opinions") or []
            if opinions:
                opinion = opinions[0].get("text") or ""
            cited: list[str] = []
            for ct in d.get("cites_to") or []:
                cited.extend(str(cid) for cid in ct.get("case_ids") or [])
            cases[row["id"]] = {
                "id": row["id"],
                "name": d.get("name") or "",
                "name_abbreviation": d.get("name_abbreviation") or "",
                "court_id": (d.get("court") or {}).get("id"),
                "decision_date": d.get("decision_date") or "",
                # Identical raw text for BOTH arms: Microsoft's embedding input
                # shape (name || first 8000 chars of the lead opinion).
                "text": (d.get("name") or "") + (opinion[:EMBED_CHAR_LIMIT]),
                "cites_raw": cited,
            }

    ids = set(cases)
    # Keep only in-corpus citation edges — mirrors the accelerator's
    # create_edges_from_citations, which JOINs cites_to against cases_updated.
    n_edges = 0
    for c in cases.values():
        in_corpus = sorted({cid for cid in c.pop("cites_raw") if cid in ids and cid != c["id"]})
        c["cites_in_corpus"] = in_corpus
        n_edges += len(in_corpus)

    # Disambiguate duplicate name_abbreviations for graph-entity naming
    # (19 duplicates in the 410-case corpus, e.g. two "Brown v. Voss" cases).
    dupes = {
        n for n, k in Counter(c["name_abbreviation"] for c in cases.values()).items() if k > 1
    }
    for c in cases.values():
        base = c["name_abbreviation"] or f"case-{c['id']}"
        c["entity_name"] = f"{base} ({c['id']})" if base in dupes else base

    with open(DATA / "corpus.jsonl", "w") as f:
        for cid in sorted(cases, key=int):
            f.write(json.dumps(cases[cid]) + "\n")

    gold_strict = sorted(
        cid for cid, lab in GOLD_LABELS.items() if lab.startswith(STRICT_PREFIXES) and cid in ids
    )
    gold_plus = sorted(
        cid
        for cid, lab in GOLD_LABELS.items()
        if lab.startswith(PLUS_PREFIXES) and lab != "no" and cid in ids
    )
    missing = sorted(cid for cid in GOLD_LABELS if cid not in ids)
    gold = {
        "question": GOLD_QUESTION,
        "labels": GOLD_LABELS,
        "gold_strict": gold_strict,
        "gold_plus": gold_plus,
        "missing_from_corpus": missing,
        "notes": (
            "gold_strict = labels starting with 'gold'; gold_plus adds 'orig*' and "
            "'maybe*'. 'no' ids are hand-labeled irrelevant. Two labeled ids are "
            "absent from the shipped 410-case corpus and excluded from both sets."
        ),
    }
    with open(DATA / "gold.json", "w") as f:
        json.dump(gold, f, indent=2)

    # One embedding per case (the AGE arm's shape: one description_vector per
    # row, same as Microsoft — but bge-small-en-v1.5 384-dim instead of
    # text-embedding-3-small 1536-dim, so both arms share one local embedder).
    print("embedding 410 cases with fastembed BAAI/bge-small-en-v1.5 ...")
    from fastembed import TextEmbedding

    model = TextEmbedding("BAAI/bge-small-en-v1.5")
    ordered = [cases[cid] for cid in sorted(cases, key=int)]
    embs = list(model.embed([c["text"] for c in ordered], batch_size=32))
    with open(DATA / "age_embeddings.jsonl", "w") as f:
        for c, e in zip(ordered, embs):
            f.write(
                json.dumps({"id": c["id"], "embedding": [round(float(x), 8) for x in e]}) + "\n"
            )

    manifest = {
        "source_repo": "https://github.com/Azure-Samples/graphrag-legalcases-postgres",
        "source_file": "data/cases_final.csv",
        "source_sha256": sha256_file(csv_path),
        "n_cases": len(cases),
        "courts": dict(Counter(str(c["court_id"]) for c in cases.values())),
        "n_citation_edges_in_corpus": n_edges,
        "n_gold_strict": len(gold_strict),
        "n_gold_plus": len(gold_plus),
        "embed_model": "BAAI/bge-small-en-v1.5",
        "embed_dim": 384,
        "embed_input": f"name || opinion_0[:{EMBED_CHAR_LIMIT}]",
    }
    with open(DATA / "manifest.json", "w") as f:
        json.dump(manifest, f, indent=2)
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
