# Multi-Tenant Load Result — 2026-05-20

Harness: `benchmarks/scale/run_multitenant_load.py`

Shape:

- 50 namespaces
- 2,000 chunks per namespace
- 100,000 total chunks
- 200 concurrent queries per mode
- top_k: 5
- p99 target: 10,000 ms

Results:

| Mode | p50 ms | p95 ms | p99 ms | Max ms | Query errors | Cross-tenant leaks | Empty results | Short results |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| two-stage on | 762.9 | 876.3 | 881.0 | 884.6 | 0 | 0 | 0 | 0 |
| two-stage off | 785.7 | 898.5 | 902.1 | 902.8 | 0 | 0 | 0 | 0 |

Two-stage p99 delta vs single-stage: -21.1 ms.

Pool exhaustion: false.

DSN: `postgresql://***:***@localhost:5434/pg_raggraph`
