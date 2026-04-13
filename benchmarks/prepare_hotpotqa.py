"""Prepare HotpotQA data for pg-raggraph ingestion.

Extracts Wikipedia paragraphs from the distractor set as individual markdown documents.
Creates a separate questions.json file for benchmark evaluation.
"""

import json
import os
import re

BENCH_DIR = os.path.dirname(__file__)
INPUT_JSON = os.path.join(BENCH_DIR, "hotpotqa", "hotpot_dev.json")
OUTPUT_DOCS = os.path.join(BENCH_DIR, "hotpotqa", "docs")
OUTPUT_QUESTIONS = os.path.join(BENCH_DIR, "hotpotqa", "questions.json")

# Sample size — full set is 7405 questions, 13783 unique articles
# Start with 500 questions for a meaningful but manageable benchmark
MAX_QUESTIONS = 500


def slugify(text: str) -> str:
    text = re.sub(r"[^\w\s-]", "", text).strip()
    text = re.sub(r"[\s_-]+", "-", text)
    return text[:100]


def main():
    os.makedirs(OUTPUT_DOCS, exist_ok=True)

    print(f"Loading {INPUT_JSON}...")
    with open(INPUT_JSON) as f:
        data = json.load(f)

    print(f"Total questions: {len(data)}")

    # Use first N questions, prioritize bridge + hard questions
    sampled = []
    for q in data:
        if q.get("level") == "hard":
            sampled.append(q)
        if len(sampled) >= MAX_QUESTIONS:
            break

    print(f"Sampled: {len(sampled)} questions (all hard level)")

    # Collect all unique Wikipedia articles referenced
    # (context is list of [title, [sentences...]])
    wiki_docs = {}  # title -> full text

    for q in sampled:
        for item in q.get("context", []):
            if len(item) != 2:
                continue
            title, sentences = item[0], item[1]
            text = "".join(sentences) if isinstance(sentences, list) else str(sentences)
            if title not in wiki_docs:
                wiki_docs[title] = text
            # If we see the same article with more content, keep the longer version
            elif len(text) > len(wiki_docs[title]):
                wiki_docs[title] = text

    print(f"Unique Wikipedia articles: {len(wiki_docs)}")

    # Write each article as a markdown file
    for title, text in wiki_docs.items():
        slug = slugify(title)
        if not slug:
            continue
        filename = f"{slug}.md"
        filepath = os.path.join(OUTPUT_DOCS, filename)
        content = f"# {title}\n\n{text.strip()}"
        with open(filepath, "w") as f:
            f.write(content)

    # Write the questions as a JSON file for the benchmark
    questions_data = []
    for q in sampled:
        supporting_titles = list({sf[0] for sf in q.get("supporting_facts", [])})
        questions_data.append(
            {
                "id": q["_id"],
                "question": q["question"],
                "answer": q["answer"],
                "type": q["type"],  # bridge | comparison
                "level": q["level"],
                "supporting_docs": supporting_titles,  # Which docs contain the answer
            }
        )

    with open(OUTPUT_QUESTIONS, "w") as f:
        json.dump(questions_data, f, indent=2)

    print("\nDone:")
    print(f"  {len(wiki_docs)} documents in {OUTPUT_DOCS}/")
    print(f"  {len(questions_data)} questions in {OUTPUT_QUESTIONS}")

    # Quick stats
    bridge = sum(1 for q in questions_data if q["type"] == "bridge")
    comparison = sum(1 for q in questions_data if q["type"] == "comparison")
    avg_support = sum(len(q["supporting_docs"]) for q in questions_data) / len(questions_data)
    print(f"\n  Bridge questions: {bridge}")
    print(f"  Comparison questions: {comparison}")
    print(f"  Avg supporting docs per question: {avg_support:.1f}")


if __name__ == "__main__":
    main()
