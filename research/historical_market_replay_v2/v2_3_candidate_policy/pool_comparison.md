# HMR-V2.3: Candidate Pool Redesign Report

This report compares the statistics of the raw V1 candidate pool versus the filtered V2 candidate pool.

## Candidate Pool Comparison (32-bar exit benchmark)

| Metric | Original V1 Pool | Redesigned V2 Pool | Delta |
|:-------|:----------------:|:------------------:|:-----:|
| **Pool Size ($n$)** | `1175` | `60` | `-1115` |
| **Mean Gross Return** | `-24.05 bps` | `-17.79 bps` | `+6.26 bps` |
| **Median Gross Return** | `-21.19 bps` | `-16.78 bps` | `+4.41 bps` |
| **Gross > 20bps rate** | `11.1%` | `21.7%` | `+10.5%` |
| **Gross > 25bps rate** | `7.8%` | `13.3%` | `+5.5%` |
| **Net+ rate** | `14.7%` | `26.7%` | `+11.9%` |
| **Mean MFE** | `0.56%` | `0.56%` | `+0.00%` |
| **Mean MAE** | `1.01%` | `1.02%` | `+0.01%` |

## Filtered Toxic Subgroups (Blacklist)

The following subgroups have been blocked due to structural toxicity (gross EV < -20 bps or win rate < 5%):

| Family | Trend | Volatility | Side | n | Mean Gross (bps) | >20bps Rate |
|:-------|:------|:-----------|:----:|--:|-----------------:|------------:|
| SMA50_BREAK | RANGE | NORMAL_VOL | SELL | 881 | -23.89 | 10.4% |
| SMA50_BREAK | TREND_DOWN | NORMAL_VOL | SELL | 135 | -20.40 | 12.6% |
| SMA50_BREAK | TREND_DOWN | HIGH_VOL | SELL | 43 | -29.22 | 9.3% |
| SMA50_BREAK | TREND_UP | NORMAL_VOL | SELL | 24 | -28.55 | 4.2% |
| SMA200_TREND | TREND_UP | NORMAL_VOL | SELL | 13 | -41.82 | 15.4% |
| SMA200_TREND | RANGE | NORMAL_VOL | SELL | 12 | -49.54 | 8.3% |
| CHANDELIER | RANGE | NORMAL_VOL | BUY | 7 | -43.59 | 14.3% |