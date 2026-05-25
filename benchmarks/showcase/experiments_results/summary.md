# 10-strategy summarization bake-off

Datasets: mhr, musique, twowiki | subset=30 | top_k=10 | gen=gpt-5-mini

## Overall

| strategy | n | avg ctx tokens | tok reduction | accuracy | avg latency ms |
|---|---|---|---|---|---|
| chunks | 90 | 2491 | 0% | 53% | 631 |
| summary_facts | 90 | 826 | 67% | 50% | 983 |
| summary | 90 | 497 | 80% | 46% | 1043 |
| summary_long | 90 | 957 | 62% | 46% | 901 |
| summary_plus_top2 | 90 | 973 | 61% | 44% | 1007 |
| hint_focus_high | 90 | 490 | 80% | 44% | 889 |
| per_chunk_facts | 90 | 517 | 79% | 37% | 807 |
| facts_only | 90 | 407 | 84% | 32% | 826 |
| per_chunk_summary | 90 | 432 | 83% | 30% | 925 |
| correlate_facts | 90 | 1466 | 41% | 22% | 1001 |

## mhr

| strategy | n | avg ctx tokens | tok reduction | accuracy | avg latency ms |
|---|---|---|---|---|---|
| chunks | 30 | 4627 | 0% | 67% | 655 |
| summary_facts | 30 | 843 | 82% | 67% | 838 |
| summary_long | 30 | 906 | 80% | 60% | 851 |
| per_chunk_facts | 30 | 625 | 86% | 60% | 1095 |
| summary_plus_top2 | 30 | 1365 | 70% | 60% | 1373 |
| summary | 30 | 463 | 90% | 57% | 860 |
| per_chunk_summary | 30 | 473 | 90% | 57% | 751 |
| hint_focus_high | 30 | 449 | 90% | 57% | 1011 |
| correlate_facts | 30 | 1233 | 73% | 50% | 803 |
| facts_only | 30 | 464 | 90% | 47% | 873 |

## musique

| strategy | n | avg ctx tokens | tok reduction | accuracy | avg latency ms |
|---|---|---|---|---|---|
| chunks | 30 | 1271 | 0% | 43% | 567 |
| summary | 30 | 496 | 61% | 38% | 1460 |
| summary_long | 30 | 939 | 26% | 33% | 796 |
| hint_focus_high | 30 | 491 | 61% | 33% | 868 |
| summary_facts | 30 | 789 | 38% | 30% | 803 |
| summary_plus_top2 | 30 | 755 | 41% | 30% | 766 |
| per_chunk_summary | 30 | 409 | 68% | 17% | 913 |
| per_chunk_facts | 30 | 414 | 67% | 17% | 642 |
| facts_only | 30 | 321 | 75% | 13% | 797 |
| correlate_facts | 30 | 1187 | 7% | 3% | 1404 |

## twowiki

| strategy | n | avg ctx tokens | tok reduction | accuracy | avg latency ms |
|---|---|---|---|---|---|
| summary_facts | 30 | 846 | 46% | 53% | 1307 |
| chunks | 30 | 1574 | 0% | 50% | 672 |
| summary | 30 | 532 | 66% | 43% | 808 |
| summary_long | 30 | 1026 | 35% | 43% | 1055 |
| summary_plus_top2 | 30 | 800 | 49% | 43% | 883 |
| hint_focus_high | 30 | 529 | 66% | 43% | 788 |
| facts_only | 30 | 436 | 72% | 37% | 808 |
| per_chunk_facts | 30 | 511 | 68% | 33% | 684 |
| per_chunk_summary | 30 | 413 | 74% | 17% | 1112 |
| correlate_facts | 30 | 1979 | -26% | 13% | 797 |
