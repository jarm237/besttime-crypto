# HMR-V1.3E-E4: Horizon Exit Experiment

Input: `research/historical_market_replay_v1/v1_3e/e1_candidates.parquet` — Top 5% SELL cohort (n=56)
Cost assumption: 15.0 bps flat

| Exit Strategy | n | Win Rate | Gross (bps) | Net (bps) | Profit Factor |
|:--------------|--:|---------:|------------:|----------:|--------------:|
| EXIT_1BAR | 56 | 0.0% | +0.00 | -15.00 | 1.000 |
| EXIT_4BAR | 56 | 55.4% | +2.76 | -12.24 | 1.350 |
| EXIT_8BAR | 56 | 48.2% | -1.09 | -16.09 | 0.917 |
| EXIT_16BAR | 56 | 60.7% | +1.56 | -13.44 | 1.132 |
| EXIT_24BAR | 56 | 41.1% | -7.24 | -22.24 | 0.607 |
| EXIT_32BAR | 56 | 66.1% | +6.23 | -8.77 | 1.671 |
| EXIT_48BAR | 56 | 62.5% | +5.66 | -9.34 | 1.691 |
| CURRENT_TPSL | 56 | 62.5% | +5.66 | -9.34 | 1.691 |