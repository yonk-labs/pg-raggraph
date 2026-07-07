#!/usr/bin/env python3
"""Build the citation-derived gold sets (METHODOLOGY.md §2-3). Deterministic:
same corpus + same seed => byte-identical output.

Task A (issue-description retrieval): question = scrubbed excerpt from
opinion[8500:] (beyond the 8000-char ingest cut — zero verbatim overlap with
any ingested chunk); gold = {target} ∪ in-corpus citations.

Task B (citation lookup): question names the caption + official cite;
gold = in-corpus citations only; targets restricted to unique captions.

Writes data/gold_taskA_seed{41,42,43}.json, data/gold_taskB_seed{41,42,43}.json
and data/gold_pool_stats.json.

Usage:
    uv run --no-sync python benchmarks/age-bakeoff/cap-gold-v1/build_gold.py
"""

from __future__ import annotations

import hashlib
import json
import random
import re
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"

SEEDS = [41, 42, 43]
N_QUESTIONS = 50
MIN_CITES = 4  # E1
MIN_OPINION = 9500  # E2
EXCERPT_START = 8500  # relative to opinion start; corpus stores tail from 8000
MIN_EXCERPT = 400
MAX_EXCERPT = 900
MIN_POST_SCRUB = 200  # V1

# --- scrub regexes (METHODOLOGY §2.3; refined in the preregistered pilot) ---
CITE_RX = re.compile(
    r"\b\d{1,4}\s+"
    r"(?:Wn\.?\s?(?:2d|App\.?)?|Wash\.?\s?(?:2d|App\.?|Terr\.?)?|P\.\s?[23]?d?\.?"
    r"|U\.S\.|S\.\s?Ct\.|L\.\s?Ed\.\s?(?:2d)?|F\.\s?(?:Supp\.?|[23]d)?"
    r"|A\.L\.R\.[23]?d?|Am\.\s?Jur\.?\s?2?d?|C\.J\.S\.|Wash\.\s?L\.\s?Rev\."
    r"|Gonz\.\s?L\.\s?Rev\.|A\.[23]?d?)"
    r"\s*(?:\(\w+\))?\s*\d*(?:,\s*\d+(?:-\d+)?)*"
)
CAPTION_RX = re.compile(
    r"\b(?:In re\s+|State ex rel\.\s+)?"
    r"(?:[A-Z][\w.'&\-]*\s+){0,6}v\.\s+(?:[A-Z][\w.'&\-]*[,.]?\s*){1,6}"
)
IN_RE_RX = re.compile(r"\bIn re\s+(?:[A-Z][\w.'&\-]*[,.]?\s*){1,6}")
SUPRA_RX = re.compile(r",?\s*\b(?:supra|infra)\b[.,]?")
DOCKET_RX = re.compile(r"\bNo\.\s?\d[\w.\-]*\b")
DANGLING_PAREN_RX = re.compile(r"\([^)]*(?:\[citation\]|\[case\]|supra)[^)]*\)?")
MARKER_RUN_RX = re.compile(r"(?:\s*\[(?:citation|case)\]\s*[,;]?\s*)+")

TEMPLATES = [
    "Which Washington precedents govern this situation: {x}",
    "Find Washington case law relevant to the following analysis: {x}",
    "What cases from the Washington Supreme Court bear on this issue: {x}",
    "Identify the controlling authorities for this legal question: {x}",
    "Which decisions address the following dispute: {x}",
]


def build_excerpt(tail: str) -> str | None:
    """tail = opinion[8000:12000] from the corpus; excerpt starts at 8500."""
    window = tail[500:]  # 8000 + 500 = preregistered start 8500
    m = re.search(r"[.!?]\s+[A-Z]", window)
    if not m:
        return None
    window = window[m.end() - 1 :]
    sents = re.split(r"(?<=[.!?])\s+", window)
    out: list[str] = []
    total = 0
    for s in sents:
        out.append(s)
        total += len(s) + 1
        if total >= MIN_EXCERPT:
            break
    if len(out) < 2:  # V3
        return None
    return " ".join(out)[:MAX_EXCERPT]


def party_tokens(name_abbreviation: str) -> list[str]:
    toks = re.split(r"\s+v\.\s+|,|\s+", name_abbreviation)
    return [t.strip(".'&") for t in toks if len(t.strip(".'&")) > 3]


