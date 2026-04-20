# AGE vs pg-raggraph Bake-off Report

## Overview

- **Engines**: age, pgrg
- **Corpora**: acme, acme__global, acme__local, acme__naive, acme__naive-boost, acme__smart, scotus, scotus__global, scotus__hier_global, scotus__hier_hybrid, scotus__hier_local, scotus__hier_naive, scotus__hier_naive_boost, scotus__hier_smart, scotus__local, scotus__naive, scotus__naive-boost, scotus__smart
- **Total data points**: 3240

## Corpus: acme

### Retrieval Latency (ms)

| Engine | p50 | p95 | p99 | mean | n |
|--------|-----|-----|-----|------|---|
| age | 45.9 | 60.0 | 130.1 | 49.4 | 90 |
| pgrg | 32.6 | 50.7 | 78.7 | 35.9 | 90 |

### Answer Generation Latency (ms)

| Engine | p50 | p95 | p99 | mean | n |
|--------|-----|-----|-----|------|---|
| age | 834.7 | 1625.4 | 2103.2 | 907.6 | 90 |
| pgrg | 793.0 | 1507.1 | 1927.1 | 866.9 | 90 |

### Fact Recall

| Engine | Mean | Min | Max | n |
|--------|------|-----|-----|---|
| age | 0.909 | 0.333 | 1.000 | 30 |
| pgrg | 0.909 | 0.333 | 1.000 | 30 |

### LLM Judge Verdicts

| Engine | Fully Correct | Partially | Wrong | Hallucinated | n |
|--------|--------------|-----------|-------|--------------|---|
| age | 5 | 11 | 11 | 3 | 30 |
| pgrg | 5 | 12 | 10 | 3 | 30 |

### Per-Question-Class Latency Breakdown

**age**

| Question Class | p50 (ms) | mean (ms) | n |
|----------------|----------|-----------|---|
| semantic | 47.6 | 54.4 | 24 |
| single_hop | 43.9 | 44.9 | 30 |
| multi_hop_bridging | 47.5 | 52.3 | 18 |
| factual | 47.3 | 47.1 | 18 |

**pgrg**

| Question Class | p50 (ms) | mean (ms) | n |
|----------------|----------|-----------|---|
| semantic | 32.9 | 34.3 | 24 |
| single_hop | 31.3 | 31.3 | 30 |
| multi_hop_bridging | 33.5 | 36.0 | 18 |
| factual | 32.8 | 45.6 | 18 |

## Corpus: acme__global

### Retrieval Latency (ms)

| Engine | p50 | p95 | p99 | mean | n |
|--------|-----|-----|-----|------|---|
| age | 51.4 | 213.1 | 382.4 | 71.3 | 90 |
| pgrg | 57.2 | 115.5 | 243.7 | 61.9 | 90 |

### Answer Generation Latency (ms)

| Engine | p50 | p95 | p99 | mean | n |
|--------|-----|-----|-----|------|---|
| age | 762.7 | 1520.8 | 1993.4 | 812.0 | 90 |
| pgrg | 723.0 | 1355.1 | 1798.8 | 777.7 | 90 |

### Fact Recall

| Engine | Mean | Min | Max | n |
|--------|------|-----|-----|---|
| age | 0.909 | 0.333 | 1.000 | 30 |
| pgrg | 0.909 | 0.333 | 1.000 | 30 |

### LLM Judge Verdicts

| Engine | Fully Correct | Partially | Wrong | Hallucinated | n |
|--------|--------------|-----------|-------|--------------|---|
| age | 6 | 12 | 11 | 1 | 30 |
| pgrg | 7 | 12 | 9 | 2 | 30 |

### Per-Question-Class Latency Breakdown

**age**

| Question Class | p50 (ms) | mean (ms) | n |
|----------------|----------|-----------|---|
| semantic | 51.4 | 59.8 | 24 |
| single_hop | 49.5 | 67.7 | 30 |
| multi_hop_bridging | 55.6 | 91.7 | 18 |
| factual | 48.8 | 72.1 | 18 |

**pgrg**

| Question Class | p50 (ms) | mean (ms) | n |
|----------------|----------|-----------|---|
| semantic | 62.4 | 53.2 | 24 |
| single_hop | 55.0 | 58.6 | 30 |
| multi_hop_bridging | 60.5 | 61.7 | 18 |
| factual | 45.4 | 79.4 | 18 |

## Corpus: acme__local

### Retrieval Latency (ms)

| Engine | p50 | p95 | p99 | mean | n |
|--------|-----|-----|-----|------|---|
| age | 45.1 | 57.9 | 68.0 | 46.8 | 90 |
| pgrg | 31.5 | 391.6 | 461.4 | 121.5 | 90 |

