"""CLI for the AGE vs pg-raggraph bake-off benchmark."""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

import click

from age_bakeoff.config import BakeoffConfig
from age_bakeoff.cost import CostTracker

logger = logging.getLogger("age_bakeoff")

_QUESTIONS_DIR = Path(__file__).resolve().parents[2] / "questions"
_RESULTS_DIR = Path(__file__).resolve().parents[2] / "results"


def _get_config() -> BakeoffConfig:
    return BakeoffConfig()


def _get_engines(cfg: BakeoffConfig) -> dict:
    from age_bakeoff.engines.age import AgeEngine
    from age_bakeoff.engines.pgrg import PgrgEngine

    return {
        "pgrg": PgrgEngine(
            dsn=cfg.pgrg_dsn,
            top_k=cfg.top_k,
            hop_budget=cfg.hop_budget,
            answer_model=cfg.answer_model,
            embedding_model=cfg.embedding_model,
        ),
        "age": AgeEngine(
            dsn=cfg.age_dsn,
            top_k=cfg.top_k,
            hop_budget=cfg.hop_budget,
            answer_model=cfg.answer_model,
            embedding_model=cfg.embedding_model,
        ),
    }


def _load_corpora() -> dict:
    from age_bakeoff.corpora.acme import AcmeCorpus
    from age_bakeoff.corpora.scotus import ScotusCorpus

    corpora = {
        "acme": AcmeCorpus(),
        "scotus": ScotusCorpus(),
    }
    # pg-src is optional (requires extraction cache)
    try:
        from age_bakeoff.corpora.pg_src import PgSrcCorpus

        pg = PgSrcCorpus()
        pg.load()  # test that cache exists
        corpora["pg-src"] = pg
    except FileNotFoundError:
        logger.warning(
            "pg-src extraction cache not found, skipping pg-src corpus"
        )
    return corpora


