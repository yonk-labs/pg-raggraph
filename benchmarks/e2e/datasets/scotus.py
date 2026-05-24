"""SCOTUS custom-corpus loader for the benchmark harness.

Corpus: the markdown Supreme Court opinion summaries in ``benchmarks/scotus/``
(one file per case). Queries: the vendored 50-question bucket fixture
``benchmarks/scotus-50-query-buckets.yaml`` (mirrors chunkshop's eval fixture).

Each query carries its ``bucket`` in ``strata`` so analysis can separate
RAG-fair questions (easy/medium/layup) from the metadata-aggregation buckets
(impossible/hard) that top-k retrieval is not expected to answer.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from benchmarks.e2e.datasets import register
from benchmarks.e2e.datasets._common import (
    CorpusDoc,
    DatasetBundle,
    Query,
    load_subset_ids,
    save_subset_ids,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CORPUS_DIR = _REPO_ROOT / "benchmarks" / "scotus"
_FIXTURE = _REPO_ROOT / "benchmarks" / "scotus-50-query-buckets.yaml"

_TERM_RE = re.compile(r"^\*\*Term:\*\*\s*(\d{4})", re.MULTILINE)
_DOCKET_RE = re.compile(r"^\*\*Docket Number:\*\*\s*(\S+)", re.MULTILINE)

_LICENSE = (
    "SCOTUS opinion summaries — public-domain U.S. government work. "
    "Query bucket fixture mirrors chunkshop docs/samples/eval."
)


def _load_corpus() -> list[CorpusDoc]:
    docs: list[CorpusDoc] = []
    for path in sorted(_CORPUS_DIR.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        meta: dict = {"source_path": path.name}
        term = _TERM_RE.search(text)
        if term:
            meta["term"] = term.group(1)
        docket = _DOCKET_RE.search(text)
        if docket:
            meta["docket_number"] = docket.group(1)
        docs.append(CorpusDoc(source_id=path.stem, text=text, metadata=meta))
    return docs


def _load_queries() -> list[Query]:
    fixture = yaml.safe_load(_FIXTURE.read_text(encoding="utf-8"))
    queries: list[Query] = []
    for q in fixture.get("questions", []):
        gold = q.get("gold_answer")
        answers = [str(gold)] if gold else []
        queries.append(
            Query(
                qid=f"scotus:q:{q['id']}",
                question=str(q["question"]),
                answers=answers,
                strata={
                    "bucket": str(q.get("bucket", "")),
                    "rag_applicable": str(q.get("rag_applicable", "")),
                    "retrieval_contract": str(q.get("retrieval_contract", "")),
                },
            )
        )
    return queries


def _pick_subset(all_queries: list[Query], subset: int, seed: int) -> list[Query]:
    if subset <= 0 or subset >= len(all_queries):
        return all_queries
    frozen = load_subset_ids("scotus", subset, seed)
    if frozen is not None:
        by_id = {q.qid: q for q in all_queries}
        missing = [qid for qid in frozen if qid not in by_id]
        if missing:
            raise ValueError(
                f"frozen subset scotus-{subset}-seed{seed} references "
                f"{len(missing)} unknown qids; regenerate the subset file"
            )
        return [by_id[qid] for qid in frozen]
    import random

    rng = random.Random(seed)
    picked = rng.sample(all_queries, subset)
    save_subset_ids("scotus", subset, seed, [q.qid for q in picked])
    return picked


def load(subset: int = 50, seed: int = 42) -> DatasetBundle:
    corpus = _load_corpus()
    queries = _pick_subset(_load_queries(), subset, seed)
    return DatasetBundle(
        name="scotus",
        corpus_docs=corpus,
        queries=queries,
        license_notice=_LICENSE,
    )


register("scotus", load)
