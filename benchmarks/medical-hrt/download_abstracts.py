"""Download PubMed abstracts via NCBI eutils.

Usage:
  uv run python download_abstracts.py --query QUERY --max 15 --out abstracts/{bucket}/

Implements eutils best practices: 3 req/s (no API key), polite User-Agent,
graceful 4xx handling. Writes one .json per PubMed ID with title, abstract,
publication year, publication types, and retraction flag.

Curation is a separate step (see manifest.yaml).
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

import httpx

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
USER_AGENT = "pgrg-benchmark/1.0 (matt@theyonk.com)"
RATE_DELAY = 0.34  # ~3 req/s


def esearch(client: httpx.Client, term: str, retmax: int) -> list[str]:
    r = client.get(
        f"{EUTILS}/esearch.fcgi",
        params={"db": "pubmed", "term": term, "retmax": retmax, "retmode": "json"},
    )
    r.raise_for_status()
    return r.json()["esearchresult"]["idlist"]


def efetch(client: httpx.Client, pmid: str) -> dict[str, Any]:
    r = client.get(
        f"{EUTILS}/efetch.fcgi",
        params={"db": "pubmed", "id": pmid, "retmode": "xml"},
    )
    r.raise_for_status()
    root = ET.fromstring(r.text)
    article = root.find(".//Article")
    title = (article.findtext("ArticleTitle") or "").strip() if article is not None else ""
    abstract_parts = article.findall(".//AbstractText") if article is not None else []
    abstract = " ".join((e.text or "") for e in abstract_parts).strip()
    pub_year_text = root.findtext(".//PubDate/Year") or ""
    pub_types = [(e.text or "") for e in root.findall(".//PublicationType")]
    retracted = any("Retract" in t for t in pub_types)
    return {
        "pmid": pmid,
        "title": title,
        "abstract": abstract,
        "pub_year": int(pub_year_text) if pub_year_text.isdigit() else None,
        "pub_types": pub_types,
        "retracted": retracted,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--query", required=True, help="PubMed search expression")
    ap.add_argument("--max", type=int, default=15)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=30.0) as client:
        ids = esearch(client, args.query, args.max)
        print(f"  found {len(ids)} pmids")
        n_fetched = 0
        for pmid in ids:
            target = args.out / f"{pmid}.json"
            if target.exists():
                print(f"  = {pmid} (cached)")
                continue
            time.sleep(RATE_DELAY)
            try:
                doc = efetch(client, pmid)
            except httpx.HTTPStatusError as e:
                print(f"  ! {pmid}: HTTP {e.response.status_code}")
                continue
            target.write_text(json.dumps(doc, indent=2))
            print(f"  + {pmid}: {doc['title'][:70]}")
            n_fetched += 1
        print(f"fetched {n_fetched} new files into {args.out}")


if __name__ == "__main__":
    main()
