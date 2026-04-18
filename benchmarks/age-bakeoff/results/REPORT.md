# AGE vs pg-raggraph Bake-off Report

## Overview

- **Engines**: age, pgrg
- **Corpora**: acme, scotus
- **Total data points**: 360

## Corpus: acme

### Retrieval Latency (ms)

| Engine | p50 | p95 | p99 | mean | n |
|--------|-----|-----|-----|------|---|
| age | 47.3 | 58.3 | 71.9 | 48.7 | 90 |
| pgrg | 33.1 | 47.4 | 79.6 | 36.7 | 90 |

### Answer Generation Latency (ms)

| Engine | p50 | p95 | p99 | mean | n |
|--------|-----|-----|-----|------|---|
| age | 803.6 | 1799.5 | 2488.1 | 949.2 | 90 |
| pgrg | 807.0 | 1740.9 | 3156.4 | 981.7 | 90 |

### LLM Judge Verdicts

| Engine | Fully Correct | Partially | Wrong | Hallucinated | n |
|--------|--------------|-----------|-------|--------------|---|
| age | 6 | 12 | 12 | 0 | 30 |
| pgrg | 5 | 12 | 10 | 3 | 30 |

### Per-Question-Class Latency Breakdown

**age**

| Question Class | p50 (ms) | mean (ms) | n |
|----------------|----------|-----------|---|
| semantic | 47.6 | 49.2 | 24 |
| single_hop | 47.1 | 48.9 | 30 |
| multi_hop_bridging | 48.8 | 50.6 | 18 |
| factual | 44.1 | 45.8 | 18 |

**pgrg**

| Question Class | p50 (ms) | mean (ms) | n |
|----------------|----------|-----------|---|
| semantic | 31.8 | 33.6 | 24 |
| single_hop | 32.0 | 34.7 | 30 |
| multi_hop_bridging | 33.5 | 36.1 | 18 |
| factual | 35.3 | 44.6 | 18 |

## Corpus: scotus

### Retrieval Latency (ms)

| Engine | p50 | p95 | p99 | mean | n |
|--------|-----|-----|-----|------|---|
| age | 2862.5 | 3292.6 | 3573.1 | 2873.5 | 90 |
| pgrg | 60.3 | 79.2 | 86.5 | 62.3 | 90 |

### Answer Generation Latency (ms)

| Engine | p50 | p95 | p99 | mean | n |
|--------|-----|-----|-----|------|---|
| age | 1246.8 | 2104.9 | 2951.0 | 1307.4 | 90 |
| pgrg | 1207.1 | 2633.6 | 3298.0 | 1361.0 | 90 |

### LLM Judge Verdicts

| Engine | Fully Correct | Partially | Wrong | Hallucinated | n |
|--------|--------------|-----------|-------|--------------|---|
| age | 11 | 6 | 13 | 0 | 30 |
| pgrg | 11 | 5 | 14 | 0 | 30 |

### Per-Question-Class Latency Breakdown

**age**

| Question Class | p50 (ms) | mean (ms) | n |
|----------------|----------|-----------|---|
| semantic | 2718.6 | 2735.6 | 24 |
| single_hop | 2854.8 | 2928.4 | 30 |
| multi_hop_bridging | 3119.5 | 3075.2 | 18 |
| factual | 2835.7 | 2764.0 | 18 |

**pgrg**

| Question Class | p50 (ms) | mean (ms) | n |
|----------------|----------|-----------|---|
| semantic | 59.4 | 60.0 | 24 |
| single_hop | 60.3 | 61.2 | 30 |
| multi_hop_bridging | 63.1 | 65.7 | 18 |
| factual | 60.5 | 63.5 | 18 |

## What This Means

This benchmark measures whether pg-raggraph's approach (recursive CTEs + pgvector in plain PostgreSQL) delivers comparable or better retrieval quality and latency versus Apache AGE's Cypher-based graph traversal.

Key metrics to compare:
- **Retrieval latency p50/p95**: raw speed of getting relevant chunks
- **Fact recall**: are the retrieved chunks covering the required facts?
- **LLM judge accuracy**: do the generated answers match the gold standard?
- **Multi-hop bridging**: where graph traversal matters most

## Where AGE Wins

This section highlights any categories where AGE outperforms pg-raggraph. If AGE shows advantages in specific question classes or corpus types, those findings inform whether Cypher queries provide value beyond what recursive CTEs achieve.


If this section is empty after running the benchmark, pg-raggraph's approach is validated across all tested dimensions.