### Answer Generation Latency (ms)

| Engine | p50 | p95 | p99 | mean | n |
|--------|-----|-----|-----|------|---|
| age | 827.4 | 1328.1 | 1729.2 | 859.7 | 90 |
| pgrg | 779.7 | 1316.3 | 1655.8 | 845.0 | 90 |

### Fact Recall

| Engine | Mean | Min | Max | n |
|--------|------|-----|-----|---|
| age | 0.909 | 0.333 | 1.000 | 30 |
| pgrg | 0.909 | 0.333 | 1.000 | 30 |

### LLM Judge Verdicts

| Engine | Fully Correct | Partially | Wrong | Hallucinated | n |
|--------|--------------|-----------|-------|--------------|---|
| age | 4 | 12 | 11 | 3 | 30 |
| pgrg | 6 | 12 | 10 | 2 | 30 |

### Per-Question-Class Latency Breakdown

**age**

| Question Class | p50 (ms) | mean (ms) | n |
|----------------|----------|-----------|---|
| semantic | 44.0 | 45.3 | 24 |
| single_hop | 43.9 | 47.4 | 30 |
| multi_hop_bridging | 45.7 | 46.9 | 18 |
| factual | 48.1 | 47.9 | 18 |

**pgrg**

| Question Class | p50 (ms) | mean (ms) | n |
|----------------|----------|-----------|---|
| semantic | 29.2 | 31.5 | 24 |
| single_hop | 30.0 | 94.5 | 30 |
| multi_hop_bridging | 30.1 | 30.6 | 18 |
| factual | 373.3 | 377.2 | 18 |

## Corpus: acme__naive

### Retrieval Latency (ms)

| Engine | p50 | p95 | p99 | mean | n |
|--------|-----|-----|-----|------|---|
| age | 47.1 | 56.9 | 62.8 | 48.0 | 90 |
| pgrg | 21.0 | 30.8 | 59.1 | 23.9 | 90 |

### Answer Generation Latency (ms)

| Engine | p50 | p95 | p99 | mean | n |
|--------|-----|-----|-----|------|---|
| age | 711.1 | 1396.1 | 1815.7 | 805.9 | 90 |
| pgrg | 765.7 | 1282.5 | 1923.0 | 809.7 | 90 |

### Fact Recall

| Engine | Mean | Min | Max | n |
|--------|------|-----|-----|---|
| age | 0.909 | 0.333 | 1.000 | 30 |
| pgrg | 0.909 | 0.333 | 1.000 | 30 |

### LLM Judge Verdicts

| Engine | Fully Correct | Partially | Wrong | Hallucinated | n |
|--------|--------------|-----------|-------|--------------|---|
| age | 4 | 12 | 11 | 3 | 30 |
| pgrg | 4 | 12 | 11 | 3 | 30 |

### Per-Question-Class Latency Breakdown

**age**

| Question Class | p50 (ms) | mean (ms) | n |
|----------------|----------|-----------|---|
| semantic | 46.7 | 48.2 | 24 |
| single_hop | 46.9 | 47.3 | 30 |
| multi_hop_bridging | 49.3 | 50.2 | 18 |
| factual | 44.6 | 46.7 | 18 |

**pgrg**

| Question Class | p50 (ms) | mean (ms) | n |
|----------------|----------|-----------|---|
| semantic | 21.6 | 22.9 | 24 |
| single_hop | 19.2 | 20.5 | 30 |
| multi_hop_bridging | 22.3 | 22.6 | 18 |
| factual | 21.5 | 32.0 | 18 |

## Corpus: acme__naive-boost

### Retrieval Latency (ms)

| Engine | p50 | p95 | p99 | mean | n |
|--------|-----|-----|-----|------|---|
| age | 46.9 | 57.6 | 69.3 | 48.4 | 90 |
| pgrg | 21.5 | 36.2 | 94.4 | 28.5 | 90 |

### Answer Generation Latency (ms)

| Engine | p50 | p95 | p99 | mean | n |
|--------|-----|-----|-----|------|---|
| age | 661.7 | 1710.4 | 3346.3 | 888.1 | 90 |
| pgrg | 700.0 | 1451.3 | 2655.4 | 793.7 | 90 |

### Fact Recall

| Engine | Mean | Min | Max | n |
|--------|------|-----|-----|---|
| age | 0.909 | 0.333 | 1.000 | 30 |
| pgrg | 0.909 | 0.333 | 1.000 | 30 |

### LLM Judge Verdicts

