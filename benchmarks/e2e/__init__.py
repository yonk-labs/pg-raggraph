"""E2E benchmark harness for pg-raggraph.

Runs the retrieval ladder against multi-hop QA corpora (MultiHop-RAG,
MuSiQue, 2WikiMultiHopQA) and emits accuracy + performance metrics.

Entry point: ``python -m benchmarks.e2e.run --dataset all``.

Design: ``docs/superpowers/specs/2026-05-20-e2e-benchmark-harness-design.md``.
"""
