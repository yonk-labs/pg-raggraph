"""LoCoMo loader.

Source: github.com/snap-research/locomo. The cached ``locomo10.json`` file
contains 10 long multi-session conversations plus QA pairs whose evidence
points at dialogue turn IDs such as ``D3:11``.

For pg-raggraph matrix work, each conversation session is one source document.
That preserves the conversational/session boundary while keeping turn IDs in
the retrievable text so evidence can be inspected in prepared contexts.
"""

from __future__ import annotations

import json
import random
import re
from pathlib import Path
from typing import Any

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

LOCAL_CACHE = Path("/home/yonk/yonk-tools/stele/benchmarks/.cache/locomo10.json")
LOCOMO_URL = "https://raw.githubusercontent.com/snap-research/locomo/main/data/locomo10.json"

LICENSE_NOTICE = (
    "LoCoMo dataset by Snap Research. "
    "https://github.com/snap-research/locomo"
)

_SESSION_RE = re.compile(r"session_(\d+)$")


def _source_path() -> Path:
    cdir = cache_dir("locomo")
    dest = cdir / "locomo10.json"
    if LOCAL_CACHE.exists():
        return LOCAL_CACHE
    return download(LOCOMO_URL, dest)


def _session_docs(sample: dict[str, Any]) -> list[CorpusDoc]:
    sid = str(sample.get("sample_id") or "unknown")
    conv = sample.get("conversation") or {}
    speaker_a = str(conv.get("speaker_a") or "")
    speaker_b = str(conv.get("speaker_b") or "")

    docs: list[CorpusDoc] = []
    session_numbers: list[int] = []
    for key in conv:
        match = _SESSION_RE.fullmatch(key)
        if match and isinstance(conv.get(key), list):
            session_numbers.append(int(match.group(1)))

    for n in sorted(session_numbers):
        session_key = f"session_{n}"
        turns = [t for t in conv.get(session_key, []) if isinstance(t, dict)]
        if not turns:
            continue
        date_time = str(conv.get(f"{session_key}_date_time") or "")
        lines = [
            f"LoCoMo conversation {sid}",
            f"Participants: {speaker_a} and {speaker_b}".strip(),
            f"Session {n}",
        ]
        if date_time:
            lines.append(f"Date/time: {date_time}")
        lines.append("")
        for turn in turns:
            dia_id = str(turn.get("dia_id") or f"D{n}:?")
            speaker = str(turn.get("speaker") or "?")
            text = str(turn.get("text") or "").strip()
            if text:
                lines.append(f"{dia_id} [{speaker}] {text}")
        docs.append(
            CorpusDoc(
                source_id=f"locomo:{sid}:session:{n}",
                text="\n".join(lines).strip(),
                metadata={
                    "sample_id": sid,
                    "session": n,
                    "session_key": session_key,
                    "date_time": date_time,
                    "speaker_a": speaker_a,
                    "speaker_b": speaker_b,
                    "turn_ids": [str(t.get("dia_id") or "") for t in turns if t.get("dia_id")],
                },
            )
        )
    return docs


def _evidence_sessions(evidence: list[Any]) -> list[str]:
    sessions: set[str] = set()
    for ref in evidence:
        text = str(ref)
        if ":" in text:
            sessions.add(text.split(":", 1)[0])
    return sorted(sessions)


def _qa_answer(qa: dict[str, Any]) -> list[str]:
    key = "adversarial_answer" if qa.get("category") == 5 else "answer"
    answer = qa.get(key)
    if answer is None:
        answer = qa.get("answer")
    text = str(answer).strip() if answer is not None else ""
    return [text] if text else []


def _all_queries(samples: list[dict[str, Any]]) -> list[Query]:
    queries: list[Query] = []
    for sample in samples:
        sid = str(sample.get("sample_id") or "unknown")
        for i, qa in enumerate(sample.get("qa") or []):
            question = str(qa.get("question") or "").strip()
            answers = _qa_answer(qa)
            if not question or not answers:
                continue
            evidence = qa.get("evidence") or []
            if not isinstance(evidence, list):
                evidence = []
            category = str(qa.get("category", "unknown"))
            queries.append(
                Query(
                    qid=f"locomo:q:{sid}:{i}",
                    question=question,
                    answers=answers,
                    strata={
                        "sample_id": sid,
                        "category": category,
                        "evidence_sessions": ",".join(_evidence_sessions(evidence)),
                        "abstention": "true" if qa.get("category") == 5 else "false",
                    },
                )
            )
    return queries


def load(subset: int = 500, seed: int = 42) -> DatasetBundle:
    write_license("locomo", LICENSE_NOTICE)
    samples: list[dict[str, Any]] = json.loads(_source_path().read_text(encoding="utf-8"))

    corpus_docs: list[CorpusDoc] = []
    for sample in samples:
        corpus_docs.extend(_session_docs(sample))

    queries = _pick_subset(_all_queries(samples), subset, seed, "locomo")
    return DatasetBundle(
        name="locomo",
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
    rng = random.Random(seed)
    picked = rng.sample(all_queries, subset)
    save_subset_ids(name, subset, seed, [q.qid for q in picked])
    return picked


register("locomo", load)