| Engine | Fully Correct | Partially | Wrong | Hallucinated | n |
|--------|--------------|-----------|-------|--------------|---|
| age | 4 | 12 | 11 | 3 | 30 |
| pgrg | 4 | 12 | 12 | 2 | 30 |

### Per-Question-Class Latency Breakdown

**age**

| Question Class | p50 (ms) | mean (ms) | n |
|----------------|----------|-----------|---|
| semantic | 47.6 | 49.5 | 24 |
| single_hop | 46.5 | 47.8 | 30 |
| multi_hop_bridging | 48.5 | 48.8 | 18 |
| factual | 47.2 | 47.6 | 18 |

**pgrg**

| Question Class | p50 (ms) | mean (ms) | n |
|----------------|----------|-----------|---|
| semantic | 21.9 | 22.7 | 24 |
| single_hop | 21.0 | 21.9 | 30 |
| multi_hop_bridging | 23.7 | 26.5 | 18 |
| factual | 21.3 | 49.0 | 18 |

## Corpus: acme__smart

### Retrieval Latency (ms)

| Engine | p50 | p95 | p99 | mean | n |
|--------|-----|-----|-----|------|---|
| age | 44.9 | 59.4 | 210.8 | 51.5 | 90 |
| pgrg | 23.0 | 43.2 | 87.9 | 27.8 | 90 |

### Answer Generation Latency (ms)

| Engine | p50 | p95 | p99 | mean | n |
|--------|-----|-----|-----|------|---|
| age | 736.2 | 1337.4 | 2041.8 | 816.2 | 90 |
| pgrg | 771.6 | 1629.1 | 2736.0 | 944.2 | 90 |

### Fact Recall

| Engine | Mean | Min | Max | n |
|--------|------|-----|-----|---|
| age | 0.909 | 0.333 | 1.000 | 30 |
| pgrg | 0.909 | 0.333 | 1.000 | 30 |

### LLM Judge Verdicts

| Engine | Fully Correct | Partially | Wrong | Hallucinated | n |
|--------|--------------|-----------|-------|--------------|---|
| age | 4 | 11 | 11 | 4 | 30 |
| pgrg | 6 | 13 | 10 | 1 | 30 |

### Per-Question-Class Latency Breakdown

**age**

| Question Class | p50 (ms) | mean (ms) | n |
|----------------|----------|-----------|---|
| semantic | 44.8 | 46.5 | 24 |
| single_hop | 43.5 | 44.9 | 30 |
| multi_hop_bridging | 46.0 | 57.1 | 18 |
| factual | 44.8 | 63.5 | 18 |

**pgrg**

| Question Class | p50 (ms) | mean (ms) | n |
|----------------|----------|-----------|---|
| semantic | 22.9 | 24.1 | 24 |
| single_hop | 23.2 | 25.4 | 30 |
| multi_hop_bridging | 22.4 | 26.3 | 18 |
| factual | 26.9 | 38.2 | 18 |

## Corpus: scotus

### Retrieval Latency (ms)

| Engine | p50 | p95 | p99 | mean | n |
|--------|-----|-----|-----|------|---|
| age | 2361.1 | 2715.0 | 3104.8 | 2345.6 | 90 |
| pgrg | 70.3 | 192.8 | 232.4 | 89.3 | 90 |

### Answer Generation Latency (ms)

| Engine | p50 | p95 | p99 | mean | n |
|--------|-----|-----|-----|------|---|
| age | 961.4 | 1969.9 | 2448.1 | 1129.9 | 90 |
| pgrg | 1045.2 | 1824.9 | 2589.7 | 1163.7 | 90 |

### Fact Recall

| Engine | Mean | Min | Max | n |
|--------|------|-----|-----|---|
| age | 0.558 | 0.000 | 1.000 | 30 |
| pgrg | 0.518 | 0.000 | 1.000 | 30 |

### LLM Judge Verdicts

| Engine | Fully Correct | Partially | Wrong | Hallucinated | n |
|--------|--------------|-----------|-------|--------------|---|
| age | 11 | 7 | 12 | 0 | 30 |
| pgrg | 10 | 6 | 14 | 0 | 30 |

### Per-Question-Class Latency Breakdown

**age**

| Question Class | p50 (ms) | mean (ms) | n |
|----------------|----------|-----------|---|
| semantic | 2176.6 | 2184.5 | 24 |
| single_hop | 2368.2 | 2432.4 | 30 |
| multi_hop_bridging | 2537.2 | 2500.3 | 18 |
| factual | 2303.6 | 2260.9 | 18 |

**pgrg**

