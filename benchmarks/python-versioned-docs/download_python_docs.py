"""Download selected Python docs pages for 3.10, 3.11, 3.12.

Saves as `pages/{version}/{slug}.html`. Idempotent — skips files that
already exist on disk. No network call when re-run.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).parent
OUT_DIR = ROOT / "pages"
USER_AGENT = "pgrg-benchmark/1.0 (https://github.com/the-yonk/pg-raggraph)"

VERSIONS = ["3.10", "3.11", "3.12"]
COMMON_SLUGS = ["library/enum", "library/typing", "reference/datamodel"]
WHATSNEW = {v: f"whatsnew/{v}" for v in VERSIONS}


def url(version: str, slug: str) -> str:
    return f"https://docs.python.org/{version}/{slug}.html"


def fetch(client: httpx.Client, target: Path, version: str, slug: str) -> bool:
    if target.exists():
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    r = client.get(url(version, slug), timeout=30.0)
    r.raise_for_status()
    target.write_bytes(r.content)
    return True


def main() -> None:
    OUT_DIR.mkdir(exist_ok=True)
    n_fetched = 0
    with httpx.Client(headers={"User-Agent": USER_AGENT}) as client:
        for version in VERSIONS:
            for slug in COMMON_SLUGS + [WHATSNEW[version]]:
                target = OUT_DIR / version / f"{slug.replace('/', '__')}.html"
                if fetch(client, target, version, slug):
                    print(f"  + {target.relative_to(ROOT)}")
                    n_fetched += 1
                    time.sleep(0.5)  # be polite
                else:
                    print(f"  = {target.relative_to(ROOT)} (cached)")
    print(f"fetched {n_fetched} new files into {OUT_DIR}")


if __name__ == "__main__":
    sys.exit(main())
