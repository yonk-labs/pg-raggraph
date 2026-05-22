"""MultiHop-RAG loader.

Source: github.com/yixuantt/MultiHop-RAG (MIT licensed). Corpus is 609 news
documents; queries carry ``question_type`` (inference / comparison /
temporal / null_query). The headline graph-test dataset per the
2026-05-19 findings doc.
"""

from __future__ import annotations

import json
import random

from benchmarks.e2e.datasets import register
from benchmarks.e2e.datasets._common import (
    CorpusDoc,
    DatasetBundle,
    Query,
    cache_dir,
    download,
    load_subset_ids,
    save_subset_ids,
    write_license,
)

CORPUS_URL = (
    "https://media.githubusercontent.com/media/yixuantt/MultiHop-RAG/main/dataset/corpus.json"
)
QUERIES_URL = (
    "https://media.githubusercontent.com/media/yixuantt/MultiHop-RAG/main/dataset/MultiHopRAG.json"
)

LICENSE_NOTICE = (
    "MultiHop-RAG dataset by Yixuan Tang et al. MIT License. "
    "https://github.com/yixuantt/MultiHop-RAG"
)


def _doc_text(d: dict) -> str:
    title = (d.get("title") or "").strip()
    body = (d.get("body") or "").strip()
    if title and body:
        return f"{title}\n\n{body}"
    return body or title


def _query_strata(q: dict) -> dict[str, str]:
    qt = q.get("question_type") or "unknown"
    return {"question_type": qt}


def _answers(q: dict) -> list[str]:
    # MHR queries have a single string answer.
    a = q.get("answer")
    return [a] if isinstance(a, str) and a.strip() else []


def load(subset: int = 500, seed: int = 42) -> DatasetBundle:
    cdir = cache_dir("mhr")
    corpus_path = download(CORPUS_URL, cdir / "corpus.json")
    queries_path = download(QUERIES_URL, cdir / "MultiHopRAG.json")
    write_license("mhr", LICENSE_NOTICE)

    raw_docs = json.loads(corpus_path.read_text(encoding="utf-8"))
    raw_queries = json.loads(queries_path.read_text(encoding="utf-8"))

    corpus_docs = [
        CorpusDoc(
            source_id=f"mhr:doc:{i}",
            text=_doc_text(d),
            metadata={"title": d.get("title"), "source": d.get("source"), "url": d.get("url")},
        )
        for i, d in enumerate(raw_docs)
        if _doc_text(d).strip()
    ]

    all_queries = [
        Query(
            qid=f"mhr:q:{i}",
            question=q["query"],
            answers=_answers(q),
            strata=_query_strata(q),
        )
        for i, q in enumerate(raw_queries)
        if q.get("query") and _answers(q)
    ]

    queries = _pick_subset(all_queries, subset, seed, "mhr")
    return DatasetBundle(
        name="mhr",
        corpus_docs=corpus_docs,
        queries=queries,
        license_notice=LICENSE_NOTICE,
    )


def _pick_subset(all_queries: list[Query], subset: int, seed: int, name: str) -> list[Query]:
    if subset <= 0 or subset >= len(all_queries):
        return all_queries
    frozen = load_subset_ids(name, subset, seed)
    if frozen is not None:
        by_id = {q.qid: q for q in all_queries}
        missing = [qid for qid in frozen if qid not in by_id]
        if missing:
            raise RuntimeError(
                f"frozen subset {name}-{subset}-seed{seed} references "
                f"{len(missing)} unknown qids; regenerate the subset file"
            )
        return [by_id[qid] for qid in frozen]
    # First time: pick deterministically and freeze.
    rng = random.Random(seed)
    picked = rng.sample(all_queries, subset)
    save_subset_ids(name, subset, seed, [q.qid for q in picked])
    return picked


register("mhr", load)
