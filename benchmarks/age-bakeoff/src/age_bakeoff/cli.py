"""CLI for the AGE vs pg-raggraph bake-off benchmark."""
from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path

import click
from dotenv import load_dotenv

from age_bakeoff.config import BakeoffConfig
from age_bakeoff.cost import CostTracker

_CHUNKER_CHOICES = ("sentence_aware", "hierarchy")


def _apply_chunker_flag(chunker: str | None) -> None:
    """Propagate ``--chunker`` to ``BAKEOFF_CHUNKER`` for loaders downstream.

    ``extraction.loaders`` reads the env var lazily; setting it here makes the
    CLI flag the single override point. ``None`` means leave the env alone
    (caller's shell-exported value wins, default ``sentence_aware`` takes over
    if unset).
    """
    if chunker is None:
        return
    os.environ["BAKEOFF_CHUNKER"] = chunker

logger = logging.getLogger("age_bakeoff")

_QUESTIONS_DIR = Path(__file__).resolve().parents[2] / "questions"
_RESULTS_DIR = Path(__file__).resolve().parents[2] / "results"

# pydantic-settings reads .env for BakeoffConfig fields but does NOT export to
# os.environ. AsyncOpenAI() reads OPENAI_API_KEY from os.environ directly, so
# without this call the CLI silently records every response as an auth error.
load_dotenv(_RESULTS_DIR.parent / ".env")


def _get_config() -> BakeoffConfig:
    return BakeoffConfig()


def _corpus_and_label_from_stem(stem: str) -> tuple[str, str | None]:
    """Split a raw-JSON filename stem into (base_corpus, label).

    ``'acme'`` -> ``('acme', None)``.
    ``'acme__smart'`` -> ``('acme', 'smart')``.

    Labelled raw JSON is produced by ``age-bakeoff run --label <label>`` and
    shares its question set with the unlabelled baseline. The label is only a
    filename suffix, never a separate corpus — downstream commands (judge,
    report, diagnose context-relevance) use the BASE corpus to find
    ``questions/{base}.yaml``.
    """
    if "__" in stem:
        base, label = stem.split("__", 1)
        return base, label
    return stem, None


def _merge_diagnose_cost(
    cost_path: Path, tracker: CostTracker, phase: str
) -> float:
    """Accumulate cost across successive ``diagnose <subcommand>`` runs.

    ``cost-diagnose.json`` is shared by all ``diagnose`` subcommands so the
    $50 budget ceiling is enforced across the full research session, not per
    invocation. This helper handles both halves of that lifecycle:

    - ``phase="load"``: if a prior ``cost-diagnose.json`` exists, seed
      ``tracker.total_usd`` with its prior total so budget-breach checks in
      ``tracker.record`` fire against the cumulative spend. Returns the prior
      total (``0.0`` if no file).
    - ``phase="save"``: merge any new calls recorded during this run INTO the
      prior file's ``by_model`` aggregation and write the combined report.
      Individual ``calls`` lists aren't persisted across invocations (only the
      per-model aggregate), so only the current tracker's calls are added.

    Returns the prior total on load; returns ``0.0`` on save.
    """
    if phase == "load":
        if not cost_path.exists():
            return 0.0
        prior = json.loads(cost_path.read_text())
        prior_total = float(prior.get("total_usd", 0.0))
        tracker.total_usd = prior_total
        return prior_total

    if phase == "save":
        cost_path.parent.mkdir(parents=True, exist_ok=True)
        prior_by_model: dict = {}
        if cost_path.exists():
            prior = json.loads(cost_path.read_text())
            prior_by_model = prior.get("by_model", {}) or {}

        # Start from prior aggregate, add each new call from this invocation
        merged_by_model: dict = {
            m: dict(bucket) for m, bucket in prior_by_model.items()
        }
        for call in tracker.calls:
            m = call["model"]
            bucket = merged_by_model.setdefault(
                m,
                {
                    "calls": 0,
                    "usd": 0.0,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                },
            )
            bucket["calls"] += 1
            bucket["usd"] += call["usd"]
            bucket["prompt_tokens"] += call["prompt_tokens"]
            bucket["completion_tokens"] += call["completion_tokens"]

        report = {
            "total_usd": tracker.total_usd,
            "budget_usd": tracker.budget_usd,
            "by_model": merged_by_model,
        }
        cost_path.write_text(json.dumps(report, indent=2, sort_keys=True))
        return 0.0

    raise ValueError(f"unknown phase {phase!r}")


