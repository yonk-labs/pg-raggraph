"""Run sample queries against the ingested CRM namespace.

Used to capture realistic example outputs for the cookbook.
"""

from __future__ import annotations

import asyncio
import os

from pg_raggraph import GraphRAG

DSN = os.environ.get("PGRG_DSN", "postgresql://postgres:postgres@localhost:5434/pg_raggraph")
NAMESPACE = os.environ.get("PGRG_NAMESPACE", "sales_crm_demo_small")

QUESTIONS = [
    "What objections came up most often in our closed-won deals?",
    "What customers bought ClarityDB Guardian and what was their main pain point?",
    "Which products were mentioned alongside competitor products?",
    "What's the most common reason we win deals?",
    "Which industries had the most won deals?",
]


async def main():
    rag = GraphRAG(
        dsn=DSN,
        namespace=NAMESPACE,
        llm_base_url="https://api.openai.com/v1",
        llm_model="gpt-4o-mini",
        llm_api_key=os.environ.get("OPENAI_API_KEY", ""),
    )
    await rag.connect()
    try:
        for i, q in enumerate(QUESTIONS, 1):
            print(f"\n{'=' * 70}")
            print(f"Q{i}: {q}")
            print("=" * 70)
            result = await rag.ask(q, mode="smart", namespace=NAMESPACE)
            print(f"\n{result.answer}")
            print(
                f"\n[mode={result.query_mode} chunks={len(result.chunks)} "
                f"latency={result.latency_ms:.0f}ms]"
            )
    finally:
        await rag.close()


if __name__ == "__main__":
    asyncio.run(main())
