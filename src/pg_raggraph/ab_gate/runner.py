"""A/B Gate matrix runner — #49.

One entry point: ``run_ab_matrix(rag, corpora, modes, gold_questions_per_corpus,
output_dir, top_k)`` orchestrates ``len(corpora) × len(modes)`` calls to
``run_harness_mode`` and returns a dict mapping each ``(corpus_id, mode)``
pair to the output JSON file written.

File naming: ``<output_dir>/<corpus_id>__<mode>.json`` (double-underscore
intentional — avoids ambiguity when corpus names contain single underscores).
Plus ``<output_dir>/manifest.json`` listing every file + run timestamps +
``pg_raggraph.__version__`` for traceability.
"""

from __future__ import annotations

import dataclasses
import json
import logging
from datetime import datetime, timezone
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


def _output_to_dict(output: ABRunnerOutput) -> dict:
    """Convert an ABRunnerOutput into a JSON-serializable dict.

    Uses dataclasses.asdict for nested coverage; required_facts (tuple
    list) becomes a list-of-lists, which is round-tripped to tuples by
    the parse helper in tests/integration/test_ab_runner_writes_per_corpus_per_mode.py.
    """
    return dataclasses.asdict(output)


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

    Sequential per cell. Writes one ABRunnerOutput JSON per cell at
    ``<output_dir>/<corpus_id>__<mode>.json`` plus a ``manifest.json``
    listing every file with run timestamps and ``pg_raggraph.__version__``
    for traceability.
    """
    import pg_raggraph

    output_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[tuple[str, str], Path] = {}
    entries: list[dict] = []
    started = datetime.now(timezone.utc).isoformat()
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
            # Atomic-ish: write to a temp neighbor, then os.replace. Keeps
            # SC-019's "no partial-write state" guarantee even if the
            # process dies mid-write.
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(_output_to_dict(output), indent=2, sort_keys=True))
            tmp.replace(path)
            paths[(corpus_id, mode)] = path
            entries.append(
                {
                    "corpus": corpus_id,
                    "mode": mode,
                    "path": path.name,
                    "question_count": len(output.results),
                }
            )
    ended = datetime.now(timezone.utc).isoformat()
    manifest = {
        "run_started_at": started,
        "run_ended_at": ended,
        "pg_raggraph_version": pg_raggraph.__version__,
        "files": entries,
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))
    return paths
