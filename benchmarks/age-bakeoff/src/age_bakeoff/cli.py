"""CLI for the AGE vs pg-raggraph bake-off benchmark."""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

import click

from age_bakeoff.config import BakeoffConfig

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
def run(corpus: tuple[str, ...], runs: int) -> None:
    """Run benchmark questions against both engines."""
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

    async def _run():
        runner = Runner(
            config=cfg,
            engines=engines,
            options=RunnerOptions(
                runs_per_question=runs,
                output_dir=_RESULTS_DIR / "raw",
            ),
        )
        for name, yaml_path in available.items():
            click.echo(f"Running corpus={name} ({runs} runs/question)")
            qset = load_question_set(yaml_path)
            results = await runner.run_corpus(name, qset)
            click.echo(
                f"  {len(results)} results written to "
                f"{_RESULTS_DIR / 'raw' / name}.json"
            )

    asyncio.run(_run())


@cli.command()
@click.option(
    "--corpus",
    "-c",
    multiple=True,
    help="Corpus to judge (default: all with results)",
)
def judge(corpus: tuple[str, ...]) -> None:
    """Run LLM judge on generated answers."""
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

    asyncio.run(_run())


@cli.command()
def report() -> None:
    """Generate the bake-off report from raw results."""
    from age_bakeoff.models import RunResult
    from age_bakeoff.report.generator import generate_report
    from age_bakeoff.scorers.llm_judge import JudgeVerdict

    raw_dir = _RESULTS_DIR / "raw"
    judge_dir = _RESULTS_DIR / "judge"

    results_by_corpus: dict[str, list[RunResult]] = {}
    judge_by_corpus: dict = {}

    for json_file in sorted(raw_dir.glob("*.json")):
        name = json_file.stem
        results_by_corpus[name] = [
            RunResult(**r) for r in json.loads(json_file.read_text())
        ]

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

    out_path = _RESULTS_DIR / "REPORT.md"
    report_text = generate_report(
        results_by_corpus=results_by_corpus,
        judge_by_corpus=judge_by_corpus if judge_by_corpus else None,
        output_path=out_path,
    )
    click.echo(f"Report written to {out_path}")
    click.echo(f"({len(report_text)} chars)")