| Question Class | p50 (ms) | mean (ms) | n |
|----------------|----------|-----------|---|
| semantic | 61.9 | 66.0 | 24 |
| single_hop | 86.9 | 103.4 | 30 |
| multi_hop_bridging | 65.4 | 68.9 | 18 |
| factual | 79.4 | 117.0 | 18 |

## Corpus: scotus__global

### Retrieval Latency (ms)

| Engine | p50 | p95 | p99 | mean | n |
|--------|-----|-----|-----|------|---|
| age | 2445.1 | 2854.2 | 3122.9 | 2446.8 | 90 |
| pgrg | 27.6 | 42.1 | 55.2 | 30.6 | 90 |

### Answer Generation Latency (ms)

| Engine | p50 | p95 | p99 | mean | n |
|--------|-----|-----|-----|------|---|
| age | 988.5 | 1617.5 | 1991.1 | 1057.7 | 90 |
| pgrg | 955.1 | 1888.5 | 2764.4 | 1083.4 | 90 |

### Fact Recall

| Engine | Mean | Min | Max | n |
|--------|------|-----|-----|---|
| age | 0.558 | 0.000 | 1.000 | 30 |
| pgrg | 0.488 | 0.000 | 0.800 | 30 |

### LLM Judge Verdicts

| Engine | Fully Correct | Partially | Wrong | Hallucinated | n |
|--------|--------------|-----------|-------|--------------|---|
| age | 12 | 5 | 13 | 0 | 30 |
| pgrg | 10 | 7 | 13 | 0 | 30 |

### Per-Question-Class Latency Breakdown

**age**

| Question Class | p50 (ms) | mean (ms) | n |
|----------------|----------|-----------|---|
| semantic | 2315.1 | 2312.8 | 24 |
| single_hop | 2441.9 | 2505.0 | 30 |
| multi_hop_bridging | 2703.3 | 2650.7 | 18 |
| factual | 2402.9 | 2324.5 | 18 |

**pgrg**

| Question Class | p50 (ms) | mean (ms) | n |
|----------------|----------|-----------|---|
| semantic | 28.1 | 32.6 | 24 |
| single_hop | 26.6 | 29.6 | 30 |
| multi_hop_bridging | 28.7 | 31.2 | 18 |
| factual | 27.2 | 28.8 | 18 |

## Corpus: scotus__hier_global

### Retrieval Latency (ms)

| Engine | p50 | p95 | p99 | mean | n |
|--------|-----|-----|-----|------|---|
| age | 3912.3 | 4774.4 | 5282.1 | 3968.7 | 90 |
| pgrg | 42.9 | 134.0 | 407.4 | 59.4 | 90 |

### Answer Generation Latency (ms)

| Engine | p50 | p95 | p99 | mean | n |
|--------|-----|-----|-----|------|---|
| age | 1090.3 | 1933.4 | 2818.4 | 1198.4 | 90 |
| pgrg | 1031.9 | 1899.7 | 2405.3 | 1171.6 | 90 |

### Fact Recall

| Engine | Mean | Min | Max | n |
|--------|------|-----|-----|---|
| age | 0.868 | 0.333 | 1.000 | 30 |
| pgrg | 0.842 | 0.333 | 1.000 | 30 |

### LLM Judge Verdicts

| Engine | Fully Correct | Partially | Wrong | Hallucinated | n |
|--------|--------------|-----------|-------|--------------|---|
| age | 18 | 8 | 4 | 0 | 30 |
| pgrg | 18 | 8 | 4 | 0 | 30 |

### Per-Question-Class Latency Breakdown

**age**

| Question Class | p50 (ms) | mean (ms) | n |
|----------------|----------|-----------|---|
| semantic | 3797.3 | 3953.5 | 24 |
| single_hop | 3988.1 | 3891.8 | 30 |
| multi_hop_bridging | 4192.7 | 4044.4 | 18 |
| factual | 3889.5 | 4041.2 | 18 |

**pgrg**

| Question Class | p50 (ms) | mean (ms) | n |
|----------------|----------|-----------|---|
| semantic | 43.9 | 44.7 | 24 |
| single_hop | 43.0 | 49.3 | 30 |
| multi_hop_bridging | 45.8 | 64.2 | 18 |
| factual | 40.4 | 91.2 | 18 |

## Corpus: scotus__hier_hybrid

### Retrieval Latency (ms)

| Engine | p50 | p95 | p99 | mean | n |
|--------|-----|-----|-----|------|---|
| age | 3089.0 | 3762.0 | 4045.0 | 3085.1 | 90 |
| pgrg | 72.6 | 89.7 | 141.0 | 79.1 | 90 |

