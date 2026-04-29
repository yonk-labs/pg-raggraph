"""Prepare MuSiQue-Ans dev split for pg-raggraph.

Strategy: pool-mode benchmark.
  - Stratified sample N questions across 2-hop / 3-hop / 4-hop.
  - Pool the union of all paragraphs (supporting + distractors) into a
    single corpus, dedupe by (title, paragraph_text).
  - Write each unique paragraph as a markdown doc under docs/.
  - Save the sampled questions to questions.json for the eval runner.

This is the shape that lets graph mode shine: retrieval has to find the
right 2-4 paragraphs out of the pooled set, and entity chains across
paragraphs are the natural way to do that.
"""

import json
import os
import random
import re
from collections import defaultdict

BENCH_DIR = os.path.dirname(__file__)
INPUT_JSONL = os.path.join(BENCH_DIR, "raw", "musique_ans_v1.0_dev.jsonl")
OUTPUT_DOCS = os.path.join(BENCH_DIR, "docs")
OUTPUT_QUESTIONS = os.path.join(BENCH_DIR, "questions.json")
OUTPUT_MANIFEST = os.path.join(BENCH_DIR, "manifest.json")

# 33/33/34 across 2-hop / 3-hop / 4-hop
N_2HOP = 33
N_3HOP = 33
N_4HOP = 34
SEED = 20260429


def slugify(text: str) -> str:
    text = re.sub(r"[^\w\s-]", "", text).strip()
    text = re.sub(r"[\s_-]+", "-", text)
    return text[:100] or "untitled"


def hop_class(qid: str) -> str:
    prefix = qid.split("__")[0]
    if prefix == "2hop":
        return "2hop"
    if prefix.startswith("3hop"):
        return "3hop"
    if prefix.startswith("4hop"):
        return "4hop"
    return "unknown"


def main():
    os.makedirs(OUTPUT_DOCS, exist_ok=True)

    print(f"Loading {INPUT_JSONL}")
    by_hop: dict[str, list] = defaultdict(list)
    with open(INPUT_JSONL) as f:
        for line in f:
            q = json.loads(line)
            by_hop[hop_class(q["id"])].append(q)

    print("Pool sizes:")
    for k, v in sorted(by_hop.items()):
        print(f"  {k}: {len(v)}")

    rng = random.Random(SEED)
    sampled = (
        rng.sample(by_hop["2hop"], N_2HOP)
        + rng.sample(by_hop["3hop"], N_3HOP)
        + rng.sample(by_hop["4hop"], N_4HOP)
    )
    rng.shuffle(sampled)
    print(f"Sampled {len(sampled)} questions ({N_2HOP}/{N_3HOP}/{N_4HOP})")

    # Pool unique paragraphs across all sampled questions.
    # Dedup key: (title, paragraph_text) — the same Wiki paragraph can show up
    # in many questions but should only be ingested once.
    paragraphs: dict[tuple[str, str], dict] = {}
    for q in sampled:
        for p in q["paragraphs"]:
            key = (p["title"], p["paragraph_text"])
            if key not in paragraphs:
                paragraphs[key] = {
                    "title": p["title"],
                    "paragraph_text": p["paragraph_text"],
                }

    print(f"Unique paragraphs to ingest: {len(paragraphs)}")

    # Write each paragraph as its own markdown doc. Filename collisions
    # are resolved by appending a counter (different paragraphs from the
    # same Wiki page get different files, and they have different content
    # so the search index will distinguish them).
    used_filenames: dict[str, int] = {}
    file_index: dict[tuple[str, str], str] = {}
    for (title, text), _ in paragraphs.items():
        slug = slugify(title)
        n = used_filenames.get(slug, 0)
        used_filenames[slug] = n + 1
        filename = f"{slug}.md" if n == 0 else f"{slug}--{n}.md"
        filepath = os.path.join(OUTPUT_DOCS, filename)
        content = f"# {title}\n\n{text.strip()}\n"
        with open(filepath, "w") as f:
            f.write(content)
        file_index[(title, text)] = filename

    print(f"Wrote {len(file_index)} markdown docs to {OUTPUT_DOCS}")

    # Build questions.json with everything the runner needs.
    questions_out = []
    for q in sampled:
        supporting = [
            {
                "title": p["title"],
                "filename": file_index[(p["title"], p["paragraph_text"])],
            }
            for p in q["paragraphs"]
            if p["is_supporting"]
        ]
        questions_out.append(
            {
                "id": q["id"],
                "hop_class": hop_class(q["id"]),
                "question": q["question"],
                "answer": q["answer"],
                "answer_aliases": q.get("answer_aliases", []),
                "supporting": supporting,
                "decomposition": q.get("question_decomposition", []),
            }
        )

    with open(OUTPUT_QUESTIONS, "w") as f:
        json.dump(questions_out, f, indent=2)
    print(f"Wrote {OUTPUT_QUESTIONS} ({len(questions_out)} questions)")

    manifest = {
        "source": "MuSiQue-Ans dev split (Trivedi et al. 2022)",
        "source_url": "https://huggingface.co/datasets/dgslibisey/MuSiQue",
        "sample_size": {"2hop": N_2HOP, "3hop": N_3HOP, "4hop": N_4HOP, "total": len(sampled)},
        "seed": SEED,
        "unique_paragraphs": len(paragraphs),
        "doc_count": len(file_index),
    }
    with open(OUTPUT_MANIFEST, "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"Wrote {OUTPUT_MANIFEST}")


if __name__ == "__main__":
    main()
