"""Loaders for external public corpora used in the multi-corpus benchmark series.

Each loader returns (documents, questions) where:
- documents: list[dict(id, title, content, metadata)]
- questions: list[QuestionYAML-compatible dict]

The bake-off's existing extraction pipeline (``extract_pg_src``) then chunks +
LLM-extracts entities/relationships on top. Seed-stable subset selection via
``seed`` kwarg for reproducibility.

Corpora wired in this module:
- GraphRAG-Bench medical / novel (HuggingFace: GraphRAG-Bench/GraphRAG-Bench)
- Microsoft graphrag-benchmarking-datasets: Kevin Scott Podcast, HotPotQA Filtered,
  MSFT Single/Multi Transcripts

Each loader downloads to ``CORPORA_CACHE_DIR`` (default:
``benchmarks/age-bakeoff/corpora/external/``) and skips re-download if present.
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import os
import random
import re
import subprocess
import tarfile
import zipfile
from pathlib import Path

_BAKEOFF_ROOT = Path(__file__).resolve().parents[3]
CORPORA_CACHE_DIR = Path(
    os.environ.get("BAKEOFF_CORPORA_CACHE", _BAKEOFF_ROOT / "corpora" / "external")
)


def _ensure_cache_dir() -> Path:
    CORPORA_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CORPORA_CACHE_DIR


def _stratified_subset(
    items: list[dict], class_key: str, n: int, seed: int = 42
) -> list[dict]:
    """Pick a stratified subset of ``n`` items, balanced across ``class_key``.

    If ``n >= len(items)``, returns all items (shuffled deterministically).
    Empty ``class_key`` values are grouped under 'unclassified'.
    """
    rng = random.Random(seed)
    buckets: dict[str, list[dict]] = {}
    for item in items:
        cls = item.get(class_key) or "unclassified"
        buckets.setdefault(cls, []).append(item)

    if n >= len(items):
        shuffled = items.copy()
        rng.shuffle(shuffled)
        return shuffled

    # Even allocation across classes, with remainder fills
    classes = sorted(buckets.keys())
    per_class = n // len(classes)
    remainder = n % len(classes)
    picked: list[dict] = []
    for i, cls in enumerate(classes):
        take = per_class + (1 if i < remainder else 0)
        pool = buckets[cls]
        rng.shuffle(pool)
        picked.extend(pool[:take])
    rng.shuffle(picked)
    return picked


def _doc_id(text: str, prefix: str = "doc") -> str:
    h = hashlib.sha256(text.encode()).hexdigest()[:12]
    return f"{prefix}-{h}"


# ---------------------------------------------------------------------------
# GraphRAG-Bench (HuggingFace: GraphRAG-Bench/GraphRAG-Bench)
# ---------------------------------------------------------------------------

_GRB_CORPUS_URL = (
    "https://huggingface.co/datasets/GraphRAG-Bench/GraphRAG-Bench/"
    "resolve/main/Datasets/Corpus/{subset}.json"
)
_GRB_QUESTIONS_URL = (
    "https://huggingface.co/datasets/GraphRAG-Bench/GraphRAG-Bench/"
    "resolve/main/Datasets/Questions/{subset}_questions.json"
)


_MEDICAL_TOPIC_RE = re.compile(r"(?:^|(?<=\. ))About\s+([a-z][^?.]{3,80}?)(?=\s+(?:What|How|Basal|\?|$))")


def _split_medical_topics(text: str) -> list[tuple[str, str]]:
    """Split the concatenated medical corpus on "About <Topic>" boundaries.

    Returns list of (title, body) tuples. Falls back to a single (corpus,
    text) tuple if the regex finds no matches (defensive — don't lose data).
    """
    import re as _re

    # Simpler heuristic: find each "About X" at the start or after a
    # sentence end, use the "What is X?" follow-up to extract the topic name.
    # The corpus pattern is: "About <topic> What is <topic>? ..."
    boundaries = []
    # Locate each "About " occurrence that's at start-of-string or after
    # a sentence terminator.
    for m in _re.finditer(r"(?:^|(?<=[.?!]\s))About\s+", text):
        boundaries.append(m.start())
    if len(boundaries) < 2:
        return [("medical corpus", text.strip())]

    parts = []
    for i, start in enumerate(boundaries):
        end = boundaries[i + 1] if i + 1 < len(boundaries) else len(text)
        chunk = text[start:end].strip()
        # Title = "About <topic>" — up to "?" or "." or 80 chars
        title_match = _re.match(r"About\s+([^.?]{3,80})", chunk)
        title = (
            title_match.group(1).strip()
            if title_match
            else f"medical topic {i}"
        )
        parts.append((title, chunk))
    return parts


def _download(url: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        return dest
    # Use curl for simplicity + reliability over huggingface-cli auth churn
    subprocess.run(
        ["curl", "-L", "-f", "-s", "-o", str(dest), url],
        check=True,
    )
    return dest


def load_graphrag_bench(
    subset: str, n_questions: int = 100, seed: int = 42
) -> tuple[list[dict], list[dict]]:
    """Load GraphRAG-Bench medical or novel subset.

    Returns ``(documents, questions)`` with a stratified 100-question subset by
    default (25 per question_type: Fact Retrieval, Complex Reasoning,
    Contextual Summarization, Creative Generation).
    """
    if subset not in ("medical", "novel"):
        raise ValueError(f"Unknown GraphRAG-Bench subset: {subset!r}")
    cache = _ensure_cache_dir() / "graphrag-bench"
    corpus_path = cache / f"{subset}.json"
    questions_path = cache / f"{subset}_questions.json"
    _download(_GRB_CORPUS_URL.format(subset=subset), corpus_path)
    _download(_GRB_QUESTIONS_URL.format(subset=subset), questions_path)

    raw_corpus = json.loads(corpus_path.read_text())
    raw_questions = json.loads(questions_path.read_text())

    # GraphRAG-Bench ships the corpus as a list of `{corpus_name, context}`
    # rows. For novel: one row per novel (20 rows). For medical: a single
    # row containing ~33 topics concatenated, each starting with "About X".
    # Split medical on "About " boundaries so each topic becomes its own
    # document with a semantic title.
    documents = []
    for row in raw_corpus if isinstance(raw_corpus, list) else [raw_corpus]:
        raw_text = row.get("context") or row.get("content") or row.get("text") or ""
        row_title = row.get("corpus_name") or row.get("title") or row.get("source") or ""
        if not raw_text:
            continue

        if subset == "medical":
            # Split on "About <Topic>" — the natural document boundary for
            # the concatenated medical corpus.
            parts = _split_medical_topics(raw_text)
            for i, (topic_title, body) in enumerate(parts):
                documents.append(
                    {
                        "id": f"medical-{i:02d}-{_doc_id(body, prefix='t')[:8]}",
                        "title": topic_title,
                        "content": body,
                        "metadata": {
                            "corpus": "graphrag-bench-medical",
                            "topic_index": i,
                        },
                    }
                )
        else:
            documents.append(
                {
                    "id": f"novel-{_doc_id(raw_text, prefix='')[:8]}",
                    "title": row_title,
                    "content": raw_text,
                    "metadata": {
                        "corpus": f"graphrag-bench-{subset}",
                        "source": row_title,
                    },
                }
            )

    questions_norm = []
    for q in raw_questions:
        # Observed fields: id, source, question, answer, question_type, evidence
        questions_norm.append(
            {
                "id": str(q.get("id") or _doc_id(q["question"], prefix="grb-q")),
                "question": q["question"],
                "gold_answer": q.get("answer", ""),
                "question_class": q.get("question_type", "unclassified"),
                "evidence": q.get("evidence", []),
                "metadata": {"corpus": f"graphrag-bench-{subset}"},
            }
        )

    questions_sample = _stratified_subset(
        questions_norm, class_key="question_class", n=n_questions, seed=seed
    )
    return documents, questions_sample


# ---------------------------------------------------------------------------
# Microsoft graphrag-benchmarking-datasets
# ---------------------------------------------------------------------------

_MS_BASE = (
    "https://raw.githubusercontent.com/microsoft/"
    "graphrag-benchmarking-datasets/main/data"
)
_MS_FILES = {
    "hotpotqa-input": (
        "HotPotQA%20Filtered%20Input%20Text.zip",
        "HotPotQA Filtered Input Text.zip",
    ),
    "hotpotqa-questions": (
        "HotPotQA%20Filtered%20Questions.csv",
        "HotPotQA Filtered Questions.csv",
    ),
    "kevin-scott-input": (
        "Kevin%20Scott%20Podcast%20Transcripts%20Input%20Text.zip",
        "Kevin Scott Podcast Transcripts Input Text.zip",
    ),
    "kevin-scott-questions": (
        "Kevin%20Scott%20Questions.csv",
        "Kevin Scott Questions.csv",
    ),
    "msft-input": ("MSFT%20Input%20Text.zip", "MSFT Input Text.zip"),
    "msft-multi-questions": (
        "MSFT%20Multi%20Transcript%20Questions.csv",
        "MSFT Multi Transcript Questions.csv",
    ),
    "msft-single-questions": (
        "MSFT%20Single%20Transcript%20Questions.csv",
        "MSFT Single Transcript Questions.csv",
    ),
}


def _ms_path(key: str) -> Path:
    url_name, local_name = _MS_FILES[key]
    cache = _ensure_cache_dir() / "ms-graphrag"
    dest = cache / local_name
    url = f"{_MS_BASE}/{url_name}"
    _download(url, dest)
    return dest


def _unzip_docs(archive_path: Path) -> list[dict]:
    """Each archive holds a flat collection of .txt transcripts. One doc per file.

    MS ships most archives as true .zip but HotPotQA Filtered Input Text.zip is
    actually a gzipped tarball despite the extension. Auto-detects by header.
    """
    documents = []
    with archive_path.open("rb") as f:
        header = f.read(4)

    if header[:2] == b"PK":
        # True zip
        with zipfile.ZipFile(archive_path) as zf:
            names = sorted(zf.namelist())
            for name in names:
                if name.endswith("/"):
                    continue
                data = zf.read(name).decode("utf-8", errors="replace")
                if not data.strip():
                    continue
                documents.append(_archive_row(name, data, archive_path))
    elif header[:2] == b"\x1f\x8b":
        # gzip — try as tar.gz first
        with gzip.open(archive_path, "rb") as gz:
            try:
                with tarfile.open(fileobj=gz, mode="r:") as tf:
                    for member in tf.getmembers():
                        if not member.isfile():
                            continue
                        extracted = tf.extractfile(member)
                        if extracted is None:
                            continue
                        data = extracted.read().decode("utf-8", errors="replace")
                        if not data.strip():
                            continue
                        documents.append(_archive_row(member.name, data, archive_path))
            except tarfile.TarError:
                # Plain gzip of a single file
                gz.seek(0)
                data = gz.read().decode("utf-8", errors="replace")
                documents.append(_archive_row(archive_path.stem, data, archive_path))
    else:
        raise ValueError(
            f"Unknown archive format at {archive_path} (header bytes {header!r})"
        )
    return documents


def _archive_row(name: str, data: str, archive_path: Path) -> dict:
    stem = Path(name).stem
    return {
        "id": stem,
        "title": stem.replace("_", " "),
        "content": data,
        "metadata": {"corpus": archive_path.stem, "filename": name},
    }


def _parse_ms_questions(csv_path: Path, corpus_tag: str) -> list[dict]:
    """Parse MS question CSVs. Column names vary by file; discovered via inspection:

    - Kevin Scott: ``question_text, question_id`` (BOM-prefixed, no gold answer)
    - MSFT Single/Multi: similar shape; exact columns normalized at read time

    Gold answers are absent in some sets (Kevin Scott, MSFT) — these are
    sensemaking benchmarks judged by LLM against the corpus itself rather than
    against a reference string. We preserve whatever gold columns exist and
    leave ``gold_answer`` empty when they don't.
    """
    out = []
    # utf-8-sig strips BOM that MS CSVs include
    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            normalized = {
                (k or "").strip().lower(): v for k, v in row.items() if k is not None
            }
            q = (
                normalized.get("question_text")
                or normalized.get("question")
                or normalized.get("query")
                or normalized.get("text")
            )
            if not q:
                continue
            a = (
                normalized.get("answer")
                or normalized.get("gold_answer")
                or normalized.get("response")
                or ""
            )
            qid = (
                normalized.get("question_id")
                or normalized.get("id")
                or normalized.get("qid")
                or _doc_id(q, prefix="ms-q")
            )
            out.append(
                {
                    "id": str(qid),
                    "question": q,
                    "gold_answer": a,
                    "question_class": normalized.get("question_type")
                    or normalized.get("type")
                    or normalized.get("class")
                    or "unclassified",
                    "metadata": {"corpus": corpus_tag},
                }
            )
    return out


_HOTPOTQA_DEV_URL = (
    "http://curtis.ml.cmu.edu/datasets/hotpot/hotpot_dev_fullwiki_v1.json"
)


def _load_hotpotqa_gold_answers() -> dict[str, str]:
    """Fetch upstream HotPotQA dev set (CC-BY-SA 4.0, Yang et al. 2018) to
    recover gold answers for questions in MS's filtered set.

    MS's HotPotQA Filtered CSV ships only question_id + question_text. The
    upstream HotPotQA release (curtis.ml.cmu.edu) has matching _id → answer
    entries. Returns a {question_id: answer} map, cached locally after first
    fetch.
    """
    cache = _ensure_cache_dir() / "ms-graphrag" / "hotpotqa_dev_fullwiki_v1.json"
    if not cache.exists():
        _download(_HOTPOTQA_DEV_URL, cache)
    data = json.loads(cache.read_text())
    # Upstream schema: list of {"_id", "answer", "question", "supporting_facts",
    # "context", "type", "level"}
    return {row["_id"]: row["answer"] for row in data if row.get("answer")}


def load_ms_hotpotqa(
    n_questions: int = 100, seed: int = 42, include_gold: bool = True
) -> tuple[list[dict], list[dict]]:
    """Load MS's HotPotQA Filtered set. Optionally augment with upstream
    gold answers (default True) so the classic fully_correct/partial/wrong
    judge rubric works. Without gold, questions are pairwise-only.
    """
    docs = _unzip_docs(_ms_path("hotpotqa-input"))
    qs = _parse_ms_questions(_ms_path("hotpotqa-questions"), corpus_tag="ms-hotpotqa")
    if include_gold:
        gold = _load_hotpotqa_gold_answers()
        matched = 0
        for q in qs:
            if q["id"] in gold:
                q["gold_answer"] = gold[q["id"]]
                matched += 1
        # Drop any question without a gold answer — they'd degrade the sweep
        qs = [q for q in qs if q["gold_answer"]]
        # Log coverage; helpful for Phase 2 paper methodology section
        print(
            f"  ms-hotpotqa: gold-answer coverage {matched}/{matched + (len(qs) - matched)}"
        )
    qs_sample = _stratified_subset(qs, class_key="question_class", n=n_questions, seed=seed)
    return docs, qs_sample


def load_ms_kevin_scott(
    n_questions: int | None = None, seed: int = 42
) -> tuple[list[dict], list[dict]]:
    docs = _unzip_docs(_ms_path("kevin-scott-input"))
    qs = _parse_ms_questions(_ms_path("kevin-scott-questions"), corpus_tag="ms-kevin-scott")
    if n_questions is None or n_questions >= len(qs):
        return docs, qs
    qs_sample = _stratified_subset(qs, class_key="question_class", n=n_questions, seed=seed)
    return docs, qs_sample


def load_ms_msft(
    which: str = "multi", n_questions: int | None = None, seed: int = 42
) -> tuple[list[dict], list[dict]]:
    """which='multi' or 'single'."""
    if which not in ("multi", "single"):
        raise ValueError(f"which must be 'multi' or 'single', got {which!r}")
    docs = _unzip_docs(_ms_path("msft-input"))
    qs = _parse_ms_questions(
        _ms_path(f"msft-{which}-questions"), corpus_tag=f"ms-msft-{which}"
    )
    if n_questions is None or n_questions >= len(qs):
        return docs, qs
    qs_sample = _stratified_subset(qs, class_key="question_class", n=n_questions, seed=seed)
    return docs, qs_sample


# ---------------------------------------------------------------------------
# Unified dispatch
# ---------------------------------------------------------------------------

CORPUS_LOADERS = {
    "graphrag-bench-medical": lambda n=100, seed=42: load_graphrag_bench("medical", n, seed),
    "graphrag-bench-novel": lambda n=100, seed=42: load_graphrag_bench("novel", n, seed),
    "ms-hotpotqa": lambda n=100, seed=42: load_ms_hotpotqa(n, seed),
    "ms-kevin-scott": lambda n=None, seed=42: load_ms_kevin_scott(n, seed),
    "ms-msft-multi": lambda n=None, seed=42: load_ms_msft("multi", n, seed),
    "ms-msft-single": lambda n=None, seed=42: load_ms_msft("single", n, seed),
}


def load_corpus(
    corpus_id: str, n_questions: int | None = None, seed: int = 42
) -> tuple[list[dict], list[dict]]:
    """Load any registered external corpus by id.

    ``n_questions=None`` means "all questions available in the upstream set."
    Per-corpus defaults are applied when n_questions is not specified.
    """
    if corpus_id not in CORPUS_LOADERS:
        raise ValueError(
            f"Unknown corpus {corpus_id!r}. Available: {sorted(CORPUS_LOADERS)}"
        )
    loader = CORPUS_LOADERS[corpus_id]
    if n_questions is None:
        return loader()
    return loader(n=n_questions, seed=seed)