### Answer Generation Latency (ms)

| Engine | p50 | p95 | p99 | mean | n |
|--------|-----|-----|-----|------|---|
| age | 1071.8 | 2250.1 | 2785.2 | 1213.3 | 90 |
| pgrg | 1121.4 | 1974.1 | 2887.4 | 1237.1 | 90 |

### Fact Recall

| Engine | Mean | Min | Max | n |
|--------|------|-----|-----|---|
| age | 0.868 | 0.333 | 1.000 | 30 |
| pgrg | 0.868 | 0.333 | 1.000 | 30 |

### LLM Judge Verdicts

| Engine | Fully Correct | Partially | Wrong | Hallucinated | n |
|--------|--------------|-----------|-------|--------------|---|
| age | 17 | 8 | 5 | 0 | 30 |
| pgrg | 18 | 8 | 4 | 0 | 30 |

### Per-Question-Class Latency Breakdown

**age**

| Question Class | p50 (ms) | mean (ms) | n |
|----------------|----------|-----------|---|
| semantic | 2929.6 | 3038.5 | 24 |
| single_hop | 3109.4 | 3024.1 | 30 |
| multi_hop_bridging | 3263.5 | 3109.3 | 18 |
| factual | 3111.6 | 3225.0 | 18 |

**pgrg**

| Question Class | p50 (ms) | mean (ms) | n |
|----------------|----------|-----------|---|
| semantic | 72.3 | 75.3 | 24 |
| single_hop | 72.0 | 74.2 | 30 |
| multi_hop_bridging | 75.0 | 76.1 | 18 |
| factual | 72.7 | 95.4 | 18 |

## Corpus: scotus__hier_local

### Retrieval Latency (ms)

| Engine | p50 | p95 | p99 | mean | n |
|--------|-----|-----|-----|------|---|
| age | 3079.3 | 3877.5 | 3995.5 | 3096.6 | 90 |
| pgrg | 64.6 | 83.4 | 254.0 | 70.6 | 90 |

### Answer Generation Latency (ms)

| Engine | p50 | p95 | p99 | mean | n |
|--------|-----|-----|-----|------|---|
| age | 1063.5 | 1999.0 | 2214.7 | 1149.7 | 90 |
| pgrg | 1068.2 | 2336.4 | 2818.2 | 1243.2 | 90 |

### Fact Recall

| Engine | Mean | Min | Max | n |
|--------|------|-----|-----|---|
| age | 0.868 | 0.333 | 1.000 | 30 |
| pgrg | 0.868 | 0.333 | 1.000 | 30 |

### LLM Judge Verdicts

| Engine | Fully Correct | Partially | Wrong | Hallucinated | n |
|--------|--------------|-----------|-------|--------------|---|
| age | 17 | 10 | 3 | 0 | 30 |
| pgrg | 18 | 8 | 4 | 0 | 30 |

### Per-Question-Class Latency Breakdown

**age**

| Question Class | p50 (ms) | mean (ms) | n |
|----------------|----------|-----------|---|
| semantic | 2977.0 | 3126.0 | 24 |
| single_hop | 3079.3 | 2983.5 | 30 |
| multi_hop_bridging | 3307.9 | 3150.1 | 18 |
| factual | 3073.6 | 3192.4 | 18 |

**pgrg**

| Question Class | p50 (ms) | mean (ms) | n |
|----------------|----------|-----------|---|
| semantic | 69.4 | 70.7 | 24 |
| single_hop | 62.4 | 64.0 | 30 |
| multi_hop_bridging | 62.0 | 76.9 | 18 |
| factual | 62.3 | 75.0 | 18 |

## Corpus: scotus__hier_naive

### Retrieval Latency (ms)

| Engine | p50 | p95 | p99 | mean | n |
|--------|-----|-----|-----|------|---|
| age | 3874.0 | 4660.7 | 5010.4 | 3855.7 | 90 |
| pgrg | 35.1 | 42.3 | 208.3 | 47.6 | 90 |

### Answer Generation Latency (ms)

| Engine | p50 | p95 | p99 | mean | n |
|--------|-----|-----|-----|------|---|
| age | 1090.8 | 2198.5 | 2672.7 | 1233.5 | 90 |
| pgrg | 1081.8 | 2025.6 | 2810.8 | 1187.2 | 90 |

### Fact Recall

| Engine | Mean | Min | Max | n |
|--------|------|-----|-----|---|
| age | 0.868 | 0.333 | 1.000 | 30 |
| pgrg | 0.868 | 0.333 | 1.000 | 30 |

### LLM Judge Verdicts

