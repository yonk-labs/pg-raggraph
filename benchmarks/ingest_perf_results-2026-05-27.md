# Embedding-Bottleneck Probe — 2026-05-27

Follow-up to the 2026-05-27 fast-ingest design doc. Once background extraction
takes the LLM out of the critical path, embedding is the only remaining cost
in `skip_llm=True` ingest. This probe quantifies the levers.

**Hardware:** Linux 6.17, CPU-only (no GPU detected via `nvidia-smi`).
**Corpus:** MHR slice — 20 docs / 91 chunks / 172k chars (same shape across all runs).
**Method:** cold ingest = embedding_cache wiped; warm = same texts re-ingested;
cost-of-embedding = `cold − warm` (isolates the embedding component
independent of DB write overhead).
**Harness:** `benchmarks/ingest_perf.py` (extended to take `--provider {local,http}`
and `--base-url` so the same script measures both arms).

## Results

| Variant | Provider | Model | Cold s | ms/chunk (cold) | Embedding ms/chunk | Throughput (cold) | Δ vs baseline |
|---|---|---|---:|---:|---:|---:|---:|
| Baseline | local (fastembed CPU) | bge-small-en-v1.5 | 12.78 | 140.4 | **139** | 1.6 docs/s | 1.0× |
| TEI HTTP | http (TEI Docker, CPU) | bge-small-en-v1.5 | 6.18 | 67.9 | **66** | 3.2 docs/s | **2.1× faster** |

Embedding remains the dominant cost in both: 99% of cold-ingest wall time
under local fastembed, 97% under TEI. Warm-cache numbers were unchanged
(~1.5–1.8 ms/chunk, ~120 docs/s) — DB store + overhead is not the bottleneck.

## Interpretation

- **2× speedup at zero hardware cost.** TEI's ONNX backend on the same CPU
  cores beats fastembed's by roughly 2× on bge-small. The cost is a small
  network hop (localhost; same machine) but that's swamped by the model
  speedup.
- **Embedding is still the floor.** Even after the 2× cut, 66 ms/chunk
  embedding is still ~97% of ingest wall time. A GPU or batched/pooled
  approach would be the next lever; the next step beyond that is fundamentally
  about choosing a smaller model, accepting lower quality, or moving to a
  shared embedding pool with batching across documents.
- **Recommendation for the laptop/dev profile:** keep local fastembed as
  the default — it requires no Docker. Document TEI as the recommended
  one-step upgrade for dedicated-server / shared-tenant deployments.

## Variants NOT measured this session

- **`bge-large` (1024-dim).** Test DB on port 5434 has `embedding_dim=384`
  baked into `chunks.embedding`; switching to bge-large requires running
  the online-embedding-migration cutover or pointing at the bench DB (5437),
  which has dim=1024 staged but also hosts MHR/MuSiQue/2Wiki/SCOTUS corpora
  whose `embedding_cache` would be invalidated by the probe's pre-cold
  wipe. Per `ASK FIRST` constraint on destructive bench-DB ops, deferred.
- **GPU variant.** No GPU on this box (`nvidia-smi` not present).
- **Fastembed batch-size sweep.** `FastEmbedProvider.__init__` accepts
  `threads` but not `batch_size`; fastembed batches internally. Adding a
  batch-size knob would require plumbing it through `FastEmbedProvider`
  and `get_embedding_provider` (new config field). Out of scope as a
  measurement-only task.
- **OpenAI embeddings.** `ASK FIRST` on paid-API tokens.

## Repro

```bash
# Baseline (local fastembed)
uv run python -m benchmarks.ingest_perf --docs 20

# TEI HTTP (CPU image; ~80 MB pull)
docker run -d --name tei-probe -p 8081:80 \
    ghcr.io/huggingface/text-embeddings-inference:cpu-latest \
    --model-id BAAI/bge-small-en-v1.5
uv run python -m benchmarks.ingest_perf --docs 20 --provider http \
    --base-url http://localhost:8081/v1 \
    --model BAAI/bge-small-en-v1.5 --dim 384
docker rm -f tei-probe
```

## Pairs with

- `docs/superpowers/specs/2026-05-27-fast-ingest-background-extraction-design.md`
  — the design doc this measurement closes out (SC-009).
- `docs/cookbook/background-extraction.md` — operator-facing guide for the
  new decoupled-ingest surface.
