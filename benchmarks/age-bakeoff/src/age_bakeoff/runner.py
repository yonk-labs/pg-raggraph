"""Benchmark harness -- runs all questions across all engines, records JSON."""
from __future__ import annotations

import json
import logging
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
        results: list[RunResult] = []
        for q in qset.questions:
            for run_number in range(1, self.options.runs_per_question + 1):
                cold = run_number == 1
                for name, engine in self.engines.items():
                    try:
                        retrieval = await engine.retrieve(q.question)
                        answer, answer_ms = await engine.generate_answer(
                            q.question,
                            retrieval.retrieved_chunk_contents,
                            tracker=self._tracker,
                        )
                        results.append(
                            RunResult(
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
                        )
                    except CostBudgetExceeded:
                        # Hard cap: write partial results and propagate so the
                        # CLI's finally-block can persist the cost tally.
                        out = self.options.output_dir / f"{corpus}.json"
                        out.write_text(
                            json.dumps(
                                [r.model_dump() for r in results],
                                indent=2,
                                sort_keys=True,
                            )
                        )
                        raise
                    except Exception as exc:
                        logger.exception(
                            "Run failed q=%s engine=%s", q.id, name
                        )
                        results.append(
                            RunResult(
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
                        )
        out = self.options.output_dir / f"{corpus}.json"
        out.write_text(
            json.dumps(
                [r.model_dump() for r in results], indent=2, sort_keys=True
            )
        )
        return results
