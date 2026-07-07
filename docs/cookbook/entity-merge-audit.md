# Entity merge auditing & description caps

Two ingest-time protections for the entity-resolution layer (PR-222, AAT-004):
a hard cap on description growth, and an audit log for every fuzzy merge so
false merges are detectable and repairable.

## Why

Fuzzy resolution merges an incoming entity into an existing one when
`0.4*trgm + 0.6*vec >= resolution_threshold` (0.85 default). Two failure
modes used to be silent:

1. **Unbounded descriptions** — every merge appended the new description.
   A hot entity mentioned in 500 chunks grew a multi-KB blob that was
   re-embedded on every merge and dragged into every context.
2. **False merges with no record and no undo** — "PostgreSQL 14" absorbing
   "PostgreSQL 15" corrupted the graph permanently; the only fix was full
   re-ingest, and you found out from wrong answers.

## Description cap

`entity_description_max_chars` (default 2000, env
`PGRG_ENTITY_DESCRIPTION_MAX_CHARS`, `0` disables) is enforced at every
write path — exact-match append, fuzzy merge, per-document dedupe, deferred
backfill, and `merge_entities()`. Semantics are **keep-first**: the oldest
(usually most canonical) text survives; novel text is appended until the cap.

The cap applies on the next merge. Corpora ingested before the cap may
already carry bloated rows — trim them once per namespace:

```python
trimmed = await rag.trim_entity_descriptions()          # configured namespace
trimmed = await rag.trim_entity_descriptions("docs_v2") # explicit namespace
```

Equivalent SQL, if you prefer psql:

```sql
UPDATE entities SET description = left(description, 2000)
WHERE namespace = 'docs_v2' AND length(description) > 2000;
```

Trimming does not re-embed; the entity's next merge refreshes its embedding.

## Merge audit log

Every fuzzy auto-merge and every manual `merge_entities()` call writes a row
to `entity_merge_log` (migration 017): namespace, surviving `kept_id`, the
absorbed entity's name/type/description/properties, the trgm/vec/combined
scores that triggered it, document provenance, and a timestamp. Exact-name
matches are not merges and are not logged.

Audit from Python:

```python
rows = await rag.entity_merges()                       # newest first
rows = await rag.entity_merges(since="2026-07-01",     # ISO string or datetime
                               min_score=0.86)         # borderline auto-merges
```

Or from the CLI:

```bash
pgrg merges                          # last 50 in the configured namespace
pgrg merges -n docs_v2 --min-score 0.86 --limit 20
```

Rows just above `resolution_threshold` are the ones to eyeball — they're the
borderline calls most likely to be false merges.

## Undoing a false merge

```python
new_id = await rag.split_entity(log_id)   # log_id from entity_merges()
```

`split_entity` recreates the absorbed entity from the logged snapshot (name,
type, description, properties, fresh embedding) and **repoints nothing** —
relationships and entity_chunks rewritten at merge time stay where they are.
It's a manual repair aid: re-link what matters by hand, or re-ingest the
affected documents (the log row carries `document_id`). It refuses if an
entity with that name already exists in the namespace.

## Version guard

Names that differ only by a version-like token never fuzzy-merge, regardless
of score: "PostgreSQL 14" / "PostgreSQL 15", "Python 3.11" / "3.12". This
generalizes the CODE_SYMBOL exemption to the versioned-docs workload. The
token pattern is `entity_version_guard_pattern` (default `\d+(?:\.\d+)*`,
env `PGRG_ENTITY_VERSION_GUARD_PATTERN`); set it to an empty string to
disable, or widen it for corpora with other version-shaped tokens.
