# Extraction direction oracle — #110 verification (2026-08-28)

Question: does the #110 prompt hardening (PR #118 — the orientation contract
`"source REL_TYPE target" must read as a true sentence`, with the passive
inversion called out) actually move direction agreement, and is any
deterministic post-processor needed on top?

Method: `run_direction_bench.py` — seeded corpus of 60 corporate-registry
briefs, 191 gold edges (OWNS / ACQUIRED / FOUNDED / PARENT_OF), sentence
voice drawn 50/50 active/passive. Extraction per doc with the library's
default prompt (`base` arm) vs default + the exact PR #118 rule (`direction`
arm). Scoring matches extracted relationships to gold entity pairs
(undirected) and scores direction separately: an edge is direction-correct
when its (src, dst) reads true under its own rel_type's frame (active types:
src=agent; `*_BY`/`SUBSIDIARY_OF`-style types: src=patient). Symmetric types
(`RELATED_TO`, …) are excluded and counted. gpt-5 models take no temperature
param, so runs wobble; two independent nano runs are reported.

## Direction agreement (matched pairs, seed 42, n=60 docs / 191 gold edges)

| model | arm | run 1 | run 2 |
|---|---|---|---|
| gpt-5-mini | base | 98.4% (188/191) | 99.0% (189/191) |
| gpt-5-mini | +rule | 99.0% (189/191) | 99.0% (189/191) |
| gpt-5-nano | base | **85.6%** (137/160, excl 31) | **87.3%** (138/158, excl 32) |
| gpt-5-nano | +rule | **95.3%** (161/169, excl 22) | **98.5%** (134/136, excl 55) |

Pair recall was 99.5–100% everywhere — the corpus isolates direction, not
recall. Run-1 nano JSONs were overwritten by run 2 (filename bug, since
fixed); run-1 numbers are from the run log.

**Verdict: the prompt rule is verified.** On the weaker model it recovers
+9.7pp / +11.2pp direction agreement across two runs; on the strong model
direction was never broken (~99% ceiling, rule is neutral). The failure the
#110 reporter measured (~50%) is extractor-model-dependent — pg-raggraph's
default config points at small local models, which is exactly where the rule
pays.

## Post-processor counterfactuals — both rejected

Two deterministic hardening candidates were evaluated against the raw edges
(run 2, stored in the results JSON):

1. **Entity-type signature validation** (flip edges whose
   `(src.entity_type, dst.entity_type)` contradicts a declared signature):
   7 of 8 residual nano misses are company→company edges — signatures catch
   none of them. Rejected.
2. **`*_BY` label normalization** (rewrite `X_BY` → active form, keep
   orientation): nano orients `_BY` labels **correctly** 113/130 times
   (base arm); the rewrite would break those 113 to fix 17 — counterfactual
   agreement craters to 26.6%. The eyeballed "label is decoration" pattern
   was selection bias from reading only the miss list. Rejected.

The residual error class after the rule (2/136 on nano run 2) is a
mislabeled `_BY` type with active orientation — rare, and no deterministic
rule distinguishes it from the correctly-inverted majority.

## Follow-ups

- Re-run both arms on the local extraction model (Qwen box / Ollama) when
  available — one command per arm; that's the deployment-realistic datapoint.
- `excluded` (symmetric `RELATED_TO`-style labels) ranged 22–55 on nano —
  direction-unscoreable edges are a rel_type-quality question (#106 space),
  not a direction question.
