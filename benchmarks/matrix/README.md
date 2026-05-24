# Matrix Benchmark Harness

This is the repeatable regression and exploration harness. It is separate from
`benchmarks/showcase/`, which should stay small and presentation-oriented.

## Fast Reload

The expensive unit is an ingest shape:

- workload dataset
- extraction arm
- embedding model and dimension
- chunking strategy
- chunk size and overlap

Each shape is staged into a deterministic namespace and recorded in
`shape-manifest.json`. With `ingest.reuse_existing_shapes: true`, later sweeps
reuse populated namespaces and avoid re-chunking/re-embedding. Set
`ingest.refresh_shapes: true` only when the corpus, chunker, embedding, or
extraction behavior changed.

## Commands

Smoke:

```bash
uv run python -m benchmarks.matrix.suite --config benchmarks/matrix/smoke.yaml --judge --report
```

Regression prep only:

```bash
uv run python -m benchmarks.matrix.suite --config benchmarks/matrix/regression.yaml --prepare-only
```

Regression with judging:

```bash
uv run python -m benchmarks.matrix.suite --config benchmarks/matrix/regression.yaml --judge --report
```

Full suite:

```bash
uv run python -m benchmarks.matrix.suite --config benchmarks/matrix/full.yaml --judge --report
```

Outputs live under `.matrix-runs/`, which is ignored.
