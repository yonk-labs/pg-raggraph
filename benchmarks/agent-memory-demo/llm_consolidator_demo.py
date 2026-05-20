"""Demo consolidator that emits typed SPO triples — the LLM-wired path.

chunkshop's ``configs/memory/consolidate.yaml`` accepts any module +
function via the ``consolidator:`` callable mode. The default
``chunkshop.consolidators.extractive`` emits sparse triples (subject /
predicate / object all None) — useful for zero-network deployments
but the bridge skips them at the graph-edge step (the chunks land,
but no ``relationships`` row gets written).

This module shows the LLM-wired path. The function signature is the
chunkshop consolidator contract:

    consolidate(text: str, **kw) -> {
        "summary": str,
        "facts": list[{
            "subject": str | None,
            "predicate": str | None,
            "object": str | None,
            "support_span": str,
            "confidence": float | None,
        }]
    }

Two implementations:

1. ``DETERMINISTIC_FAKE_LLM`` — pure-Python stub that returns
   well-formed SPO triples for a fixed test corpus. Used by the
   smoke test in this directory to validate the bridge handles
   non-sparse fact rows end-to-end. Has no network dependency, so
   it works in CI.

2. ``OPENAI_LLM_CONSOLIDATOR`` — reference for a real LLM. Calls
   the OpenAI Chat Completions API with a structured-output prompt
   asking the model to extract SPO triples from the input text.
   Requires ``OPENAI_API_KEY``. Comment-only by default to avoid
   pulling openai as a runtime dep.

Use one or the other in your chunkshop YAML:

    consolidator:
      mode: callable
      module: benchmarks.agent_memory_demo.llm_consolidator_demo
      function: consolidate              # routes to the deterministic stub

OR for a real LLM, uncomment the OpenAI block below and point at
``openai_consolidate`` instead.
"""

from __future__ import annotations

import re
from typing import Any

# ---------------------------------------------------------------------------
# Deterministic stub — used by the smoke test to validate the bridge handles
# non-sparse SPO triples end-to-end. Pattern-matches on the session content
# pg-raggraph's smoke fixtures produce.
# ---------------------------------------------------------------------------


_FACT_PATTERNS: list[tuple[re.Pattern[str], dict[str, str]]] = [
    (
        re.compile(r"pool[_ ]?max[_ ]?size.*?(\d+)\s*x\s*cpu", re.IGNORECASE),
        {
            "subject": "postgres_pool_size",
            "predicate": "recommended_setting",
            "object": "2x_cpu_cores",
        },
    ),
    (
        re.compile(r"pgbouncer.*?transaction[- ]?pooling", re.IGNORECASE),
        {
            "subject": "pgbouncer",
            "predicate": "recommended_mode",
            "object": "transaction_pooling",
        },
    ),
    (
        re.compile(r"replication\s+(?:catches up|lag).*?(\d+)\s*ms", re.IGNORECASE),
        {
            "subject": "logical_replication",
            "predicate": "typical_lag",
            "object": "under_100ms",
        },
    ),
    (
        re.compile(r"read\s+queries.*?(?:standby|replica)", re.IGNORECASE),
        {
            "subject": "read_queries",
            "predicate": "should_route_to",
            "object": "standby_replicas",
        },
    ),
]


def consolidate(text: str, **_kw: Any) -> dict[str, Any]:
    """Deterministic SPO extractor — returns typed triples from a
    fixed-pattern corpus.

    Matches the chunkshop consolidator contract. Used by the Pattern M
    smoke test to validate that pg-raggraph's bridge correctly turns
    typed SPO triples into graph relationships (when the extractive
    default would skip them).
    """
    if not text or not text.strip():
        return {"summary": "", "facts": []}

    facts: list[dict[str, Any]] = []
    for pattern, triple in _FACT_PATTERNS:
        m = pattern.search(text)
        if m:
            facts.append(
                {
                    **triple,
                    "support_span": text[
                        max(0, m.start() - 20) : min(len(text), m.end() + 80)
                    ].strip(),
                    "confidence": 0.95,
                }
            )

    # Summary: first ~200 chars, sentence-aware.
    sents = re.split(r"(?<=[.!?])\s+", text.strip())
    summary = " ".join(sents[:2])[:200]

    return {"summary": summary, "facts": facts}


# ---------------------------------------------------------------------------
# Reference: OpenAI-wired consolidator. Uncomment to use.
# ---------------------------------------------------------------------------

# import os
# from openai import OpenAI
#
# _CLIENT = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
#
# _SYSTEM_PROMPT = """You are an information-extraction system.
# Given a conversation transcript, extract atomic facts as
# subject-predicate-object triples plus a one-paragraph summary.
#
# Output strict JSON matching this schema:
# {
#   "summary": "<one paragraph summarizing the conversation>",
#   "facts": [
#     {
#       "subject": "<noun phrase>",
#       "predicate": "<verb or relation>",
#       "object": "<noun phrase>",
#       "support_span": "<exact span from the input that supports this fact>",
#       "confidence": <float 0.0-1.0>
#     },
#     ...
#   ]
# }
#
# Facts must be atomic and verifiable against support_span. Drop fuzzy
# inferences. Prefer fewer high-confidence facts over many low-confidence ones."""
#
# def openai_consolidate(text: str, **_kw: Any) -> dict[str, Any]:
#     resp = _CLIENT.chat.completions.create(
#         model="gpt-4o-mini",
#         messages=[
#             {"role": "system", "content": _SYSTEM_PROMPT},
#             {"role": "user", "content": text},
#         ],
#         response_format={"type": "json_object"},
#         temperature=0,
#     )
#     return json.loads(resp.choices[0].message.content)


__all__ = ["consolidate"]
