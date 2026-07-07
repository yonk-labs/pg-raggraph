#!/usr/bin/env python3
"""Download the CAP gold v1 corpus: wash-2d volumes 1-120 from static.case.law.

Selection rule is preregistered in METHODOLOGY.md §1: reporter wash-2d,
volumes 1-120 inclusive, every case with a non-empty lead opinion. Writes:

  data/volumes/<v>.zip     raw CAP volume archives (kept for provenance)
  data/corpus.jsonl        one line per case: id, name, name_abbreviation,
                           court_id, decision_date, official_cite, text,
                           opinion_len, cites_in_corpus, entity_name
  data/manifest.json       volume shas + corpus counts

Case text = name + opinions[0].text[:8000] — Microsoft's embedding-input
shape, unchanged from the h2h. No bulk data is committed (data/ gitignored).

Usage:
    uv run --no-sync python benchmarks/age-bakeoff/cap-gold-v1/download_corpus.py
"""

from __future__ import annotations

import hashlib
import io
import json
import time
import urllib.request
import zipfile
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
VOLS = DATA / "volumes"

REPORTER = "wash-2d"
VOLUMES = list(range(1, 121))  # preregistered: 1-120 inclusive
BASE = f"https://static.case.law/{REPORTER}"
EMBED_CHAR_LIMIT = 8000  # Microsoft: name || LEFT(opinion, 8000)


def fetch_volume(v: int) -> Path:
    dest = VOLS / f"{v}.zip"
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    url = f"{BASE}/{v}.zip"
    # static.case.law 403s the default Python urllib UA; any browser-ish UA works
    req = urllib.request.Request(url, headers={"User-Agent": "cap-gold-v1-benchmark/1.0"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                dest.write_bytes(r.read())
            return dest
        except Exception as e:  # noqa: BLE001
            if attempt == 2:
                raise
            print(f"  vol {v}: retry after {type(e).__name__}: {e}")
            time.sleep(3 * (attempt + 1))
    raise AssertionError("unreachable")


def main() -> None:
    DATA.mkdir(exist_ok=True)
    VOLS.mkdir(exist_ok=True)

    cases: dict[str, dict] = {}
    vol_shas: dict[str, str] = {}
    n_skipped_no_opinion = 0
    t0 = time.time()

    for v in VOLUMES:
        zp = fetch_volume(v)
        vol_shas[str(v)] = hashlib.sha256(zp.read_bytes()).hexdigest()
        with zipfile.ZipFile(io.BytesIO(zp.read_bytes())) as zf:
            names = [n for n in zf.namelist() if n.startswith("json/") and n.endswith(".json")]
            for n in sorted(names):
                c = json.loads(zf.read(n))
                cid = str(c["id"])
                opinions = (c.get("casebody") or {}).get("opinions") or []
                opinion = opinions[0].get("text") or "" if opinions else ""
                if not opinion.strip():
                    n_skipped_no_opinion += 1
                    continue
                official = ""
                for cite in c.get("citations") or []:
                    if cite.get("type") == "official":
                        official = cite.get("cite") or ""
                        break
                cited: list[str] = []
                for ct in c.get("cites_to") or []:
                    cited.extend(str(x) for x in ct.get("case_ids") or [])
                if cid in cases:
                    # same case id appearing twice (shouldn't happen) — keep first
                    continue
                cases[cid] = {
                    "id": cid,
                    "name": c.get("name") or "",
                    "name_abbreviation": c.get("name_abbreviation") or "",
                    "court_id": ((c.get("court") or {}).get("id")),
                    "decision_date": c.get("decision_date") or "",
                    "official_cite": official,
                    "volume": v,
                    "opinion_len": len(opinion),
                    "opinion_tail": opinion[8000:12000],  # question source (§2.2 E2)
                    "text": (c.get("name") or "") + opinion[:EMBED_CHAR_LIMIT],
                    "cites_raw": cited,
                }
        print(f"vol {v}: cumulative {len(cases)} cases ({time.time() - t0:.0f}s)")

    ids = set(cases)
    n_edges = 0
    for c in cases.values():
        in_corpus = sorted({x for x in c.pop("cites_raw") if x in ids and x != c["id"]})
        c["cites_in_corpus"] = in_corpus
        n_edges += len(in_corpus)

    # entity naming: duplicates get an " (id)" suffix (h2h convention;
    # METHODOLOGY §5 — the numeric version guard then refuses cross-case merges)
    dupes = {
        n for n, k in Counter(c["name_abbreviation"] for c in cases.values()).items() if k > 1
    }
    for c in cases.values():
        base = c["name_abbreviation"] or f"case-{c['id']}"
        c["entity_name"] = f"{base} ({c['id']})" if base in dupes else base

    with open(DATA / "corpus.jsonl", "w") as f:
        for cid in sorted(cases, key=int):
            f.write(json.dumps(cases[cid]) + "\n")

    manifest = {
        "source": f"https://static.case.law/{REPORTER}/ (Caselaw Access Project, public domain)",
        "reporter": REPORTER,
        "volumes": f"{VOLUMES[0]}-{VOLUMES[-1]}",
        "volume_sha256": vol_shas,
        "n_cases": len(cases),
        "n_skipped_no_opinion": n_skipped_no_opinion,
        "n_citation_edges_in_corpus": n_edges,
        "n_duplicate_captions": len(dupes),
        "courts": dict(Counter(str(c["court_id"]) for c in cases.values())),
        "embed_model": "BAAI/bge-small-en-v1.5",
        "embed_dim": 384,
        "embed_input": f"name || opinion_0[:{EMBED_CHAR_LIMIT}]",
    }
    with open(DATA / "manifest.json", "w") as f:
        json.dump(manifest, f, indent=2)
    print(json.dumps({k: v for k, v in manifest.items() if k != "volume_sha256"}, indent=2))


if __name__ == "__main__":
    main()