def _get_engines(cfg: BakeoffConfig) -> dict:
    from age_bakeoff.engines.age import AgeEngine
    from age_bakeoff.engines.pgrg import PgrgEngine

    return {
        "pgrg": PgrgEngine(
            dsn=cfg.pgrg_dsn,
            top_k=cfg.top_k,
            hop_budget=cfg.hop_budget,
            retrieval_mode=cfg.retrieval_mode,
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
@click.option(
    "--chunker",
    type=click.Choice(_CHUNKER_CHOICES),
    default=None,
    help=(
        "Chunker strategy (default: env BAKEOFF_CHUNKER or 'sentence_aware'). "
        "'hierarchy' enables heading/title-prefixed chunks."
    ),
)
def ingest(corpus: tuple[str, ...], chunker: str | None) -> None:
    """Ingest corpora into both engines."""
    _apply_chunker_flag(chunker)
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
    "--mode",
    default=None,
    help=(
        "pg-raggraph retrieval mode: hybrid|smart|local|global|naive|naive_boost "
        "(overrides config; only affects the pgrg engine)"
    ),
)
@click.option(
    "--label",
    default=None,
    help=(
        "Suffix for raw JSON filename (e.g., 'smart', 'sig-vector'). "
        "Omit to write results/raw/{corpus}.json; with a label, "
        "writes results/raw/{corpus}__{label}.json."
    ),
)
@click.option(
    "--budget-usd",
    default=50.0,
    type=float,
    help="Hard cap on OpenAI spend (default: $50)",
)
@click.option(
    "--chunker",
    type=click.Choice(_CHUNKER_CHOICES),
    default=None,
    help=(
        "Chunker strategy (default: env BAKEOFF_CHUNKER or 'sentence_aware'). "
        "Only affects corpora re-ingested by this command."
    ),
)
@click.option(
    "--skip-ingest/--no-skip-ingest",
    default=False,
    help=(
        "Skip re-ingestion and reuse whatever is already in each engine's DB. "
        "Use for mode sweeps where ingest time dominates: ingest once under a "
        "prior --mode, then pass --skip-ingest for subsequent modes. Retrieval "
        "results stay valid because retrieval_mode is a query-time parameter."
    ),
)
def run(
    corpus: tuple[str, ...],
    runs: int,
    mode: str | None,
    label: str | None,
    budget_usd: float,
    chunker: str | None,
    skip_ingest: bool,
) -> None:
    """Run benchmark questions against both engines."""
    _apply_chunker_flag(chunker)
    tracker = CostTracker(budget_usd=budget_usd)

    cfg = _get_config()
    if mode is not None:
        # BakeoffConfig is a non-frozen pydantic-settings model; direct mutation
        # is fine and avoids the model_copy boilerplate.
        cfg.retrieval_mode = mode
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
                label=label,
            ),
            tracker=tracker,
        )
        suffix = f"__{label}" if label else ""
        for name, yaml_path in available.items():
            qset = load_question_set(yaml_path)
            # Ingest corpus right before running its questions (single namespace).
            # --skip-ingest reuses whatever each engine already has, which is
            # the mode-sweep fast path (ingest once, run many modes).
            extraction = None
            corpus_obj = corpora.get(name)
            if corpus_obj and not skip_ingest:
                click.echo(f"Ingesting corpus={name} into both engines...")
                extraction = corpus_obj.load()
            elif skip_ingest:
                click.echo(
                    f"Skipping ingest for corpus={name} "
                    "(reusing previously-ingested state)"
                )
            click.echo(f"Running corpus={name} ({runs} runs/question)")
            results = await runner.run_corpus(name, qset, extraction=extraction)
            click.echo(
                f"  {len(results)} results written to "
                f"{_RESULTS_DIR / 'raw' / f'{name}{suffix}'}.json"
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
            # Labelled raw JSON (acme__smart.json) shares its question set with
            # the baseline — look up questions/{base}.yaml, not {name}.yaml.
            # Filter `--corpus` against the base, so `--corpus acme` matches
            # both `acme.json` and `acme__*.json` (SC-003/004/005 labels).
            base, _label = _corpus_and_label_from_stem(name)
            if corpus and base not in corpus:
                continue
            yaml_path = _QUESTIONS_DIR / f"{base}.yaml"
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
        # Labelled raw JSON (acme__smart.json) shares its question set with the
        # baseline; resolve to questions/{base}.yaml. The full stem stays as the
        # results_by_corpus/fact_recall/question_classes key so labelled runs
        # appear as distinct rows in REPORT.md.
        base, _label = _corpus_and_label_from_stem(name)
        yaml_path = _QUESTIONS_DIR / f"{base}.yaml"
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

    # Share cost-diagnose.json across all diagnose subcommands so the budget
    # ceiling is enforced across the full research session.
    _RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    cost_path = _RESULTS_DIR / "cost-diagnose.json"
    _merge_diagnose_cost(cost_path, tracker, phase="load")

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
        _merge_diagnose_cost(cost_path, tracker, phase="save")
        click.echo(
            f"Cost tally: ${tracker.total_usd:.4f} / ${tracker.budget_usd:.2f} "
            f"(report at {cost_path})"
        )


@diagnose.command("context-relevance")
@click.option(
    "--corpus",
    "-c",
    multiple=True,
    help="Corpus to diagnose (default: all with raw results)",
)
@click.option(
    "--seed",
    default=42,
    type=int,
    help="Question-sampling seed (default: 42)",
)
@click.option(
    "--samples",
    default=10,
    type=int,
    help="Questions to sample per corpus (default: 10)",
)
@click.option(
    "--budget-usd",
    default=50.0,
    type=float,
    help="Hard cap on OpenAI spend (default: $50)",
)
def context_relevance_cmd(
    corpus: tuple[str, ...],
    seed: int,
    samples: int,
    budget_usd: float,
) -> None:
    """Score per-chunk LLM-judged relevance for sampled questions.

    Separates retrieval quality from answer-generation quality. A chunk that
    scores 0.0 relevance but was retrieved is a retrieval issue; a chunk that
    scores 1.0 where the final answer is still wrong is an answer-generation
    issue.

    Skips corpora whose raw JSON predates ``retrieved_chunk_contents`` (the
    default ``[]`` from pydantic is indistinguishable from "retrieved nothing";
    rerun ``age-bakeoff run`` to regenerate those corpora).

    Output: ``results/diagnostics/context_relevance.json``.
    """
    import random

    from pydantic import ValidationError

    tracker = CostTracker(budget_usd=budget_usd)

    # Share cost-diagnose.json across diagnose subcommands (see _merge_diagnose_cost).
    _RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    cost_path = _RESULTS_DIR / "cost-diagnose.json"
    _merge_diagnose_cost(cost_path, tracker, phase="load")

    cfg = _get_config()

    from openai import AsyncOpenAI

    from age_bakeoff.questions.schema import load_question_set
    from age_bakeoff.scorers.chunk_relevance import score_chunk_relevance

    raw_dir = _RESULTS_DIR / "raw"
    diag_dir = _RESULTS_DIR / "diagnostics"
    diag_dir.mkdir(parents=True, exist_ok=True)

    # Which raw files carry retrieved_chunk_contents? Mirror the report command:
    # peek at raw rows; skip corpora that predate Task 0.2.
    raw_rows_by_corpus: dict[str, list[dict]] = {}
    has_contents_by_corpus: dict[str, bool] = {}
    for json_file in sorted(raw_dir.glob("*.json")):
        name = json_file.stem
        if name.startswith("cost-"):
            continue  # defensive; raw_dir shouldn't hold cost files anyway
        # `--corpus acme` must match labelled variants like `acme__smart` too.
        base, _label = _corpus_and_label_from_stem(name)
        if corpus and base not in corpus:
            continue
        rows = json.loads(json_file.read_text())
        raw_rows_by_corpus[name] = rows
        has_contents_by_corpus[name] = any(
            "retrieved_chunk_contents" in row for row in rows
        )

    if not raw_rows_by_corpus:
        click.echo("No raw results found under results/raw/.")
        return

    async def _run() -> dict:
        client = AsyncOpenAI()
        out: dict[str, dict[str, dict[str, list[float]]]] = {}

        for name, rows in raw_rows_by_corpus.items():
            if not has_contents_by_corpus.get(name, False):
                click.echo(
                    f"Skipping corpus={name}: raw JSON predates "
                    "retrieved_chunk_contents. Rerun `age-bakeoff run`."
                )
                continue

            # Labelled raw JSON (acme__smart.json) shares its question set
            # with the baseline — look up questions/{base}.yaml.
            base, _label = _corpus_and_label_from_stem(name)
            yaml_path = _QUESTIONS_DIR / f"{base}.yaml"
            if not yaml_path.exists():
                click.echo(f"No question set for {name}, skipping")
                continue
            try:
                qset = load_question_set(yaml_path)
            except (ValidationError, ValueError):
                # Strict 30-question validator rejects fixtures; fall back.
                qset = load_question_set(yaml_path, strict=False)
            q_by_id = {q.id: q for q in qset.questions}

            rnd = random.Random(seed)
            # Sample from questions that actually appear in the raw rows so we
            # don't pick question IDs that were never run.
            qids_with_rows = sorted({r["question_id"] for r in rows})
            picked_qids = set(
                rnd.sample(
                    qids_with_rows, min(samples, len(qids_with_rows))
                )
            )

            per_engine: dict[str, dict[str, list[float]]] = {}
            for r in rows:
                qid = r["question_id"]
                if qid not in picked_qids:
                    continue
                q = q_by_id.get(qid)
                if not q:
                    continue
                chunks = r.get("retrieved_chunk_contents") or []
                if not chunks:
                    # Legacy or genuinely empty -- skip (score_chunk_relevance
                    # returns [] anyway; skipping avoids bloating the output).
                    continue
                engine = r["engine"]
                # Only score once per (engine, qid) -- if there are multiple
                # runs, use the first.
                engine_bucket = per_engine.setdefault(engine, {})
                if qid in engine_bucket:
                    continue
                scores = await score_chunk_relevance(
                    client=client,
                    question=q.question,
                    chunks=chunks,
                    model=cfg.judge_model,
                    tracker=tracker,
                )
                engine_bucket[qid] = scores

            if per_engine:
                out[name] = per_engine
                total_pairs = sum(len(v) for v in per_engine.values())
                click.echo(
                    f"Diagnosed corpus={name}: {total_pairs} "
                    "(engine,question) pairs scored"
                )

        return out

    try:
        result = asyncio.run(_run())
        out_path = diag_dir / "context_relevance.json"
        payload = {
            "judge_model": cfg.judge_model,
            "seed": seed,
            "samples": samples,
            "scoring_policy": "first_run_only",
            "corpora": result,
        }
        out_path.write_text(json.dumps(payload, indent=2, sort_keys=True))
        click.echo(f"Wrote {out_path}")
    finally:
        _merge_diagnose_cost(cost_path, tracker, phase="save")
        click.echo(
            f"Cost tally: ${tracker.total_usd:.4f} / ${tracker.budget_usd:.2f} "
            f"(report at {cost_path})"
        )


def _parse_k_values(raw: str) -> list[int]:
    """Parse comma-separated ints like "5,10,20" or "5, 10, 20".

    Strips whitespace around each entry. Rejects empty entries, non-ints, and
    non-positive values so users get a clear error instead of a mysterious
    ``KeyError`` or degenerate retrieval downstream. Dedupes while preserving
    first-seen order so ``"5,10,5,20,10"`` sweeps each k exactly once.
    """
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if not parts:
        raise click.BadParameter(
            "--k-values must contain at least one integer"
        )
    try:
        ks = [int(p) for p in parts]
    except ValueError as exc:
        raise click.BadParameter(
            f"--k-values must be comma-separated integers, got {raw!r}"
        ) from exc
    if any(k <= 0 for k in ks):
        raise click.BadParameter("k_values must be positive integers")
    return list(dict.fromkeys(ks))


@diagnose.command("top-k-sweep")
@click.option(
    "--corpus",
    "-c",
    multiple=True,
    help="Corpus to diagnose (default: all available)",
)
@click.option(
    "--k-values",
    default="5,10,20,50",
    help="Comma-separated top_k values to sweep (default: 5,10,20,50)",
)
@click.option(
    "--samples",
    default=10,
    type=int,
    help="Questions to sample per corpus (default: 10)",
)
@click.option(
    "--seed",
    default=42,
    type=int,
    help="Question-sampling seed (default: 42)",
)
def top_k_sweep_cmd(
    corpus: tuple[str, ...],
    k_values: str,
    samples: int,
    seed: int,
) -> None:
    """Re-run sampled questions at multiple ``top_k`` values per engine.

    LLM-free: only calls ``engine.retrieve()`` -- no OpenAI spend, no answer
    generation, no judge. Captures ``chunk_ids`` + ``contents`` + ``retrieval_ms``
    at each ``top_k`` setting so the downstream fact-recall pass in
    ``QUALITY-ANALYSIS.md`` can quantify whether raising ``k`` recovers missing
    facts.

    Assumes both engines have already ingested the target corpora via a prior
    ``age-bakeoff run``; this command does NOT re-ingest.

    Output: ``results/diagnostics/top_k_sweep.json`` with schema
    ``{k_values, samples, seed, corpora: {corpus: {engine: {k: runs}}}}``.
    JSON object keys for ``k`` are stringified ints (standard JSON behavior).
    """
    import random

    from pydantic import ValidationError

    ks = _parse_k_values(k_values)

    cfg = _get_config()
    engines = _get_engines(cfg)

    from age_bakeoff.diagnostics import top_k_sweep
    from age_bakeoff.questions.schema import load_question_set

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
        out_by_corpus: dict[str, dict[str, dict[int, list]]] = {}

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
            questions = [q.question for q in sampled]

            per_engine: dict[str, dict[int, list]] = {}
            for engine_name, engine in engines.items():
                per_engine[engine_name] = await top_k_sweep(
                    engine=engine, questions=questions, k_values=ks
                )
            out_by_corpus[name] = per_engine
            click.echo(
                f"Diagnosed corpus={name}: {len(questions)} questions "
                f"x {len(ks)} k values x {len(engines)} engines"
            )

        return out_by_corpus

    result = asyncio.run(_run())
    out_path = diag_dir / "top_k_sweep.json"
    payload = {
        "k_values": ks,
        "samples": samples,
        "seed": seed,
        "corpora": result,
    }
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True))
    click.echo(f"Wrote {out_path}")
