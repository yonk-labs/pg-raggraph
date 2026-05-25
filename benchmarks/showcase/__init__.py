"""Showcase sweep: summary-vs-chunks RAG comparison on 3rd-party benchmarks.

Measures token reduction, LLM call count, answer accuracy, and latency across
arms (raw chunks → LLM, lede summary → LLM, summary-only no-LLM) and knob combos
(retrieval expansion off/on, keep_headings off/on) against the loaded MHR /
MuSiQue / 2Wiki bench data (Postgres only).
"""