| Engine | Fully Correct | Partially | Wrong | Hallucinated | n |
|--------|--------------|-----------|-------|--------------|---|
| age | 18 | 8 | 4 | 0 | 30 |
| pgrg | 18 | 9 | 3 | 0 | 30 |

### Per-Question-Class Latency Breakdown

**age**

| Question Class | p50 (ms) | mean (ms) | n |
|----------------|----------|-----------|---|
| semantic | 3730.6 | 3852.5 | 24 |
| single_hop | 3869.4 | 3757.6 | 30 |
| multi_hop_bridging | 4112.0 | 3924.5 | 18 |
| factual | 3822.6 | 3954.5 | 18 |

**pgrg**

| Question Class | p50 (ms) | mean (ms) | n |
|----------------|----------|-----------|---|
| semantic | 34.5 | 34.7 | 24 |
| single_hop | 35.1 | 37.9 | 30 |
| multi_hop_bridging | 37.0 | 36.4 | 18 |
| factual | 34.9 | 92.2 | 18 |

## Corpus: scotus__hier_naive_boost

### Retrieval Latency (ms)

| Engine | p50 | p95 | p99 | mean | n |
|--------|-----|-----|-----|------|---|
| age | 3898.6 | 4820.1 | 4988.6 | 3929.0 | 90 |
| pgrg | 39.6 | 45.3 | 106.6 | 45.9 | 90 |

### Answer Generation Latency (ms)

| Engine | p50 | p95 | p99 | mean | n |
|--------|-----|-----|-----|------|---|
| age | 1104.0 | 2194.7 | 2861.0 | 1222.9 | 90 |
| pgrg | 1071.0 | 1948.0 | 3294.2 | 1246.2 | 90 |

### Fact Recall

| Engine | Mean | Min | Max | n |
|--------|------|-----|-----|---|
| age | 0.868 | 0.333 | 1.000 | 30 |
| pgrg | 0.868 | 0.333 | 1.000 | 30 |

### LLM Judge Verdicts

| Engine | Fully Correct | Partially | Wrong | Hallucinated | n |
|--------|--------------|-----------|-------|--------------|---|
| age | 18 | 9 | 3 | 0 | 30 |
| pgrg | 17 | 9 | 4 | 0 | 30 |

### Per-Question-Class Latency Breakdown

**age**

| Question Class | p50 (ms) | mean (ms) | n |
|----------------|----------|-----------|---|
| semantic | 3751.9 | 3922.3 | 24 |
| single_hop | 3923.3 | 3842.8 | 30 |
| multi_hop_bridging | 4128.3 | 4014.2 | 18 |
| factual | 3876.3 | 3996.4 | 18 |

**pgrg**

| Question Class | p50 (ms) | mean (ms) | n |
|----------------|----------|-----------|---|
| semantic | 39.8 | 40.1 | 24 |
| single_hop | 38.5 | 39.0 | 30 |
| multi_hop_bridging | 41.7 | 41.9 | 18 |
| factual | 38.7 | 69.3 | 18 |

## Corpus: scotus__hier_smart

### Retrieval Latency (ms)

| Engine | p50 | p95 | p99 | mean | n |
|--------|-----|-----|-----|------|---|
| age | 3226.9 | 4103.7 | 4383.6 | 3255.6 | 90 |
| pgrg | 32.1 | 49.2 | 234.0 | 39.4 | 90 |

### Answer Generation Latency (ms)

| Engine | p50 | p95 | p99 | mean | n |
|--------|-----|-----|-----|------|---|
| age | 1038.1 | 1801.8 | 2825.4 | 1161.8 | 90 |
| pgrg | 1080.3 | 1795.8 | 2274.3 | 1146.8 | 90 |

### Fact Recall

| Engine | Mean | Min | Max | n |
|--------|------|-----|-----|---|
| age | 0.868 | 0.333 | 1.000 | 30 |
| pgrg | 0.868 | 0.333 | 1.000 | 30 |

### LLM Judge Verdicts

| Engine | Fully Correct | Partially | Wrong | Hallucinated | n |
|--------|--------------|-----------|-------|--------------|---|
| age | 18 | 9 | 3 | 0 | 30 |
| pgrg | 17 | 10 | 3 | 0 | 30 |

### Per-Question-Class Latency Breakdown

**age**

| Question Class | p50 (ms) | mean (ms) | n |
|----------------|----------|-----------|---|
| semantic | 3217.5 | 3403.8 | 24 |
| single_hop | 3182.6 | 3099.5 | 30 |
| multi_hop_bridging | 3444.4 | 3269.3 | 18 |
| factual | 3187.7 | 3304.7 | 18 |

