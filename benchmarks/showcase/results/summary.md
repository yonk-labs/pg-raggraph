# Showcase sweep — summary vs chunks

Datasets: mhr, musique, twowiki | subset=10 | top_k=10 | gen=gpt-5-mini judge=gpt-5-mini

| arm | expansion | headings | n | avg ctx tokens | tok reduction | llm calls | accuracy | avg latency ms |
|---|---|---|---|---|---|---|---|---|
| chunks_llm | moderate | n/a | 30 | 2482 | 0% | 30 | 50% | 805 |
| chunks_llm | off | n/a | 30 | 2483 | 0% | 30 | 60% | 1210 |
| summary_llm | moderate | off | 30 | 571 | 77% | 30 | 38% | 738 |
| summary_llm | moderate | on | 30 | 598 | 76% | 30 | 43% | 746 |
| summary_llm | off | off | 30 | 574 | 77% | 30 | 45% | 1171 |
| summary_llm | off | on | 30 | 601 | 76% | 30 | 40% | 1261 |
| summary_only | moderate | off | 30 | 571 | 77% | 0 | 25% | 323 |
| summary_only | moderate | on | 30 | 598 | 76% | 0 | 27% | 326 |
| summary_only | off | off | 30 | 574 | 77% | 0 | 30% | 341 |
| summary_only | off | on | 30 | 601 | 76% | 0 | 23% | 346 |
