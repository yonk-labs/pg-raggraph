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
import hashlib
import io
import json
import os
import random
import subprocess
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

    # Schema discovery — the HF dataset is a list of dicts; the shapes are
    # documented in huggingface.co/datasets/GraphRAG-Bench/GraphRAG-Bench
    documents = []
    if isinstance(raw_corpus, list):
        for i, row in enumerate(raw_corpus):
            # Corpus file keys observed: {id, source, title?, text | content}
            text = row.get("content") or row.get("text") or row.get("context") or ""
            if not text:
                continue
            doc_id = row.get("id") or _doc_id(text, prefix=f"grb-{subset}")
            documents.append(
                {
                    "id": str(doc_id),
                    "title": row.get("title", "") or row.get("source", ""),
                    "content": text,
                    "metadata": {
                        "corpus": f"graphrag-bench-{subset}",
                        "source": row.get("source", ""),
                    },
                }
            )
    elif isinstance(raw_corpus, dict):
        # Keyed dict form: {doc_id: text, ...} or {doc_id: {content, title, ...}}
        for doc_id, val in raw_corpus.items():
            if isinstance(val, str):
                text, title = val, ""
            else:
                text = val.get("content") or val.get("text") or ""
                title = val.get("title") or val.get("source") or ""
            if not text:
                continue
            documents.append(
                {
                    "id": str(doc_id),
                    "title": title,
                    "content": text,
                    "metadata": {
                        "corpus": f"graphrag-bench-{subset}",
                        "source": title,
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


def _unzip_docs(zip_path: Path) -> list[dict]:
    """Each zip holds a flat collection of .txt transcripts. One doc per file."""
    documents = []
    with zipfile.ZipFile(zip_path) as zf:
        for name in sorted(zf.namelist()):
            if name.endswith("/"):
                continue
            data = zf.read(name).decode("utf-8", errors="replace")
            if not data.strip():
                continue
            doc_id = Path(name).stem
            title = Path(name).stem.replace("_", " ")
            documents.append(
                {
                    "id": doc_id,
                    "title": title,
                    "content": data,
                    "metadata": {"corpus": zip_path.stem, "filename": name},
                }
            )
    return documents


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


def load_ms_hotpotqa(
    n_questions: int = 100, seed: int = 42
) -> tuple[list[dict], list[dict]]:
    docs = _unzip_docs(_ms_path("hotpotqa-input"))
    qs = _parse_ms_questions(_ms_path("hotpotqa-questions"), corpus_tag="ms-hotpotqa")
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
