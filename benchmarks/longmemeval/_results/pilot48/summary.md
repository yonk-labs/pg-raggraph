# LongMemEval — pg-raggraph vs Zep

| arm | answer model | overall | vs Zep | vs full-ctx | avg ctx tok |
|---|---|---|---|---|---|
| full_context | gpt-4o-2024-11-20 | 52.1 | — | -8.1 | 105529 |
| full_context | gpt-4o-mini-2024-07-18 | 62.5 | — | +7.1 | 105529 |
| pgrg:local | gpt-4o-2024-11-20 | 70.8 | -0.4 | +10.6 | 3156 |
| pgrg:local | gpt-4o-mini-2024-07-18 | 72.9 | +9.1 | +17.5 | 3156 |
| pgrg:naive | gpt-4o-2024-11-20 | 81.2 | +10.0 | +21.0 | 3735 |
| pgrg:naive | gpt-4o-mini-2024-07-18 | 79.2 | +15.4 | +23.8 | 3735 |
| pgrg:smart | gpt-4o-2024-11-20 | 72.9 | +1.7 | +12.7 | 3523 |
| pgrg:smart | gpt-4o-mini-2024-07-18 | 72.9 | +9.1 | +17.5 | 3523 |
