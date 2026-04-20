<!-- Thanks for contributing! Fill in the sections that apply. -->

## What this PR does

<!-- One sentence: "This PR ...". -->

## Why

<!-- The problem or motivation. Link the issue if there is one: "Closes #NNN". -->

## How

<!-- Key implementation choices. What you changed, what you deliberately didn't change. -->

## Type of change

- [ ] Bug fix (non-breaking)
- [ ] New feature (non-breaking, opt-in)
- [ ] Breaking change (requires major version bump)
- [ ] Documentation only
- [ ] Benchmark / test / internal tooling

## Test plan

<!-- How did you verify this works? Commands run, new tests added, manual steps taken. -->

- [ ] `uv run pytest` passes locally
- [ ] `uv run ruff check . && uv run ruff format --check .` clean
- [ ] New behavior has a test
- [ ] New config or API is documented in `README.md` and/or `docs/user-guide.md`

## Benchmark impact (if retrieval, chunking, or indexing changed)

<!-- Before/after numbers from a real run. Cite the raw result file path. -->

| | Before | After |
|---|---|---|
| Accuracy (fully_correct / total) | — | — |
| p50 latency | — | — |
| Raw results | — | — |

## Backwards compatibility

<!-- Anyone upgrading from the previous release — do they need to do anything? -->

## Anything else reviewers should know

<!-- Known limitations, follow-up work, things you'd like feedback on. -->