**pgrg**

| Question Class | p50 (ms) | mean (ms) | n |
|----------------|----------|-----------|---|
| semantic | 37.0 | 59.9 | 24 |
| single_hop | 26.0 | 27.4 | 30 |
| multi_hop_bridging | 35.7 | 36.8 | 18 |
| factual | 25.0 | 34.7 | 18 |

## Corpus: scotus__local

### Retrieval Latency (ms)

| Engine | p50 | p95 | p99 | mean | n |
|--------|-----|-----|-----|------|---|
| age | 2710.5 | 3143.9 | 3327.2 | 2711.9 | 90 |
| pgrg | 66.2 | 103.4 | 131.6 | 68.0 | 90 |

### Answer Generation Latency (ms)

| Engine | p50 | p95 | p99 | mean | n |
|--------|-----|-----|-----|------|---|
| age | 880.3 | 1738.8 | 2221.7 | 1013.9 | 90 |
| pgrg | 945.0 | 2007.5 | 2635.0 | 1091.0 | 90 |

### Fact Recall

| Engine | Mean | Min | Max | n |
|--------|------|-----|-----|---|
| age | 0.558 | 0.000 | 1.000 | 30 |
| pgrg | 0.518 | 0.000 | 1.000 | 30 |

### LLM Judge Verdicts

| Engine | Fully Correct | Partially | Wrong | Hallucinated | n |
|--------|--------------|-----------|-------|--------------|---|
| age | 11 | 7 | 12 | 0 | 30 |
| pgrg | 9 | 7 | 14 | 0 | 30 |

### Per-Question-Class Latency Breakdown

**age**

| Question Class | p50 (ms) | mean (ms) | n |
|----------------|----------|-----------|---|
| semantic | 2605.4 | 2596.8 | 24 |
| single_hop | 2702.9 | 2782.9 | 30 |
| multi_hop_bridging | 3022.0 | 2934.4 | 18 |
| factual | 2600.3 | 2524.4 | 18 |

**pgrg**

| Question Class | p50 (ms) | mean (ms) | n |
|----------------|----------|-----------|---|
| semantic | 74.2 | 76.2 | 24 |
| single_hop | 58.1 | 60.5 | 30 |
| multi_hop_bridging | 80.7 | 86.6 | 18 |
| factual | 47.0 | 51.2 | 18 |

## Corpus: scotus__naive

### Retrieval Latency (ms)

| Engine | p50 | p95 | p99 | mean | n |
|--------|-----|-----|-----|------|---|
| age | 2174.8 | 2584.2 | 2804.2 | 2184.0 | 90 |
| pgrg | 22.2 | 36.6 | 66.5 | 25.7 | 90 |

### Answer Generation Latency (ms)

| Engine | p50 | p95 | p99 | mean | n |
|--------|-----|-----|-----|------|---|
| age | 810.4 | 1351.6 | 2168.2 | 873.2 | 90 |
| pgrg | 817.2 | 1682.8 | 2191.8 | 950.9 | 90 |

### Fact Recall

| Engine | Mean | Min | Max | n |
|--------|------|-----|-----|---|
| age | 0.558 | 0.000 | 1.000 | 30 |
| pgrg | 0.558 | 0.000 | 1.000 | 30 |

### LLM Judge Verdicts

| Engine | Fully Correct | Partially | Wrong | Hallucinated | n |
|--------|--------------|-----------|-------|--------------|---|
| age | 12 | 6 | 12 | 0 | 30 |
| pgrg | 11 | 8 | 11 | 0 | 30 |

### Per-Question-Class Latency Breakdown

**age**

| Question Class | p50 (ms) | mean (ms) | n |
|----------------|----------|-----------|---|
| semantic | 2060.7 | 2053.3 | 24 |
| single_hop | 2174.8 | 2243.1 | 30 |
| multi_hop_bridging | 2404.5 | 2363.9 | 18 |
| factual | 2139.1 | 2079.8 | 18 |

**pgrg**

| Question Class | p50 (ms) | mean (ms) | n |
|----------------|----------|-----------|---|
| semantic | 22.8 | 24.6 | 24 |
| single_hop | 21.2 | 21.9 | 30 |
| multi_hop_bridging | 24.1 | 26.6 | 18 |
| factual | 22.0 | 32.7 | 18 |

## Corpus: scotus__naive-boost

### Retrieval Latency (ms)

| Engine | p50 | p95 | p99 | mean | n |
|--------|-----|-----|-----|------|---|
| age | 2598.7 | 3013.4 | 3256.8 | 2610.9 | 90 |
| pgrg | 23.9 | 45.7 | 250.5 | 32.4 | 90 |

