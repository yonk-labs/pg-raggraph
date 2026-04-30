"""Ingest the prepared CRM call notes into pg-raggraph.

Uses gpt-4o-mini for entity extraction. Cost: ~$0.20-0.40 for the
small sample (~650 notes). Runs in ~10-20 min depending on rate.
"""

from __future__ import annotations

import asyncio
import os
import re
import time
from pathlib import Path

from pg_raggraph import GraphRAG

DOCS = Path(__file__).parent / "docs"
DSN = os.environ.get("PGRG_DSN", "postgresql://postgres:postgres@localhost:5434/pg_raggraph")
NAMESPACE = os.environ.get("PGRG_NAMESPACE", "sales_crm_demo")


def parse_metadata_from_doc(text: str) -> dict:
    """Pull `**Key:** value` lines from the markdown frontmatter."""
    md = {}
    for line in text.splitlines():
        m = re.match(r"^\*\*([^:]+):\*\*\s*(.+)$", line)
        if m:
            key = m.group(1).strip().lower().replace(" ", "_")
            md[key] = m.group(2).strip()
        if line.startswith("## Notes"):
            break
    return md


async def main() -> None:
    files = sorted(str(p) for p in DOCS.glob("*.md"))
    print(f"Ingesting {len(files)} call notes into namespace={NAMESPACE}")

    rag = GraphRAG(
        dsn=DSN,
        namespace=NAMESPACE,
        embedding_provider="local",                     # bge-small (default)
        llm_base_url=os.environ.get(
            "LLM_URL", "https://api.openai.com/v1"
        ),
        llm_model=os.environ.get("LLM_MODEL", "gpt-4o-mini"),
        llm_api_key=os.environ.get("OPENAI_API_KEY", ""),
        extraction_prompt="dev",                        # better fit for CRM
        doc_concurrency=4,
        extract_concurrency=8,
    )
    await rag.connect()
    try:
        t0 = time.perf_counter()
        # Per-doc ingest so each carries its own metadata frontmatter.
        for i, f in enumerate(files, 1):
            text = Path(f).read_text()
            md = parse_metadata_from_doc(text)
            await rag.ingest([f], namespace=NAMESPACE, metadata=md)
            if i % 50 == 0 or i == len(files):
                elapsed = time.perf_counter() - t0
                rate = i / max(elapsed, 1e-6)
                eta = (len(files) - i) / max(rate, 1e-6)
                print(
                    f"  {i}/{len(files)} done ({elapsed/60:.1f}min, "
                    f"ETA {eta/60:.1f}min)",
                    flush=True,
                )

        elapsed = time.perf_counter() - t0
        status = await rag.status(NAMESPACE)
        print()
        print("=" * 60)
        print(f"Done in {elapsed/60:.1f} min")
        print(f"  documents:     {status['documents']}")
        print(f"  chunks:        {status['chunks']}")
        print(f"  entities:      {status['entities']}")
        print(f"  relationships: {status['relationships']}")
        print("=" * 60)
    finally:
        await rag.close()


if __name__ == "__main__":
    asyncio.run(main())
