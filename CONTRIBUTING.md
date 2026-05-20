# Contributing to pg-raggraph

Thanks for considering a contribution. This is a small, focused library and we want to keep it that way — clear code, honest benchmarks, and a low barrier to reading the whole thing in a sitting.

## What kinds of changes we welcome

- **Bug reports and fixes.** File an issue first for anything non-obvious so we can agree on the shape of the fix.
- **New chunkers, embedders, or retrieval modes** — ship them behind a config flag, with a test, and a benchmark-table entry showing the tradeoff.
- **Documentation fixes and clarifications.** Always welcome.
- **Benchmark extensions.** New corpora, new question sets, new metrics. Evidence is the point.

## What to check before opening a PR

- Tests pass: `uv run pytest`
- Lint clean: `uv run ruff check . && uv run ruff format --check .` (or `pre-commit run --all-files`, see below)
- New behavior has a test. New config knobs are documented in `docs/user-guide.md` and the `README.md` config table.
- Benchmark numbers in the PR description cite a raw result file, not a summary paragraph.

> **Pre-commit hook (recommended).** This repo ships a `.pre-commit-config.yaml` that runs both ruff invocations on every `git commit`. Install once:
>
> ```bash
> uv tool install pre-commit && pre-commit install
> ```
>
> After that, `git commit` blocks if either ruff check fails — matching CI's lint job exactly. Saves the round-trip of "merged with red CI, push a follow-up fix."

## Local development setup

```bash
# 1. Clone and enter the repo
git clone https://github.com/<you>/pg-raggraph.git
cd pg-raggraph

# 2. Install dependencies (Python 3.12+ required)
uv sync --all-extras

# 2a. (Recommended) install the pre-commit hook
uv tool install pre-commit
pre-commit install

# 3. Start PostgreSQL with pgvector + pg_trgm
docker compose up -d

# 4. Copy env examples and fill in keys
cp .env.example .env
cp benchmarks/age-bakeoff/.env.example benchmarks/age-bakeoff/.env
# edit both files — see README for the full config table

# 5. Run the test suite
uv run pytest                    # all tests (needs DB up)
uv run pytest tests/unit/        # just unit (no DB needed)
uv run pytest tests/integration/ # integration (needs DB up)
```

## Code style

- **Python 3.12+, async-first.** All database operations use `asyncpg` / `psycopg` async.
- **Ruff for lint + format.** We match `pyproject.toml` settings; don't reformat with a different tool.
- **Small, focused PRs.** One logical change per PR. Bug fix ≠ refactor ≠ feature; split them.
- **Comments are rare.** Name things well enough that most comments are unnecessary. When a comment is warranted, explain *why*, not *what*.
- **Tests tell the story.** If the behavior isn't obvious from a test, the test is unclear.

## Commit and PR expectations

- Commit messages follow the existing repo style — see `git log --oneline -20` for examples. A one-line summary with a short imperative verb (`feat:`, `fix:`, `docs:`, `test:`) followed by a body explaining *why* the change matters.
- PR titles should finish the sentence "This PR ...". Bodies should explain the user-facing effect and link any relevant issue.
- PRs that change benchmark or library defaults must include before/after numbers from a real run.
- Co-authored-by lines are welcome.

## When in doubt

Open a draft PR early or start a discussion issue. Aligning on approach before you've written a lot of code saves everyone time.

## Code of conduct

This project follows the [Contributor Covenant](CODE_OF_CONDUCT.md). Please read it before opening an issue or PR.

## Security

See [SECURITY.md](SECURITY.md) for how to report vulnerabilities.
