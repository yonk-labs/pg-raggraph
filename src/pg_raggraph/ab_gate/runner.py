"""A/B Gate matrix runner — #49.

One entry point: ``run_ab_matrix(rag, corpora, modes, gold_questions_per_corpus,
output_dir, top_k)`` orchestrates ``len(corpora) × len(modes)`` calls to
``run_harness_mode`` and returns a dict mapping each ``(corpus_id, mode)``
pair to the output JSON file written.

File naming: ``<output_dir>/<corpus_id>__<mode>.json`` (double-underscore
intentional — avoids ambiguity when corpus names contain single underscores).
Plus ``<output_dir>/manifest.json`` listing every file + run timestamps +
``pg_raggraph.__version__`` for traceability.

This task lands the orchestration skeleton; Task 8 adds file I/O.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pg_raggraph.ab_gate.harness import run_harness_mode
from pg_raggraph.ab_gate.io import ABRunnerOutput, GoldQuestion

if TYPE_CHECKING:
    from pg_raggraph import GraphRAG

logger = logging.getLogger("pg_raggraph.ab_gate.runner")

Mode = Literal["naive_vector", "graph_leg", "hybrid"]


def _output_path(output_dir: Path, corpus_id: str, mode: str) -> Path:
    """``<output_dir>/<corpus_id>__<mode>.json``. DC-004 enforces the double-underscore."""
    return output_dir / f"{corpus_id}__{mode}.json"


async def run_ab_matrix(
    rag: "GraphRAG",
    *,
    corpora: list[str],
    modes: list[Mode],
    gold_questions_per_corpus: dict[str, list[GoldQuestion]],
    output_dir: Path,
    top_k: int = 10,
) -> dict[tuple[str, str], Path]:
    """Run the {corpora × modes} A/B matrix.

    Sequential per cell — no per-(corpus, mode) parallelism (locked in
    brief's Out of Scope). Per-question parallelism inside a mode is
    delegated to the harness, which today is also sequential.

    Returns a dict mapping ``(corpus_id, mode) → Path`` so callers
    (#50's verdict computer) can find each output file.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[tuple[str, str], Path] = {}
    for corpus_id in corpora:
        gold = gold_questions_per_corpus.get(corpus_id)
        if not gold:
            logger.warning(
                "no gold questions for corpus %r; skipping all modes for this corpus",
                corpus_id,
            )
            continue
        for mode in modes:
            logger.info("running (%s, %s)", corpus_id, mode)
            output: ABRunnerOutput = await run_harness_mode(
                rag,
                corpus_id=corpus_id,
                mode=mode,
                gold_questions=gold,
                top_k=top_k,
            )
            path = _output_path(output_dir, corpus_id, mode)
            paths[(corpus_id, mode)] = path
            # File I/O lands in Task 8.
            _ = output
    return paths
