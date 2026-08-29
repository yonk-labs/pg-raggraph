# LongMemEval — pg-raggraph vs Zep

| arm | answer model | overall | vs Zep | vs full-ctx | avg ctx tok |
|---|---|---|---|---|---|
| full_context | gpt-4o-mini-2024-07-18 | 0.0 | — | -55.4 | 104730 |
| pgrg:local | gpt-4o-mini-2024-07-18 | 100.0 | +36.2 | +44.6 | 3693 |
| pgrg:naive | gpt-4o-mini-2024-07-18 | 50.0 | -13.8 | -5.4 | 3676 |
| pgrg:smart | gpt-4o-mini-2024-07-18 | 100.0 | +36.2 | +44.6 | 3699 |
