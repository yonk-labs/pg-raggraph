# LongMemEval — pg-raggraph vs Zep

| arm | answer model | overall | vs Zep | vs full-ctx | avg ctx tok |
|---|---|---|---|---|---|
| full_context | gpt-4o-2024-11-20 | 57.5 | — | -2.7 | 105519 |
| full_context | gpt-4o-mini-2024-07-18 | 62.5 | — | +7.1 | 105519 |
| pgrg:local | gpt-4o-2024-11-20 | 80.0 | +8.8 | +19.8 | 3151 |
| pgrg:local | gpt-4o-mini-2024-07-18 | 80.0 | +16.2 | +24.6 | 3151 |
| pgrg:naive | gpt-4o-2024-11-20 | 85.0 | +13.8 | +24.8 | 3724 |
| pgrg:naive | gpt-4o-mini-2024-07-18 | 82.5 | +18.7 | +27.1 | 3724 |
| pgrg:smart | gpt-4o-2024-11-20 | 80.0 | +8.8 | +19.8 | 3587 |
| pgrg:smart | gpt-4o-mini-2024-07-18 | 75.0 | +11.2 | +19.6 | 3587 |
