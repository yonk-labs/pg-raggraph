"""2WikiMultiHopQA loader (dev split).

Source: github.com/Alab-NII/2wikimultihop. Standard 2-hop benchmark with
gold supporting paths. Dataset is canonically distributed on Google
Drive; we attempt a HuggingFace parquet mirror first, fall back to a
manual-drop instruction.
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

_SOURCES = [
    (
        "https://huggingface.co/api/datasets/framolfese/2WikiMultihopQA/parquet/default/validation/0.parquet",
        "parquet",
    ),
]

LICENSE_NOTICE = (
    "2WikiMultiHopQA dataset by Ho et al. Apache-2.0. https://github.com/Alab-NII/2wikimultihop"
)

MANUAL_FILE = "dev.json"


def _try_fetch(url: str, dest: Path) -> bool:
    try:
        urllib.request.urlretrieve(url, dest)  # noqa: S310
        return True
    except (urllib.error.URLError, urllib.error.HTTPError, OSError):
        return False


def _load_parquet(path: Path) -> list[dict]:
    import pyarrow.parquet as pq

    return pq.read_table(path).to_pylist()


def _load_json(path: Path) -> list[dict]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        return raw
    return raw.get("data", [])


def _normalize(rec: dict, i: int) -> tuple[Query | None, list[CorpusDoc]]:
    q = rec.get("question")
    if not q:
        return None, []
    a = rec.get("answer")
    answers = [a] if isinstance(a, str) and a.strip() else []
    aliases = rec.get("answer_aliases") or rec.get("aliases") or []
    answers.extend(s for s in aliases if isinstance(s, str) and s.strip())
    if not answers:
        return None, []

    qid_raw = rec.get("_id") or rec.get("id") or f"auto-{i}"
    qid = f"twowiki:q:{qid_raw}"
    qtype = rec.get("type") or "unknown"

    # Context shape: HF mirror uses parallel arrays {title: [...], sentences: [[...]]}.
    # Canonical github format uses list of [title, [sentences]] pairs.
    docs: list[CorpusDoc] = []
    ctx = rec.get("context") or []
    pairs: list[tuple[str | None, list[str] | str | None]] = []
    if isinstance(ctx, dict):
        titles = ctx.get("title") or []
        sents_arr = ctx.get("sentences") or ctx.get("content") or []
        for t, s in zip(titles, sents_arr):
            pairs.append((t, s))
    elif isinstance(ctx, list):
        for c in ctx:
            if isinstance(c, list) and len(c) == 2:
                pairs.append((c[0], c[1]))
            elif isinstance(c, dict):
                pairs.append((c.get("title"), c.get("sentences") or c.get("text")))

    for c_idx, (title, sents) in enumerate(pairs):
        if not sents:
            continue
        body = (
            " ".join(s for s in sents if isinstance(s, str))
            if isinstance(sents, list)
            else str(sents)
        )
        if not body.strip():
            continue
        head = (title or "").strip()
        text = f"{head}\n\n{body}" if head else body
        docs.append(
            CorpusDoc(
                source_id=f"twowiki:doc:{qid_raw}:{c_idx}",
                text=text,
                metadata={"title": head, "from_query": qid_raw},
            )
        )

    return Query(qid=qid, question=q, answers=answers, strata={"type": qtype}), docs


def load(subset: int = 500, seed: int = 42) -> DatasetBundle:
    cdir = cache_dir("twowiki")
    write_license("twowiki", LICENSE_NOTICE)

    manual_path = cdir / MANUAL_FILE
    parquet_path = cdir / "validation.parquet"

    rows: list[dict] = []
    if manual_path.exists():
        rows = _load_json(manual_path)
    elif parquet_path.exists():
        rows = _load_parquet(parquet_path)
    else:
        for url, kind in _SOURCES:
            dest = parquet_path if kind == "parquet" else cdir / "dev.json"
            if _try_fetch(url, dest):
                rows = _load_parquet(dest) if kind == "parquet" else _load_json(dest)
                if rows:
                    break
        if not rows:
            raise RuntimeError(
                f"2WikiMultiHopQA not found. Place {MANUAL_FILE} in {cdir} "
                f"(download from https://github.com/Alab-NII/2wikimultihop) and re-run."
            )

    pairs: list[tuple[Query, list[CorpusDoc]]] = []
    for i, rec in enumerate(rows):
        q, docs = _normalize(rec, i)
        if q is not None:
            pairs.append((q, docs))

    all_queries = [p[0] for p in pairs]
    selected = _pick_subset(all_queries, subset, seed, "twowiki")
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
        name="twowiki",
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


register("twowiki", load)
