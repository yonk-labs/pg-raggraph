# Per-call kwargs on `query()` / `ask()`

> **TL;DR.** Most of the behavior that used to be config-only is now overridable per-call. Multi-tenant servers sharing one `GraphRAG` instance can pick different retrieval policies per request without mutating shared config — no locks, no races.

`GraphRAG.query()` and `GraphRAG.ask()` accept eight keyword-only arguments that override their matching `config.*` field for one call. Pass `None` (the default) and the call falls back to config. Pass an explicit value and the call uses that value once.

```python
# Default — uses config for everything
result = await rag.ask("What's the latest on this?")

# Per-call override — config untouched
result = await rag.ask(
    "What's the latest on this?",
    retracted_behavior="hide",
    version_filter="3.12",
    memory_tier="consolidated",
)
```

## The full set

All keyword-only after the first positional `question`. Order doesn't matter; each defaults to `None` (means "use config").

| Kwarg | Type | What it controls | Where the value lives in config |
|---|---|---|---|
| `mode` | `str` | Retrieval mode (`smart` default) | — (always per-call) |
| `namespace` | `str \| None` | Tenant scope | `config.namespace` |
| `as_of` | `datetime \| None` | Time-travel — restrict to docs whose effective window covers this timestamp | — (per-call only) |
| `version_filter` | `str \| None` | Content scope — restrict to docs with this `version_label` | — (per-call only) |
| `evolution_aware` | `bool \| None` | Force `False` to ignore `evolution_tier` for this call | `config.evolution_tier` |
| `retracted_behavior` | `"hide" \| "flag" \| "surface_both" \| None` | How to handle retracted docs | `config.retracted_behavior` |
| `supersession_behavior` | `"hide" \| "prefer_new" \| "surface_both" \| None` | How to handle superseded docs | `config.supersession_behavior` |
| `memory_tier` | `"provisional" \| "consolidated" \| "both" \| None` | chunkshop SP-A tier filter (only fires on chunks with `metadata.tier`) | `config.memory_tier` |
| `retrieval_strategy` | `"weighted" \| "pre_filter" \| "vector_first" \| None` | SQL shape for `naive` / `naive_boost` modes | `config.retrieval_strategy` |
| `rerank` | `bool` | Cross-encoder rerank (off by default; off-by-design until you opt in) | — (per-call only) |

`mode`, `as_of`, `version_filter`, `rerank` are per-call only because they were never config-driven. The rest mirror config fields with explicit `None`-falls-back-to-config semantics.

## Two distinct categories — content scope vs evolution scoring

**Content-scoping kwargs** apply regardless of `evolution_tier`. They're WHERE clauses on `documents.metadata` / typed columns:

- `namespace` — always-on tenant filter
- `version_filter` — restrict to specific `version_label`
- `memory_tier` — restrict to `provisional` / `consolidated` (only affects chunks with the tier metadata)

**Evolution-scoring kwargs** participate in the score expression and are tier-gated. They only fire when `evolution_tier != "off"`:

- `retracted_behavior` — interacts with retraction scoring
- `supersession_behavior` — interacts with supersession scoring
- `as_of` — interacts with `effective_from` / `effective_to` temporal window

Setting `evolution_aware=False` on a single call forces the effective tier to `"off"` for that call, which short-circuits the scoring-gated kwargs but **not** the content-scoping kwargs. So `version_filter` still applies under `evolution_aware=False` — that's the [#18](https://github.com/yonk-labs/pg-raggraph/issues/18) fix from 2026-05-20.

## Multi-tenant patterns (the why)

### Pattern 1 — different tenants want different retraction policies

Pre-arc: the only way to change `retracted_behavior` per request was to mutate `rag.config.retracted_behavior`, which is shared. That requires an `asyncio.Lock` around every call — serializing the API under contention.

Post-arc:

```python
@app.post("/v1/ask")
async def ask(req: AskRequest, tenant_id: str = Depends(current_tenant)):
    # Each tenant configures its own retraction policy.
    policy = await get_retraction_policy(tenant_id)
    result = await rag.ask(
        req.question,
        namespace=tenant_id,
        retracted_behavior=policy,  # per-call — no shared mutation
    )
    return result
```

### Pattern 2 — debug view vs production view

```python
# Production answer: hide retracted documents
result = await rag.ask(q, retracted_behavior="hide")

# Debug / admin view: show everything, flagged
result = await rag.ask(q, retracted_behavior="surface_both")
```

Same `rag` instance, two different views, zero shared-state mutation.

