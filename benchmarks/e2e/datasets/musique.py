"""MuSiQue loader (dev split).

Source: github.com/StonyBrookNLP/musique (CC-BY-4.0). Compositional 2-4
hop questions with gold supporting paragraphs. Dev set hosted on a Dropbox
share by the authors; we mirror it via a HuggingFace parquet endpoint
when the canonical Dropbox URL is unavailable.

If neither source is reachable, drop ``musique_ans_v1.0_dev.jsonl`` into
``~/.cache/pg_raggraph_bench/musique/`` and re-run.
"""

from __future__ import annotations

import json
import random
import urllib.error
import urllib.request
from pathlib import Path

from benchmarks.e2e.datasets import register
from benchmarks.e2e.datasets._common import (
    CorpusDoc,
    DatasetBundle,
    Query,
    cache_dir,
    load_subset_ids,
    save_subset_ids,
    write_license,
)

# Try in order. HF datasets-server gives parquet for the public mirror.
_SOURCES = [
    # tasksource mirror exposes the dev split as parquet
    (
        "https://huggingface.co/api/datasets/dgslibisey/MuSiQue/parquet/default/validation/0.parquet",
        "parquet",
    ),
]

LICENSE_NOTICE = (
    "MuSiQue dataset by Trivedi et al. CC-BY-4.0. https://github.com/StonyBrookNLP/musique"
)

MANUAL_FILE = "musique_ans_v1.0_dev.jsonl"


def _try_fetch_parquet(url: str, dest: Path) -> bool:
    try:
        urllib.request.urlretrieve(url, dest)  # noqa: S310 — explicit URL
        return True
    except (urllib.error.URLError, urllib.error.HTTPError, OSError):
        return False


def _normalize_record(rec: dict, i: int) -> tuple[Query | None, list[CorpusDoc]]:
    q = rec.get("question") or rec.get("question_text")
    if not q:
        return None, []
    answers = []
    a = rec.get("answer") or rec.get("answer_text")
    if isinstance(a, str) and a.strip():
        answers.append(a)
    aliases = rec.get("answer_aliases") or []
    answers.extend(s for s in aliases if isinstance(s, str) and s.strip())
    if not answers:
        return None, []

    # Decomposition gives n_hops.
    decomp = rec.get("question_decomposition") or rec.get("decomposition") or []
    n_hops = len(decomp) if decomp else 0
    stratum = f"{n_hops}hop" if n_hops in (2, 3, 4) else "unknown"

    qid_raw = rec.get("id") or f"musique:auto:{i}"
    qid = f"musique:q:{qid_raw}"

    docs: list[CorpusDoc] = []
    paragraphs = rec.get("paragraphs") or []
    for p_idx, p in enumerate(paragraphs):
        title = (p.get("title") or "").strip()
        text = (p.get("paragraph_text") or p.get("text") or "").strip()
        if not text:
            continue
        body = f"{title}\n\n{text}" if title else text
        docs.append(
            CorpusDoc(
                source_id=f"musique:doc:{qid_raw}:{p_idx}",
                text=body,
                metadata={"title": title, "from_query": qid_raw},
            )
        )

    return Query(qid=qid, question=q, answers=answers, strata={"n_hops": stratum}), docs


def _load_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _load_parquet(path: Path) -> list[dict]:
    import pyarrow.parquet as pq  # local import keeps the dep optional at module load

    table = pq.read_table(path)
    return table.to_pylist()


def load(subset: int = 500, seed: int = 42) -> DatasetBundle:
    cdir = cache_dir("musique")
    write_license("musique", LICENSE_NOTICE)

    manual_path = cdir / MANUAL_FILE
    parquet_path = cdir / "validation.parquet"

    rows: list[dict] = []
    if manual_path.exists():
        rows = _load_jsonl(manual_path)
    elif parquet_path.exists():
        rows = _load_parquet(parquet_path)
    else:
        # Try remote sources
        for url, kind in _SOURCES:
            dest = parquet_path if kind == "parquet" else cdir / "dev.jsonl"
            if _try_fetch_parquet(url, dest):
                rows = _load_parquet(dest) if kind == "parquet" else _load_jsonl(dest)
                break
        if not rows:
            raise RuntimeError(
                f"MuSiQue not found. Place {MANUAL_FILE} in {cdir} "
                f"(download from https://github.com/StonyBrookNLP/musique) and re-run."
            )

    # Per-query distractor corpus: normalize records into (Query, docs[]), pick
    # the query subset, then collect docs only from selected queries (deduped).
    pairs: list[tuple[Query, list[CorpusDoc]]] = []
    for i, rec in enumerate(rows):
        q, docs = _normalize_record(rec, i)
        if q is not None:
            pairs.append((q, docs))

    all_queries = [p[0] for p in pairs]
    selected = _pick_subset(all_queries, subset, seed, "musique")
    selected_ids = {q.qid for q in selected}
    docs_by_query = {p[0].qid: p[1] for p in pairs}

    corpus_docs: list[CorpusDoc] = []
    seen_docs: set[str] = set()
    for qid in selected_ids:
        for d in docs_by_query.get(qid, []):
            if d.source_id not in seen_docs:
                corpus_docs.append(d)
                seen_docs.add(d.source_id)

    return DatasetBundle(
        name="musique",
        corpus_docs=corpus_docs,
        queries=selected,
        license_notice=LICENSE_NOTICE,
    )


def _pick_subset(all_queries: list[Query], subset: int, seed: int, name: str) -> list[Query]:
    if subset <= 0 or subset >= len(all_queries):
        return all_queries
    frozen = load_subset_ids(name, subset, seed)
    if frozen is not None:
        by_id = {q.qid: q for q in all_queries}
        return [by_id[qid] for qid in frozen if qid in by_id]
    rng = random.Random(seed)
    picked = rng.sample(all_queries, subset)
    save_subset_ids(name, subset, seed, [q.qid for q in picked])
    return picked


register("musique", load)
