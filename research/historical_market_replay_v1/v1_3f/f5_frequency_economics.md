# HMR-V1.3F-F5: Frequency Economics Report

Input: `research/historical_market_replay_v1/v1_3f/f0_candidates.parquet` — Top 5% SELL cohort (n=56)

Dataset window spans **88.84 days**  

Cost assumption: **15.0 bps** flat per trade

| Horizon | Hold Time | n | Gross/Trade | Net/Trade | Trades/Day | Daily Cost | Daily Net EV |
|:--------|:----------|--:|------------:|----------:|-----------:|-----------:|-------------:|
| 1 bars | 0.25 hours | 56 | +0.00 bps | -15.00 bps | 0.630 | 9.45 bps | -9.45 bps |
| 2 bars | 0.50 hours | 56 | +4.20 bps | -10.80 bps | 0.630 | 9.45 bps | -6.81 bps |
| 4 bars | 1.00 hours | 56 | +2.76 bps | -12.24 bps | 0.630 | 9.45 bps | -7.72 bps |
| 8 bars | 2.00 hours | 56 | -1.09 bps | -16.09 bps | 0.630 | 9.45 bps | -10.14 bps |
| 16 bars | 4.00 hours | 56 | +1.56 bps | -13.44 bps | 0.630 | 9.45 bps | -8.47 bps |
| 24 bars | 6.00 hours | 56 | -7.24 bps | -22.24 bps | 0.630 | 9.45 bps | -14.02 bps |
| 32 bars | 8.00 hours | 56 | +6.23 bps | -8.77 bps | 0.630 | 9.45 bps | -5.52 bps |
| 48 bars | 12.00 hours | 56 | +5.66 bps | -9.34 bps | 0.630 | 9.45 bps | -5.88 bps |
| 72 bars | 18.00 hours | 56 | +3.51 bps | -11.49 bps | 0.630 | 9.45 bps | -7.24 bps |
| 96 bars | 24.00 hours | 56 | +4.98 bps | -10.02 bps | 0.630 | 9.45 bps | -6.32 bps |
| 192 bars | 48.00 hours | 56 | +1.68 bps | -13.32 bps | 0.630 | 9.45 bps | -8.40 bps |