"""Direction oracle bench (issue #110): does extracted (src, dst) agree with
generator ground truth?

Mirrors the #110 reporter's methodology: a seeded corpus of corporate-registry
briefs whose sentences each express ONE gold edge (agent, patient, family),
with sentence voice drawn 50/50 active/passive. Extraction runs the library's
default prompt per doc; scoring matches extracted relationships to gold entity
PAIRS (undirected), then scores direction separately — an extracted edge is
direction-correct when its (src, dst) reads true under its own rel_type's
frame (active types: src=agent; passive/*_BY types: src=patient). Symmetric or
opaque types (RELATED_TO, ...) are excluded from direction scoring and counted.

Arms:
  base       — the installed EXTRACTION_SYSTEM_PROMPT as-is
  direction  — base + the #110 orientation contract (exact PR #118 text)

Run on main (pre-#118) so `base` measures the shipped prompt:
  uv run python benchmarks/extraction-direction/run_direction_bench.py \
      --arm base --docs 60
  uv run python benchmarks/extraction-direction/run_direction_bench.py \
      --arm direction --docs 60

Model: gpt-5-mini (OpenAI key: ../.openai home_key). No temperature param —
gpt-5 models reject values other than default.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import re
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from pg_raggraph.extraction import EXTRACTION_SYSTEM_PROMPT, _parse_extraction  # noqa: E402

DIRECTION_RULE = (
    '- Direction matters: "source REL_TYPE target" must read as a true sentence.\n'
    '  Passive text inverts it — "X is owned by Y" means source=Y OWNS target=X.\n'
)

OPENAI_URL = "https://api.openai.com/v1/chat/completions"
MODEL = "gpt-5-mini"

# --- corpus ------------------------------------------------------------------

_CO_A = [
    "Veltrax",
    "Norvane",
    "Quillon",
    "Bramwick",
    "Ostrella",
    "Fenmore",
    "Caldrix",
    "Yarrowgate",
    "Peltway",
    "Sundrell",
    "Marchbanks",
    "Tovrik",
    "Elmsworth",
    "Ravelin",
    "Kestwick",
    "Dunmere",
    "Halloway",
    "Zephyrine",
    "Ironcrest",
    "Lumetta",
]
_CO_B = [
    "Industries",
    "Holdings",
    "Group",
    "Partners",
    "Capital",
    "Systems",
    "Logistics",
    "Foods",
    "Energy",
    "Materials",
    "Robotics",
    "Textiles",
    "Marine",
    "Aviation",
    "Pharma",
    "Media",
    "Mining",
    "Rail",
    "Analytics",
    "Packaging",
]
_FIRST = [
    "Mira",
    "Doran",
    "Elsa",
    "Tobias",
    "Priya",
    "Marcus",
    "Ingrid",
    "Felix",
    "Aiko",
    "Ruben",
    "Salome",
    "Viktor",
]
_LAST = [
    "Kestenholz",
    "Abernathy",
    "Duval",
    "Okonkwo",
    "Lindqvist",
    "Marchetti",
    "Havel",
    "Sorenson",
    "Ferreira",
    "Nakagawa",
]

# family -> (active templates, passive templates); {a}=agent, {p}=patient.
_TEMPLATES = {
    "OWNS": (
        ["{a} holds a majority stake in {p}.", "{a} owns a controlling interest in {p}."],
        ["{p} is majority-owned by {a}.", "A controlling interest in {p} is held by {a}."],
    ),
    "ACQUIRED": (
        [
            "{a} acquired {p} in an all-cash deal.",
            "{a} completed its takeover of {p} last quarter.",
        ],
        [
            "{p} was acquired by {a} in an all-cash deal.",
            "{p} was taken over by {a} last quarter.",
        ],
    ),
    "FOUNDED": (
        [
            "{a} founded {p} to enter the regional market.",
            "{a} established {p} as an independent venture.",
        ],
        [
            "{p} was founded by {a} to enter the regional market.",
            "{p} was established by {a} as an independent venture.",
        ],
    ),
    "PARENT_OF": (
        ["{a} is the parent company of {p}.", "{a} operates {p} as one of its divisions."],
        ["{p} is a wholly-owned subsidiary of {a}.", "{p} operates as a division of {a}."],
    ),
}
_PERSON_AGENT = {"FOUNDED"}


def make_corpus(n_docs: int, seed: int) -> list[dict]:
    rng = random.Random(seed)
    companies = [f"{a} {b}" for a in _CO_A for b in _CO_B]
    people = [f"{f} {last}" for f in _FIRST for last in _LAST]
    rng.shuffle(companies)
    rng.shuffle(people)
    co_iter, p_iter = iter(companies), iter(people)

    docs = []
    for d in range(n_docs):
        n_edges = rng.choice([2, 3, 3, 4])
        sentences, gold = [], []
        for _ in range(n_edges):
            family = rng.choice(list(_TEMPLATES))
            agent = next(p_iter) if family in _PERSON_AGENT else next(co_iter)
            patient = next(co_iter)
            voice = rng.choice(["active", "passive"])
            tpl = rng.choice(_TEMPLATES[family][0 if voice == "active" else 1])
            sentences.append(tpl.format(a=agent, p=patient))
            gold.append({"agent": agent, "patient": patient, "family": family, "voice": voice})
        docs.append(
            {
                "doc_id": f"reg-{d}",
                "gold": gold,
                "text": "Corporate registry brief.\n" + " ".join(sentences),
            }
        )
    return docs


# --- extraction --------------------------------------------------------------


def build_prompt(arm: str) -> str:
    if arm == "base":
        assert "must read as a true sentence" not in EXTRACTION_SYSTEM_PROMPT, (
            "installed prompt already carries the direction rule — "
            "run the base arm on main (pre-#118)"
        )
        return EXTRACTION_SYSTEM_PROMPT
    marker = "- Only extract explicit facts from the text"
    assert marker in EXTRACTION_SYSTEM_PROMPT
    return EXTRACTION_SYSTEM_PROMPT.replace(marker, DIRECTION_RULE + marker)


def load_key() -> str:
    for line in (Path(__file__).resolve().parents[3] / ".openai").read_text().splitlines():
        if line.startswith("home_key="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("home_key not found in ../.openai")


async def extract_doc(
    client: httpx.AsyncClient, sem: asyncio.Semaphore, key: str, system_prompt: str, doc: dict
) -> dict:
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": f"Extract entities and relationships from:\n\n{doc['text']}",
            },
        ],
        "response_format": {"type": "json_object"},
    }
    async with sem:
        for attempt in range(3):
            try:
                r = await client.post(
                    OPENAI_URL,
                    json=payload,
                    headers={"Authorization": f"Bearer {key}"},
                    timeout=120,
                )
                r.raise_for_status()
                content = r.json()["choices"][0]["message"]["content"]
                result = _parse_extraction(json.loads(content))
                return {
                    "doc_id": doc["doc_id"],
                    "relationships": [rel.model_dump() for rel in result.relationships],
                }
            except Exception as e:  # noqa: BLE001 - bench: retry then record
                if attempt == 2:
                    return {
                        "doc_id": doc["doc_id"],
                        "relationships": [],
                        "error": f"{type(e).__name__}: {e}",
                    }
                await asyncio.sleep(2**attempt)


# --- scoring -----------------------------------------------------------------

_PASSIVE_SPECIAL = {"SUBSIDIARY_OF", "PART_OF", "BELONGS_TO", "DIVISION_OF"}
_SYMMETRIC = {"RELATED_TO", "ASSOCIATED_WITH", "AFFILIATED_WITH", "CONNECTED_TO"}


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", name.lower()).strip()


def _match(extracted: str, gold: str) -> bool:
    e, g = _norm(extracted), _norm(gold)
    return e == g or (len(e) >= 4 and (e in g or g in e))


def frame(rel_type: str) -> str:
    """'agent' when src should be the gold agent, 'patient' when inverted
    (passive-named types), 'excluded' for symmetric/opaque types."""
    rt = (rel_type or "").upper()
    if rt in _SYMMETRIC:
        return "excluded"
    if rt.endswith("_BY") or rt in _PASSIVE_SPECIAL:
        return "patient"
    return "agent"


def score(docs: list[dict], extractions: list[dict]) -> dict:
    by_doc = {e["doc_id"]: e for e in extractions}
    totals = {
        "gold_pairs": 0,
        "matched_pairs": 0,
        "scored": 0,
        "correct": 0,
        "excluded": 0,
        "errors": 0,
    }
    by_voice = {"active": [0, 0], "passive": [0, 0]}  # [correct, scored]
    misses = []
    for doc in docs:
        ext = by_doc.get(doc["doc_id"], {})
        if ext.get("error"):
            totals["errors"] += 1
        rels = ext.get("relationships", [])
        for g in doc["gold"]:
            totals["gold_pairs"] += 1
            hit = None
            for rel in rels:
                s, t = rel.get("source", ""), rel.get("target", "")
                if (_match(s, g["agent"]) and _match(t, g["patient"])) or (
                    _match(s, g["patient"]) and _match(t, g["agent"])
                ):
                    hit = rel
                    break
            if hit is None:
                continue
            totals["matched_pairs"] += 1
            f = frame(hit.get("rel_type", ""))
            if f == "excluded":
                totals["excluded"] += 1
                continue
            expected_src = g["agent"] if f == "agent" else g["patient"]
            ok = _match(hit.get("source", ""), expected_src)
            totals["scored"] += 1
            totals["correct"] += int(ok)
            by_voice[g["voice"]][1] += 1
            by_voice[g["voice"]][0] += int(ok)
            if not ok:
                misses.append(
                    {
                        "doc": doc["doc_id"],
                        "gold": g,
                        "rel": {
                            k: hit.get(k) for k in ("source", "target", "rel_type", "description")
                        },
                    }
                )
    return {"totals": totals, "by_voice": by_voice, "misses": misses}


# --- main --------------------------------------------------------------------


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", choices=["base", "direction"], required=True)
    ap.add_argument("--docs", type=int, default=60)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--concurrency", type=int, default=8)
    args = ap.parse_args()

    docs = make_corpus(args.docs, args.seed)
    system_prompt = build_prompt(args.arm)
    key = load_key()
    sem = asyncio.Semaphore(args.concurrency)
    t0 = time.time()
    async with httpx.AsyncClient() as client:
        extractions = await asyncio.gather(
            *(extract_doc(client, sem, key, system_prompt, d) for d in docs)
        )
    elapsed = time.time() - t0

    report = score(docs, list(extractions))
    tot, bv = report["totals"], report["by_voice"]
    out = {
        "arm": args.arm,
        "model": MODEL,
        "docs": args.docs,
        "seed": args.seed,
        "elapsed_s": round(elapsed, 1),
        "totals": tot,
        "by_voice": {v: {"correct": c, "scored": s} for v, (c, s) in bv.items()},
        "misses": report["misses"],
        # Raw per-doc extractions + gold, so alternative scorers (e.g. a
        # label-vs-orientation normalizer counterfactual) can re-score
        # offline without another LLM run.
        "corpus": docs,
        "extractions": list(extractions),
    }
    out_path = (
        Path(__file__).parent / f"results-{MODEL}-{args.arm}-seed{args.seed}-n{args.docs}.json"
    )
    out_path.write_text(json.dumps(out, indent=2))

    def pct(c, s):
        return f"{100 * c / s:.1f}%" if s else "n/a"

    print(
        f"\narm={args.arm} model={MODEL} docs={args.docs} seed={args.seed} "
        f"elapsed={elapsed:.0f}s errors={tot['errors']}"
    )
    print(
        f"pair recall      : {tot['matched_pairs']}/{tot['gold_pairs']} "
        f"({pct(tot['matched_pairs'], tot['gold_pairs'])})"
    )
    print(
        f"direction        : {tot['correct']}/{tot['scored']} "
        f"({pct(tot['correct'], tot['scored'])})  excluded={tot['excluded']}"
    )
    for v in ("active", "passive"):
        c, s = bv[v]
        print(f"  {v:<7} voice  : {c}/{s} ({pct(c, s)})")
    print(f"written: {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
