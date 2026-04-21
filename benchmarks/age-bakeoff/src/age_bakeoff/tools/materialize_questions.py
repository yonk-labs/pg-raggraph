"""Materialize a corpus's question set into a YAML file the judge consumes.

Reads from external_corpora.CORPUS_LOADERS, applies stratified subset
selection, writes ``questions/{corpus}.yaml`` matching the existing schema:

    name: <corpus_id>
    questions:
      - id: <qid>
        question: <text>
        gold_answer: <text>
        question_class: <class>
        metadata: {...}

Usage:
    uv run python -m age_bakeoff.tools.materialize_questions \\
        --corpus graphrag-bench-medical \\
        --n 100 --seed 42 \\
        --out questions/graphrag-bench-medical.yaml
"""
from __future__ import annotations

import argparse
from pathlib import Path

import yaml

from age_bakeoff.extraction.external_corpora import CORPUS_LOADERS, load_corpus


def materialize(corpus_id: str, n: int | None, seed: int, out_path: Path) -> int:
    _docs, questions = load_corpus(corpus_id, n_questions=n, seed=seed)

    yaml_data = {
        "corpus": corpus_id,
        "questions": [
            {
                "id": q["id"],
                "question": q["question"],
                "gold_answer": q.get("gold_answer") or "",
                # GraphRAG-Bench ships `evidence` — map to required_facts so
                # the bakeoff's fact-recall scorer has something to check.
                # MS datasets have neither; default to empty list.
                "required_facts": q.get("evidence", []) or [],
                "question_class": q.get("question_class", "unclassified"),
            }
            for q in questions
        ],
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(yaml.safe_dump(yaml_data, sort_keys=False, allow_unicode=True))
    return len(questions)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--corpus", required=True, choices=sorted(CORPUS_LOADERS.keys()))
    p.add_argument("--n", type=int, default=None, help="question subset size")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()

    n_written = materialize(args.corpus, args.n, args.seed, args.out)
    print(f"Wrote {n_written} questions to {args.out}")


if __name__ == "__main__":
    main()
