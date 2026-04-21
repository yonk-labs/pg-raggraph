"""Benchmark harness -- runs all questions across all engines, records JSON."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

from age_bakeoff.config import BakeoffConfig
from age_bakeoff.cost import CostBudgetExceeded, CostTracker
from age_bakeoff.engines.base import Engine
from age_bakeoff.models import ExtractionOutput, RunResult
from age_bakeoff.questions.schema import QuestionSet, _LooseQuestionSet

logger = logging.getLogger(__name__)


@dataclass
class RunnerOptions:
    runs_per_question: int = 3
    output_dir: Path = field(default_factory=lambda: Path("results/raw"))
    label: str | None = None
    # Per-query timeout so a hung retrieval/answer doesn't block the whole run.
    # Smart mode on SCOTUS hung for 70+ min in Phase 2 without this.
    query_timeout_sec: float = 120.0
    # Incremental write cadence — how often to flush results to disk. Every N
    # (question, run) tuples written so a crash/kill doesn't lose everything.
    # Set via env BAKEOFF_FLUSH_EVERY or default 5.
    flush_every: int = 5
    # Log per-question progress so silence is distinguishable from "stuck".
    # Emits "q=X/Y engine=Z elapsed=...s cost=$..." every question.
    progress_log: bool = True


class Runner:
    def __init__(
        self,
        config: BakeoffConfig,
        engines: dict[str, Engine],
        options: RunnerOptions,
        tracker: CostTracker | None = None,
    ):
        self.config = config
        self.engines = engines
        self.options = options
        self._tracker = tracker
        self.options.output_dir.mkdir(parents=True, exist_ok=True)

    def verify_symmetry(self) -> None:
        infos = [eng.info() for eng in self.engines.values()]
        if len(infos) < 2:
            return
        ref = infos[0]
        for other in infos[1:]:
            if other.embedding_model != ref.embedding_model:
                raise RuntimeError(
                    f"Embedding model mismatch: {ref.embedding_model} vs {other.embedding_model}"
                )
            if other.answer_model != ref.answer_model:
                raise RuntimeError(
                    f"Answer model mismatch: {ref.answer_model} vs {other.answer_model}"
                )
            if other.top_k != ref.top_k:
                raise RuntimeError(
                    f"top_k mismatch: {ref.top_k} vs {other.top_k}"
                )

    async def ingest(self, extractions: dict[str, ExtractionOutput]) -> None:
        self.verify_symmetry()
        for corpus, extraction in extractions.items():
            for name, engine in self.engines.items():
                logger.info(
                    "Ingesting corpus=%s into engine=%s", corpus, name
                )
                await engine.ingest(extraction)

    async def ingest_corpus(self, corpus: str, extraction: ExtractionOutput) -> None:
        """Ingest a single corpus into all engines (wipes previous data)."""
        self.verify_symmetry()
        for name, engine in self.engines.items():
            logger.info("Ingesting corpus=%s into engine=%s", corpus, name)
            await engine.ingest(extraction)

    async def run_corpus(
        self, corpus: str, qset: QuestionSet | _LooseQuestionSet,
        extraction: ExtractionOutput | None = None,
    ) -> list[RunResult]:
        if extraction:
            await self.ingest_corpus(corpus, extraction)
        # Labelled filenames keep per-mode / per-signal runs from clobbering the
        # baseline. Omitting --label preserves the pre-Task-2.1 filename so
        # existing REPORT pipelines still find {corpus}.json.
        suffix = f"__{self.options.label}" if self.options.label else ""
        out = self.options.output_dir / f"{corpus}{suffix}.json"
        results: list[RunResult] = []

        total_q = len(qset.questions)
        total_jobs = total_q * self.options.runs_per_question * len(self.engines)
        t0 = time.time()
        job_count = 0
        last_flush = 0

        def _flush() -> None:
            """Write results to disk. Called every flush_every jobs + on exit."""
            try:
                out.write_text(
                    json.dumps(
                        [r.model_dump() for r in results],
                        indent=2,
                        sort_keys=True,
                    )
                )
            except BrokenPipeError:
                # stdout pipe closed; don't let it cascade into the run.
                pass
            except OSError as e:
                logger.warning("flush failed: %s", e)

        def _progress(qi: int, total: int, engine_name: str, latency_ms: float, err: str | None) -> None:
            """One-line per-question progress. Designed to survive broken pipes."""
            if not self.options.progress_log:
                return
            elapsed = time.time() - t0
            rate = job_count / elapsed if elapsed > 0 else 0
            remaining = (total_jobs - job_count) / rate if rate > 0 else 0
            cost = self._tracker.total_usd if self._tracker is not None else 0.0
            tag = f"ERR({err[:40]})" if err else f"{latency_ms:.0f}ms"
            msg = (
                f"[{job_count}/{total_jobs}] q={qi+1}/{total} "
                f"engine={engine_name:8s} {tag} "
                f"elapsed={elapsed:.0f}s eta={remaining:.0f}s "
                f"cost=${cost:.3f}"
            )
            try:
                print(msg, flush=True)
            except BrokenPipeError:
                # Downstream pipe closed (e.g. | head -N). Keep going silently.
                pass
            logger.info(msg)

        async def _one_job(
            name: str,
            engine: Engine,
            q,
            run_number: int,
            cold: bool,
            qi: int,
        ) -> RunResult:
            """Run one (engine, question, run) triple; return a RunResult."""
            start = time.time()
            try:
                retrieval = await asyncio.wait_for(
                    engine.retrieve(q.question),
                    timeout=self.options.query_timeout_sec,
                )
                answer, answer_ms = await asyncio.wait_for(
                    engine.generate_answer(
                        q.question,
                        retrieval.retrieved_chunk_contents,
                        tracker=self._tracker,
                    ),
                    timeout=self.options.query_timeout_sec,
                )
                latency = (time.time() - start) * 1000
                _progress(qi, total_q, name, latency, None)
                return RunResult(
                    engine=name,
                    corpus=corpus,
                    question_id=q.id,
                    run_number=run_number,
                    cold=cold,
                    retrieval_ms=retrieval.retrieval_ms,
                    answer_ms=answer_ms,
                    retrieved_chunk_ids=retrieval.retrieved_chunk_ids,
                    retrieved_chunk_contents=retrieval.retrieved_chunk_contents,
                    generated_answer=answer,
                )
            except CostBudgetExceeded:
                raise
            except asyncio.TimeoutError:
                _progress(qi, total_q, name, -1, "timeout")
                logger.exception(
                    "Run timed out q=%s engine=%s after %ss",
                    q.id,
                    name,
                    self.options.query_timeout_sec,
                )
                return RunResult(
                    engine=name,
                    corpus=corpus,
                    question_id=q.id,
                    run_number=run_number,
                    cold=cold,
                    retrieval_ms=-1.0,
                    answer_ms=-1.0,
                    retrieved_chunk_ids=[],
                    generated_answer="",
                    error=f"timeout after {self.options.query_timeout_sec}s",
                )
            except Exception as exc:
                _progress(qi, total_q, name, -1, str(exc))
                logger.exception("Run failed q=%s engine=%s", q.id, name)
                return RunResult(
                    engine=name,
                    corpus=corpus,
                    question_id=q.id,
                    run_number=run_number,
                    cold=cold,
                    retrieval_ms=-1.0,
                    answer_ms=-1.0,
                    retrieved_chunk_ids=[],
                    generated_answer="",
                    error=str(exc),
                )

        for qi, q in enumerate(qset.questions):
            for run_number in range(1, self.options.runs_per_question + 1):
                cold = run_number == 1
                # Engines run concurrently per (q, run) — cuts wall time in half
                # for the 2-engine head-to-head and scales to 3+ engines cleanly.
                try:
                    engine_results = await asyncio.gather(
                        *[
                            _one_job(name, eng, q, run_number, cold, qi)
                            for name, eng in self.engines.items()
                        ],
                        return_exceptions=False,
                    )
                except CostBudgetExceeded:
                    _flush()
                    raise
                results.extend(engine_results)
                job_count += len(engine_results)

                # Incremental flush so kill/crash doesn't lose everything
                if job_count - last_flush >= self.options.flush_every:
                    _flush()
                    last_flush = job_count

        _flush()
        return results
