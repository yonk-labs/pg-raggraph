"""Ingest the Python docs corpus into pgrg with version_label metadata.

Strips HTML to plain text via beautifulsoup4. Each version's pages go in
under the same namespace, distinguished only by metadata.version_label.

Re-runs are idempotent: the (namespace, content_hash) UNIQUE constraint on
documents skips already-ingested docs.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

from bs4 import BeautifulSoup

from pg_raggraph import GraphRAG

ROOT = Path(__file__).parent
PAGES = ROOT / "pages"
NAMESPACE = "python_docs"
DSN = os.environ.get(
    "PGRG_DSN", "postgresql://postgres:postgres@localhost:5434/pg_raggraph"
)


def html_to_text(p: Path) -> str:
    soup = BeautifulSoup(p.read_text(), "html.parser")
    for tag in soup(["script", "style", "nav", "footer"]):
        tag.decompose()
    return soup.get_text("\n", strip=True)


async def main() -> None:
    rag = GraphRAG(dsn=DSN, namespace=NAMESPACE, evolution_tier="structural")
    await rag.connect()
    try:
        for version in sorted(p.name for p in PAGES.iterdir() if p.is_dir()):
            label = f"Python {version}"
            for html_file in sorted((PAGES / version).glob("*.html")):
                txt = html_to_text(html_file)
                tmp = ROOT / "_tmp" / f"{version}__{html_file.stem}.md"
                tmp.parent.mkdir(parents=True, exist_ok=True)
                tmp.write_text(f"# {html_file.stem} ({label})\n\n{txt}")
                await rag.ingest(
                    [str(tmp)],
                    namespace=NAMESPACE,
                    metadata={"version_label": label},
                )
                print(f"  + {label}: {html_file.name}")
    finally:
        await rag.close()


if __name__ == "__main__":
    asyncio.run(main())