### Pattern 3 — version-scoped Q&A (the dx-poc / docs-versioning use case)

```python
# Default tier=off; version_filter still applies (issue #18 fix)
result = await rag.ask("How does StrEnum work?", version_filter="3.12")
# Only sees docs with documents.version_label = "3.12"
```

This works at any `evolution_tier` setting because `version_filter` is content scoping.

### Pattern 4 — chunkshop SP-A consolidated-wins (O2 enforcement)

```python
# Default — both tiers visible, ranked naturally
result = await rag.ask("What did the agent learn about postgres?")

# Per-call — only consolidated facts (multi-tenant memory server)
result = await rag.ask(
    "What did the agent decide?",
    memory_tier="consolidated",
)
```

The filter only fires on chunks whose `metadata.tier` is non-NULL, so non-memory chunks always pass through. Mixed corpora are safe.

### Pattern 5 — picking a retrieval strategy per call

```python
# Most queries: default weighted, safe everywhere
result = await rag.ask(q)

# Known-broad question on this single-namespace corpus: vector_first for 60× speedup
result = await rag.ask(
    q,
    retrieval_strategy="vector_first",  # HNSW-eligible CTE
)

# Known-selective predicate, you've added the right index: pre_filter
result = await rag.ask(
    q,
    retrieval_strategy="pre_filter",
)
```

See [`retrieval-strategy.md`](retrieval-strategy.md) for the full decision matrix and bench numbers.

## Composing multiple kwargs

The kwargs compose. Each adds its WHERE clause (or scoring term) independently:

```python
from datetime import datetime, timezone

result = await rag.ask(
    "What's the latest authoritative answer?",
    namespace="docs",
    version_filter="3.12",                                  # content scope
    retracted_behavior="hide",                              # scoring (tier-gated)
    supersession_behavior="hide",                           # scoring (tier-gated)
    as_of=datetime(2025, 1, 1, tzinfo=timezone.utc),        # scoring (tier-gated)
    memory_tier="consolidated",                             # content scope
    retrieval_strategy="vector_first",                      # SQL shape
)
```

Order doesn't matter; each kwarg is independent. The validator rejects invalid values at the boundary (e.g., `retracted_behavior="bogus"` raises `ValueError` at call time, not silently in SQL).

## When to mutate config vs use the kwarg

| You want | Use |
|---|---|
| One global default for the whole process | `config.retracted_behavior = "hide"` at startup |
| Per-call decision in a multi-tenant server | per-call kwarg |
| Stable behavior for a long-lived job loop | per-call kwarg passed once at job start |
| Toggle for an admin "debug view" UI | per-call kwarg from the UI controller |
| A/B test of policy in production | per-call kwarg from the AB-test selector |

The mutate-config pattern is a smell when there's more than one caller. It existed pre-arc because the kwarg didn't. Now it doesn't have to.

## Backward compatibility

All kwargs default to `None`. Existing call sites that don't pass them get config-driven behavior identical to pre-arc. The per-call shape is purely additive.

## Source-level pins

The tier-gated semantics are pinned in:

- [`tests/unit/test_retracted_behavior_override.py`](../../tests/unit/test_retracted_behavior_override.py) — `retracted_behavior` per-call
- [`tests/unit/test_supersession_behavior_override.py`](../../tests/unit/test_supersession_behavior_override.py) — `supersession_behavior` per-call
- [`tests/unit/test_memory_tier_override.py`](../../tests/unit/test_memory_tier_override.py) — `memory_tier` filter
- [`tests/unit/test_retrieval_strategy.py`](../../tests/unit/test_retrieval_strategy.py) — `retrieval_strategy` SQL shapes
- [`tests/unit/test_version_fields_tier_off.py`](../../tests/unit/test_version_fields_tier_off.py) — `version_filter` + `version_label` tier-independence (#17, #18)

If a future refactor regresses any of these, the source-level pins fail loudly.

## See also

- [`docs/EVOLUTION-API-QUICKREF.md`](../EVOLUTION-API-QUICKREF.md) — the per-call vs config-default decision matrix at API level
- [`retrieval-strategy.md`](retrieval-strategy.md) — `retrieval_strategy` deep dive with bench numbers
- [`metadata-indexes.md`](metadata-indexes.md) — how `memory_tier` chunks get their `metadata.tier` field stamped at ingest
- [`chunkshop-integration.md`](chunkshop-integration.md) — Pattern M (SP-A bridge), where `memory_tier="consolidated"` is the O2 rule
