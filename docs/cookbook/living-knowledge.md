# Living Knowledge

Living Knowledge is for high-churn records where the current state changes
often enough that naive append-only ingest would create too many duplicated
retrievable documents.

The model is deliberately simple:

- store one coherent materialized full document per logical object per cadence bucket;
- overwrite updates inside the same bucket;
- create a new materialized document when the bucket changes;
- optionally write a hash-level audit log;
- do not embed diffs by default.

This is not full event sourcing. Diffs are useful for audit, but coherent
materialized documents are the right retrieval and embedding unit.

## When To Use It

Use Living Knowledge when a source object changes multiple times per day:

- CRM accounts
- support tickets
- customer health summaries
- agent memory state
- inventory or operational records
- project status pages generated from a system of record

Do not use it for slow-changing files where the normal `source_id` replacement
behavior is enough.

## Basic Usage

```python
await rag.ingest_records(
    [
        {
            "source_id": "event:987",
            "text": """
            Account: Acme
            Status: active
            Owner: Priya
            Renewal risk: medium
            Next step: send SOC2 report by Friday.
            """,
            "metadata": {
                "account_id": "account:acme",
                "effective_from": updated_at,
            },
        }
    ],
    namespace="crm",
    living_knowledge=True,
    living_key="account_id",
    living_cadence="day",
)
```

With the default daily cadence, all updates for `account:acme` on
`2026-05-25` map to:

```text
living://crm/account:acme/day/2026-05-25
```

If the account changes five times that day, pg-raggraph keeps replacing that
one materialized document. On `2026-05-26`, it creates a new document and marks
the prior bucket as no longer current.

## Configuration

Constructor-level defaults:

```python
rag = GraphRAG(
    namespace="crm",
    living_knowledge=True,
    living_key="account_id",
    living_cadence="day",       # hour | day | week | month
    living_current_only=True,   # latest queries ignore old living buckets
    living_audit_diffs=False,   # optional hash-level audit log
)
```

Per-call overrides:

```python
await rag.ingest_records(
    records,
    namespace="crm",
    living_knowledge=True,
    living_key="ticket_id",
    living_cadence="hour",
    living_audit_diffs=True,
)
```

## What Gets Stored

Each materialized document gets metadata like:

```json
{
  "logical_id": "account:acme",
  "living_logical_id": "account:acme",
  "living_source_id": "event:987",
  "living_cadence": "day",
  "living_bucket": "2026-05-25",
  "living_current": true,
  "effective_from": "2026-05-25T00:00:00+00:00",
  "version_label": "day:2026-05-25"
}
```

When a new bucket arrives, the previous current bucket is updated:

```json
{
  "living_current": false,
  "effective_to": "2026-05-26T00:00:00+00:00"
}
```

Latest retrieval for a `GraphRAG(living_knowledge=True)` instance filters out
old living buckets by default. Historical `as_of` queries bypass the current
filter so the temporal window can select older buckets.

## Optional Audit Log

Set `living_audit_diffs=True` to write rows to `living_audit_log` when:

- an update overwrites a document inside the same bucket;
- a new bucket supersedes the previous current bucket.

The audit log stores hashes and metadata, not retrievable chunks. It exists to
answer "what changed?" operationally without polluting semantic retrieval.

## Choosing A Cadence

Use the coarsest cadence that matches the business question.

| Cadence | Use When |
|---|---|
| `hour` | Operations change rapidly and hour-level history matters. |
| `day` | Default for business records that change several times per day. |
| `week` | Weekly status summaries, project plans, account health. |
| `month` | Low-resolution archival history. |

For 4-5 updates per hour, start with `day`. Move to `hour` only when users ask
questions that really need hour-level historical state.

## Retrieval Profiles

For living KB namespaces:

- use `balanced` for general current-state questions;
- use `stacked` for conversational or agent-memory state;
- use `accurate` for high-stakes historical questions;
- use `raw` for debugging.

Example:

```python
await rag.ask(
    "What is the current renewal risk for Acme?",
    namespace="crm",
    profile="balanced",
)
```

## Chunkshop Notes

When feeding pg-raggraph from chunkshop, use chunkshop to build the coherent
materialized document or pre-chunked representation. Do not send every small
diff as a separately embedded document.

Recommended pattern:

```text
source events / diffs
  -> chunkshop or app-level consolidation
  -> one coherent materialized doc
  -> pg-raggraph ingest_records(..., living_knowledge=True)
```

For agent memory:

- provisional raw observations can stay in chunkshop or a short-retention log;
- consolidated memory should be written as materialized living documents;
- retrieval should usually target the consolidated namespace with
  `profile="stacked"` or `profile="balanced"`.

Before releasing this path, verify the latest chunkshop compatibility fix is
included and smoke-test pre-chunked living records.
