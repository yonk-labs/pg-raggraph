# Larger-context grounding sweep

Datasets: mhr | subset=5 | top_ks=10,20,30 | gen=gpt-5-mini

## Overall

| arm | n | avg source tokens | avg ctx tokens | compression | accuracy | latency ms |
|---|---|---|---|---|---|---|
| toc_doc_summary_plus_chunk_summary | 5 | 1410316 | 34634 | 98% | 60% | 2828 |
| llm_prior | 5 | 0 | 0 | n/a | 40% | 2307 |
| chunks_10 | 5 | 4557 | 4557 | 0% | 40% | 1696 |
| chunks_20 | 5 | 9087 | 9087 | 0% | 40% | 972 |
| chunks_30 | 5 | 13676 | 13676 | 0% | 40% | 1047 |
| doc_summary_facts | 5 | 1405759 | 18299 | 99% | 40% | 1044 |
| doc_summary_facts_plus_chunks10 | 5 | 1410316 | 22861 | 98% | 40% | 1208 |
| hint_doc_summary_facts | 5 | 1405759 | 17782 | 99% | 40% | 1172 |
| hint_doc_summary_facts_plus_chunks10 | 5 | 1410316 | 22343 | 98% | 40% | 1091 |

## mhr

| arm | n | avg source tokens | avg ctx tokens | compression | accuracy | latency ms |
|---|---|---|---|---|---|---|
| toc_doc_summary_plus_chunk_summary | 5 | 1410316 | 34634 | 98% | 60% | 2828 |
| llm_prior | 5 | 0 | 0 | n/a | 40% | 2307 |
| chunks_10 | 5 | 4557 | 4557 | 0% | 40% | 1696 |
| chunks_20 | 5 | 9087 | 9087 | 0% | 40% | 972 |
| chunks_30 | 5 | 13676 | 13676 | 0% | 40% | 1047 |
| doc_summary_facts | 5 | 1405759 | 18299 | 99% | 40% | 1044 |
| doc_summary_facts_plus_chunks10 | 5 | 1410316 | 22861 | 98% | 40% | 1208 |
| hint_doc_summary_facts | 5 | 1405759 | 17782 | 99% | 40% | 1172 |
| hint_doc_summary_facts_plus_chunks10 | 5 | 1410316 | 22343 | 98% | 40% | 1091 |