def scrub(excerpt: str, name_abbreviation: str) -> str:
    x = CITE_RX.sub(" [citation] ", excerpt)
    x = CAPTION_RX.sub(" [case] ", x)
    x = IN_RE_RX.sub(" [case] ", x)
    x = DOCKET_RX.sub(" ", x)
    x = SUPRA_RX.sub(" ", x)
    x = DANGLING_PAREN_RX.sub(" ", x)
    for tok in party_tokens(name_abbreviation):
        x = re.sub(rf"\b{re.escape(tok)}\b", "[party]", x, flags=re.IGNORECASE)
    x = MARKER_RUN_RX.sub(" [citation] ", x)
    x = re.sub(r"\s+", " ", x).strip()
    return x


def make_question_a(case: dict) -> str | None:
    excerpt = build_excerpt(case["opinion_tail"])
    if excerpt is None:
        return None
    q = scrub(excerpt, case["name_abbreviation"])
    if len(q) < MIN_POST_SCRUB:  # V1
        return None
    for tok in party_tokens(case["name_abbreviation"]):  # V2
        if re.search(rf"\b{re.escape(tok)}\b", q, flags=re.IGNORECASE):
            return None
    tmpl = TEMPLATES[int(hashlib.sha256(case["id"].encode()).hexdigest(), 16) % len(TEMPLATES)]
    return tmpl.format(x=q)


def make_question_b(case: dict) -> str:
    year = case["decision_date"][:4]
    cite = case["official_cite"] or "Washington Reports 2d"
    return f"Which precedents does {case['name_abbreviation']}, {cite} ({year}), rely on?"


def main() -> None:
    corpus = [json.loads(line) for line in open(DATA / "corpus.jsonl")]
    caption_counts = Counter(c["name_abbreviation"] for c in corpus)

    pool_a: list[dict] = []
    fail = Counter()
    for c in corpus:
        if len(c["cites_in_corpus"]) < MIN_CITES:
            fail["E1_cites"] += 1
            continue
        if c["opinion_len"] < MIN_OPINION:
            fail["E2_length"] += 1
            continue
        q = make_question_a(c)
        if q is None:
            fail["E3_question"] += 1
            continue
        pool_a.append({"case": c, "question": q})
    pool_a.sort(key=lambda e: int(e["case"]["id"]))

    pool_b = [e for e in pool_a if caption_counts[e["case"]["name_abbreviation"]] == 1]

    stats = {
        "corpus_cases": len(corpus),
        "pool_a": len(pool_a),
        "pool_b": len(pool_b),
        "pool_b_excluded_duplicate_caption": len(pool_a) - len(pool_b),
        "eligibility_failures": dict(fail),
        "seeds": SEEDS,
        "n_questions_per_seed": N_QUESTIONS,
    }
    with open(DATA / "gold_pool_stats.json", "w") as f:
        json.dump(stats, f, indent=2)
    print(json.dumps(stats, indent=2))

    for seed in SEEDS:
        sample_a = random.Random(seed).sample(pool_a, N_QUESTIONS)
        out_a = []
        for e in sample_a:
            c = e["case"]
            out_a.append(
                {
                    "target_id": c["id"],
                    "target_caption": c["name_abbreviation"],
                    "question": e["question"],
                    "gold": sorted([c["id"], *c["cites_in_corpus"]], key=int),
                    "gold_cited": sorted(c["cites_in_corpus"], key=int),
                }
            )
        with open(DATA / f"gold_taskA_seed{seed}.json", "w") as f:
            json.dump(out_a, f, indent=2)

        sample_b = random.Random(seed).sample(pool_b, N_QUESTIONS)
        out_b = []
        for e in sample_b:
            c = e["case"]
            out_b.append(
                {
                    "target_id": c["id"],
                    "target_caption": c["name_abbreviation"],
                    "question": make_question_b(c),
                    "gold": sorted(c["cites_in_corpus"], key=int),
                }
            )
        with open(DATA / f"gold_taskB_seed{seed}.json", "w") as f:
            json.dump(out_b, f, indent=2)
        print(f"seed {seed}: taskA {len(out_a)} questions, taskB {len(out_b)} questions")


if __name__ == "__main__":
    main()