@click.group()
@click.option(
    "--verbose", "-v", is_flag=True, help="Enable verbose logging"
)
def cli(verbose: bool) -> None:
    """AGE vs pg-raggraph bake-off benchmark."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )


@cli.command()
@click.option(
    "--corpus",
    "-c",
    multiple=True,
    help="Corpus to ingest (default: all available)",
)
def ingest(corpus: tuple[str, ...]) -> None:
    """Ingest corpora into both engines."""
    cfg = _get_config()
    engines = _get_engines(cfg)
    corpora = _load_corpora()

    if corpus:
        corpora = {k: v for k, v in corpora.items() if k in corpus}

    async def _run():
        from age_bakeoff.runner import Runner, RunnerOptions

        runner = Runner(
            config=cfg,
            engines=engines,
            options=RunnerOptions(output_dir=_RESULTS_DIR / "raw"),
        )
        extractions = {
            name: c.load() for name, c in corpora.items()
        }
        await runner.ingest(extractions)
        click.echo(
            f"Ingested {len(extractions)} corpora into {len(engines)} engines"
        )

    asyncio.run(_run())


@cli.command()
@click.option(
    "--corpus",
    "-c",
    multiple=True,
    help="Corpus to run (default: all available)",
)
@click.option(
    "--runs", "-n", default=3, help="Runs per question (default: 3)"
)
@click.option(
    "--budget-usd",
    default=50.0,
    type=float,
    help="Hard cap on OpenAI spend (default: $50)",
)
def run(corpus: tuple[str, ...], runs: int, budget_usd: float) -> None:
    """Run benchmark questions against both engines."""
    tracker = CostTracker(budget_usd=budget_usd)

    cfg = _get_config()
    engines = _get_engines(cfg)

    from age_bakeoff.questions.schema import load_question_set
    from age_bakeoff.runner import Runner, RunnerOptions

    # Find available question sets
    available = {}
    for yaml_file in sorted(_QUESTIONS_DIR.glob("*.yaml")):
        name = yaml_file.stem
        if not corpus or name in corpus:
            available[name] = yaml_file

    if not available:
        click.echo("No question sets found")
        return

    corpora = _load_corpora()

    async def _run():
        runner = Runner(
            config=cfg,
            engines=engines,
            options=RunnerOptions(
                runs_per_question=runs,
                output_dir=_RESULTS_DIR / "raw",
            ),
            tracker=tracker,
        )
        for name, yaml_path in available.items():
            qset = load_question_set(yaml_path)
            # Ingest corpus right before running its questions (single namespace)
            extraction = None
            corpus_obj = corpora.get(name)
            if corpus_obj:
                click.echo(f"Ingesting corpus={name} into both engines...")
                extraction = corpus_obj.load()
            click.echo(f"Running corpus={name} ({runs} runs/question)")
            results = await runner.run_corpus(name, qset, extraction=extraction)
            click.echo(
                f"  {len(results)} results written to "
                f"{_RESULTS_DIR / 'raw' / name}.json"
            )

    try:
        asyncio.run(_run())
    finally:
        _RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        cost_path = _RESULTS_DIR / "cost-run.json"
        tracker.save_report(cost_path)
        click.echo(
            f"Cost tally: ${tracker.total_usd:.4f} / ${tracker.budget_usd:.2f} "
            f"(report at {cost_path})"
        )


@cli.command()
@click.option(
    "--corpus",
    "-c",
    multiple=True,
    help="Corpus to judge (default: all with results)",
)
@click.option(
    "--budget-usd",
    default=50.0,
    type=float,
    help="Hard cap on OpenAI spend (default: $50)",
)
def judge(corpus: tuple[str, ...], budget_usd: float) -> None:
    """Run LLM judge on generated answers."""
    tracker = CostTracker(budget_usd=budget_usd)

    cfg = _get_config()

    from openai import AsyncOpenAI

    from age_bakeoff.models import RunResult
    from age_bakeoff.questions.schema import load_question_set
    from age_bakeoff.scorers.llm_judge import judge_answer, majority_verdict

    raw_dir = _RESULTS_DIR / "raw"
    judge_dir = _RESULTS_DIR / "judge"
    judge_dir.mkdir(parents=True, exist_ok=True)

    async def _run():
        client = AsyncOpenAI()
        for json_file in sorted(raw_dir.glob("*.json")):
            name = json_file.stem
            if corpus and name not in corpus:
                continue

            # Load question set for gold answers
            yaml_path = _QUESTIONS_DIR / f"{name}.yaml"
            if not yaml_path.exists():
                click.echo(f"No question set for {name}, skipping judge")
                continue

            qset = load_question_set(yaml_path)
            gold_by_id = {q.id: q for q in qset.questions}

            results = [
                RunResult(**r)
                for r in json.loads(json_file.read_text())
            ]

            verdicts: dict[str, dict[str, list]] = {}
            for r in results:
                if r.error or not r.generated_answer:
                    continue
                q = gold_by_id.get(r.question_id)
                if not q:
                    continue

                key = f"{r.engine}::{r.question_id}"
                if key not in verdicts:
                    verdicts[key] = {"engine": r.engine, "qid": r.question_id, "votes": []}

                v = await judge_answer(
                    client=client,
                    question=q.question,
                    gold_answer=q.gold_answer,
                    generated_answer=r.generated_answer,
                    model=cfg.judge_model,
                    tracker=tracker,
                )
                verdicts[key]["votes"].append(v.value)

            # Majority vote
            final = {}
            for key, data in verdicts.items():
                from age_bakeoff.scorers.llm_judge import JudgeVerdict

                votes = [JudgeVerdict(v) for v in data["votes"]]
                final[key] = {
                    "engine": data["engine"],
                    "question_id": data["qid"],
                    "verdict": majority_verdict(votes).value,
                    "votes": data["votes"],
                }

            out = judge_dir / f"{name}.json"
            out.write_text(json.dumps(final, indent=2, sort_keys=True))
            click.echo(f"Judged {len(final)} question/engine pairs for {name}")

    try:
        asyncio.run(_run())
    finally:
        _RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        cost_path = _RESULTS_DIR / "cost-judge.json"
        tracker.save_report(cost_path)
        click.echo(
            f"Cost tally: ${tracker.total_usd:.4f} / ${tracker.budget_usd:.2f} "
            f"(report at {cost_path})"
        )


@cli.command()
def report() -> None:
    """Generate the bake-off report from raw results."""
    from pydantic import ValidationError

    from age_bakeoff.models import RunResult
    from age_bakeoff.report.generator import generate_report
    from age_bakeoff.scorers.llm_judge import JudgeVerdict

    raw_dir = _RESULTS_DIR / "raw"
    judge_dir = _RESULTS_DIR / "judge"

    results_by_corpus: dict[str, list[RunResult]] = {}
    # Track which corpora have the `retrieved_chunk_contents` key in raw JSON.
    # Legacy raw JSON (written before that column existed) must be skipped for
    # fact recall — pydantic fills a default `[]`, which would otherwise be
    # indistinguishable from an engine that genuinely retrieved nothing.
    has_contents_by_corpus: dict[str, bool] = {}
    judge_by_corpus: dict = {}

    for json_file in sorted(raw_dir.glob("*.json")):
        name = json_file.stem
        raw_rows = json.loads(json_file.read_text())
        has_contents_by_corpus[name] = any(
            "retrieved_chunk_contents" in row for row in raw_rows
        )
        results_by_corpus[name] = [RunResult(**r) for r in raw_rows]

    # Load judge results if available
    for json_file in sorted(judge_dir.glob("*.json")):
        name = json_file.stem
        raw_judge = json.loads(json_file.read_text())
        corpus_verdicts: dict[str, dict[str, JudgeVerdict]] = {}
        for key, data in raw_judge.items():
            engine = data["engine"]
            qid = data["question_id"]
            if engine not in corpus_verdicts:
                corpus_verdicts[engine] = {}
            corpus_verdicts[engine][qid] = JudgeVerdict(data["verdict"])
        judge_by_corpus[name] = corpus_verdicts

    if not results_by_corpus:
        click.echo("No results found. Run `age-bakeoff run` first.")
        return

    # Compute fact recall + gather question classes from YAML question sets.
    # Legacy raw JSON (pre retrieved_chunk_contents) is skipped gracefully so
    # the report still generates; those rows will pick up fact recall on rerun.
    from age_bakeoff.questions.schema import load_question_set
    from age_bakeoff.scorers.fact_recall import score_fact_recall

    fact_recall_by_corpus: dict[str, dict[str, dict[str, float]]] = {}
    question_classes: dict[str, dict[str, object]] = {}
    skipped_corpora: set[str] = set()

    for name, results in results_by_corpus.items():
        yaml_path = _QUESTIONS_DIR / f"{name}.yaml"
        if not yaml_path.exists():
            continue
        try:
            qset = load_question_set(yaml_path)
        except (ValidationError, ValueError):
            # Strict 30-question validator rejects fixture-size question sets;
            # fall back to loose mode so the CLI still produces a report.
            # YAML parse errors / FileNotFoundError / unknown enums propagate.
            qset = load_question_set(yaml_path, strict=False)
        q_by_id = {q.id: q for q in qset.questions}
        question_classes[name] = {qid: q.question_class for qid, q in q_by_id.items()}

        # If this corpus was produced by a pre-Task-0.2 run, skip fact recall
        # entirely. Scoring would be misleading: the default `[]` from pydantic
        # is indistinguishable from "engine retrieved nothing".
        if not has_contents_by_corpus.get(name, False):
            skipped_corpora.add(name)
            continue

        per_engine: dict[str, dict[str, list[float]]] = {}
        for r in results:
            if r.error:
                continue
            q = q_by_id.get(r.question_id)
            if not q:
                continue
            # Score even when retrieved_chunk_contents is []: that's a real
            # measurement (engine retrieved nothing), not missing data.
            engine_bucket = per_engine.setdefault(r.engine, {})
            engine_bucket.setdefault(r.question_id, []).append(
                score_fact_recall(q, r.retrieved_chunk_contents)
            )

        collapsed = {
            engine: {qid: sum(s) / len(s) for qid, s in qmap.items()}
            for engine, qmap in per_engine.items()
        }
        if collapsed:
            fact_recall_by_corpus[name] = collapsed

    if skipped_corpora:
        click.echo(
            f"Fact recall skipped for {len(skipped_corpora)} corpora "
            f"({', '.join(sorted(skipped_corpora))}): raw JSON predates "
            "retrieved_chunk_contents. Rerun `age-bakeoff run` to regenerate."
        )

    out_path = _RESULTS_DIR / "REPORT.md"
    report_text = generate_report(
        results_by_corpus=results_by_corpus,
        fact_recall_by_corpus=fact_recall_by_corpus if fact_recall_by_corpus else None,
        judge_by_corpus=judge_by_corpus if judge_by_corpus else None,
        question_classes=question_classes if question_classes else None,
        output_path=out_path,
    )
    click.echo(f"Report written to {out_path}")
    click.echo(f"({len(report_text)} chars)")


@cli.group()
def diagnose() -> None:
    """Research diagnostics (Phase 1)."""


@diagnose.command("gold-strictness")
@click.option(
    "--corpus",
    "-c",
    multiple=True,
    help="Corpus to diagnose (default: all available)",
)
@click.option(
    "--seed",
    default=42,
    type=int,
    help=(
        "Question-sampling seed (alternative phrasings are non-deterministic "
        "at temperature=0.7)"
    ),
)
@click.option(
    "--samples",
    default=5,
    type=int,
    help="Questions to sample per corpus (default: 5)",
)
@click.option(
    "--alts-per-q",
    default=3,
    type=int,
    help="Alternative phrasings per question (default: 3)",
)
@click.option(
    "--budget-usd",
    default=50.0,
    type=float,
    help="Hard cap on OpenAI spend (default: $50)",
)
def gold_strictness_cmd(
    corpus: tuple[str, ...],
    seed: int,
    samples: int,
    alts_per_q: int,
    budget_usd: float,
) -> None:
    """Audit gold-answer strictness by sampling alternative phrasings.

    For each sampled question, asks the judge model for N factually-equivalent
    alternative phrasings, then re-judges each one. Alternatives judged `wrong`
    or `hallucinated` indicate the gold answer is "strict" -- reasonable
    paraphrases would fail the rubric.

    Output: results/diagnostics/gold_strictness.json
    """
    import random

    from pydantic import ValidationError

    tracker = CostTracker(budget_usd=budget_usd)

    cfg = _get_config()

    from openai import AsyncOpenAI

    from age_bakeoff.diagnostics import sample_gold_alternative_phrasings
    from age_bakeoff.questions.schema import load_question_set
    from age_bakeoff.scorers.llm_judge import judge_answer

    diag_dir = _RESULTS_DIR / "diagnostics"
    diag_dir.mkdir(parents=True, exist_ok=True)

    # Find available question sets
    available: dict[str, Path] = {}
    for yaml_file in sorted(_QUESTIONS_DIR.glob("*.yaml")):
        name = yaml_file.stem
        if not corpus or name in corpus:
            available[name] = yaml_file

    if not available:
        click.echo("No question sets found")
        return

    async def _run() -> dict:
        client = AsyncOpenAI()
        out_by_corpus: dict[str, list[dict]] = {}

        for name, yaml_path in available.items():
            try:
                qset = load_question_set(yaml_path)
            except (ValidationError, ValueError):
                # Strict 30-question validator rejects fixtures; fall back.
                qset = load_question_set(yaml_path, strict=False)

            rnd = random.Random(seed)
            sampled = rnd.sample(
                qset.questions, min(samples, len(qset.questions))
            )

            rows: list[dict] = []
            for q in sampled:
                alts = await sample_gold_alternative_phrasings(
                    client=client,
                    question=q.question,
                    gold_answer=q.gold_answer,
                    n=alts_per_q,
                    model=cfg.judge_model,
                    tracker=tracker,
                )
                verdicts: list[str] = []
                for alt in alts:
                    v = await judge_answer(
                        client=client,
                        question=q.question,
                        gold_answer=q.gold_answer,
                        generated_answer=alt,
                        model=cfg.judge_model,
                        tracker=tracker,
                    )
                    verdicts.append(v.value)
                strict_count = sum(
                    1 for v in verdicts if v in ("wrong", "hallucinated")
                )
                rows.append(
                    {
                        "qid": q.id,
                        "question": q.question,
                        "gold_answer": q.gold_answer,
                        "alternatives": alts,
                        "verdicts": verdicts,
                        "strict_count": strict_count,
                        "total": len(alts),
                    }
                )
            out_by_corpus[name] = rows
            click.echo(
                f"Diagnosed corpus={name}: {len(rows)} questions sampled"
            )

        return out_by_corpus

    try:
        result = asyncio.run(_run())
        out_path = diag_dir / "gold_strictness.json"
        payload = {
            "judge_model": cfg.judge_model,
            "generator_model": cfg.judge_model,  # same model; documented caveat
            "seed": seed,
            "samples": samples,
            "alts_per_q": alts_per_q,
            "corpora": result,
        }
        out_path.write_text(json.dumps(payload, indent=2, sort_keys=True))
        click.echo(f"Wrote {out_path}")
    finally:
        _RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        cost_path = _RESULTS_DIR / "cost-diagnose.json"
        tracker.save_report(cost_path)
        click.echo(
            f"Cost tally: ${tracker.total_usd:.4f} / ${tracker.budget_usd:.2f} "
            f"(report at {cost_path})"
        )