### Answer Generation Latency (ms)

| Engine | p50 | p95 | p99 | mean | n |
|--------|-----|-----|-----|------|---|
| age | 861.0 | 1482.0 | 2699.7 | 989.6 | 90 |
| pgrg | 838.0 | 1560.4 | 10839.5 | 1345.7 | 90 |

### Fact Recall

| Engine | Mean | Min | Max | n |
|--------|------|-----|-----|---|
| age | 0.558 | 0.000 | 1.000 | 30 |
| pgrg | 0.558 | 0.000 | 1.000 | 30 |

### LLM Judge Verdicts

| Engine | Fully Correct | Partially | Wrong | Hallucinated | n |
|--------|--------------|-----------|-------|--------------|---|
| age | 11 | 7 | 12 | 0 | 30 |
| pgrg | 11 | 8 | 11 | 0 | 30 |

### Per-Question-Class Latency Breakdown

**age**

| Question Class | p50 (ms) | mean (ms) | n |
|----------------|----------|-----------|---|
| semantic | 2470.3 | 2482.9 | 24 |
| single_hop | 2590.9 | 2655.5 | 30 |
| multi_hop_bridging | 2861.6 | 2803.9 | 18 |
| factual | 2594.7 | 2514.2 | 18 |

**pgrg**

| Question Class | p50 (ms) | mean (ms) | n |
|----------------|----------|-----------|---|
| semantic | 24.3 | 26.8 | 24 |
| single_hop | 22.3 | 30.2 | 30 |
| multi_hop_bridging | 26.5 | 30.1 | 18 |
| factual | 24.1 | 45.8 | 18 |

## Corpus: scotus__smart

### Retrieval Latency (ms)

| Engine | p50 | p95 | p99 | mean | n |
|--------|-----|-----|-----|------|---|
| age | 2389.0 | 2805.9 | 3013.2 | 2376.7 | 90 |
| pgrg | 35.5 | 87.8 | 245.4 | 49.7 | 90 |

### Answer Generation Latency (ms)

| Engine | p50 | p95 | p99 | mean | n |
|--------|-----|-----|-----|------|---|
| age | 958.0 | 1701.1 | 2699.7 | 1069.6 | 90 |
| pgrg | 1119.7 | 1732.4 | 1931.7 | 1138.9 | 90 |

### Fact Recall

| Engine | Mean | Min | Max | n |
|--------|------|-----|-----|---|
| age | 0.558 | 0.000 | 1.000 | 30 |
| pgrg | 0.558 | 0.000 | 1.000 | 30 |

### LLM Judge Verdicts

| Engine | Fully Correct | Partially | Wrong | Hallucinated | n |
|--------|--------------|-----------|-------|--------------|---|
| age | 12 | 5 | 13 | 0 | 30 |
| pgrg | 11 | 9 | 10 | 0 | 30 |

### Per-Question-Class Latency Breakdown

**age**

| Question Class | p50 (ms) | mean (ms) | n |
|----------------|----------|-----------|---|
| semantic | 2266.2 | 2259.1 | 24 |
| single_hop | 2376.3 | 2427.2 | 30 |
| multi_hop_bridging | 2567.9 | 2555.9 | 18 |
| factual | 2298.3 | 2270.0 | 18 |

**pgrg**

| Question Class | p50 (ms) | mean (ms) | n |
|----------------|----------|-----------|---|
| semantic | 29.9 | 49.6 | 24 |
| single_hop | 40.0 | 47.7 | 30 |
| multi_hop_bridging | 45.9 | 50.8 | 18 |
| factual | 28.3 | 52.3 | 18 |

## What This Means

This benchmark measures whether pg-raggraph's approach (recursive CTEs + pgvector in plain PostgreSQL) delivers comparable or better retrieval quality and latency versus Apache AGE's Cypher-based graph traversal.

Key metrics to compare:
- **Retrieval latency p50/p95**: raw speed of getting relevant chunks
- **Fact recall**: are the retrieved chunks covering the required facts?
- **LLM judge accuracy**: do the generated answers match the gold standard?
- **Multi-hop bridging**: where graph traversal matters most

## Where AGE Wins

This section highlights any categories where AGE outperforms pg-raggraph. If AGE shows advantages in specific question classes or corpus types, those findings inform whether Cypher queries provide value beyond what recursive CTEs achieve.

- **acme__global**: AGE retrieval p50 is 10% faster (51.4ms vs 57.2ms)

If this section is empty after running the benchmark, pg-raggraph's approach is validated across all tested dimensions.
