# HMR-V2.1D: Candidate Quality Matrix Report

Database holds **1175 candidates** over the period **2025-01-01** to **2025-03-31**.

## Technical Trigger Families (2.1A)

| Family | n | BUY/SELL | Mean Gross (bps) | Median Gross (bps) | >20bps Rate | Net+ Rate | Mean MFE | Mean MAE | AUC vs Score | Classification |
|:-------|--:|:--------:|-----------------:|-------------------:|------------:|----------:|---------:|---------:|-------------:|:---------------|
| ('CHANDELIER',) | 11 | 11/0 | -39.03 | -44.35 | 18.2% | 18.2% | 0.47% | 0.98% | 0.944 | **STRUCTURALLY_TOXIC** |
| ('RSI_REVERSAL',) | 2 | 2/0 | 42.66 | 42.66 | 100.0% | 100.0% | 1.17% | 0.39% | nan | **INSUFFICIENT_SAMPLE** |
| ('SMA200_TREND',) | 45 | 14/31 | -38.80 | -38.12 | 13.3% | 15.6% | 0.37% | 1.18% | 0.846 | **STRUCTURALLY_TOXIC** |
| ('SMA50_BREAK',) | 1117 | 18/1099 | -23.42 | -20.69 | 10.8% | 14.5% | 0.56% | 1.00% | 0.716 | **STRUCTURALLY_TOXIC** |

## Symbol x Side Decomposition (2.1B)

| Symbol | Side | n | Mean Gross (bps) | Median Gross (bps) | >20bps Rate | Net+ Rate | Mean MFE | Mean MAE | AUC vs Score |
|:-------|:----:|--:|-----------------:|-------------------:|------------:|----------:|---------:|---------:|-------------:|
| BNB | BUY | 15 | -22.29 | -27.53 | 20.0% | 20.0% | 0.55% | 0.92% | 0.833 |
| BNB | SELL | 348 | -19.59 | -18.47 | 11.8% | 15.8% | 0.52% | 0.94% | 0.755 |
| BTC | BUY | 16 | -6.87 | 2.45 | 25.0% | 31.2% | 0.49% | 0.77% | 0.854 |
| BTC | SELL | 411 | -17.43 | -16.72 | 9.2% | 13.9% | 0.47% | 0.79% | 0.759 |
| ETH | BUY | 14 | -18.94 | -24.73 | 42.9% | 42.9% | 0.73% | 1.22% | 0.521 |
| ETH | SELL | 371 | -36.57 | -35.42 | 10.5% | 12.7% | 0.68% | 1.31% | 0.722 |

## Regime Decomposition (2.1C)

| Trend Regime | Volatility Regime | n | Mean Gross (bps) | >20bps Rate | Net+ Rate | Mean MFE | Mean MAE | AUC vs Score |
|:-------------|:------------------|--:|-----------------:|------------:|----------:|---------:|---------:|-------------:|
| RANGE | LOW_VOL | 12 | -2.71 | 8.3% | 25.0% | 0.49% | 0.87% | 0.909 |
| RANGE | NORMAL_VOL | 920 | -23.86 | 10.9% | 14.2% | 0.55% | 1.00% | 0.737 |
| TREND_DOWN | HIGH_VOL | 45 | -33.59 | 8.9% | 11.1% | 0.71% | 1.37% | 0.610 |
| TREND_DOWN | NORMAL_VOL | 143 | -21.31 | 11.9% | 16.8% | 0.57% | 0.90% | 0.623 |
| TREND_UP | HIGH_VOL | 10 | -47.97 | 20.0% | 20.0% | 0.51% | 1.38% | 0.750 |
| TREND_UP | NORMAL_VOL | 45 | -27.37 | 15.6% | 17.8% | 0.44% | 0.99% | 0.914 |

## Candidate Quality Matrix (2.1D)

| Family | Trend | Volatility | Side | n | Mean Gross (bps) | >20bps Rate | Net+ Rate | Classification |
|:-------|:------|:-----------|:----:|--:|-----------------:|------------:|----------:|:---------------|
| CHANDELIER | RANGE | NORMAL_VOL | BUY | 7 | -43.59 | 14.3% | 14.3% | **INSUFFICIENT_SAMPLE** |
| CHANDELIER | TREND_UP | NORMAL_VOL | BUY | 3 | -22.87 | 33.3% | 33.3% | **INSUFFICIENT_SAMPLE** |
| CHANDELIER | TREND_DOWN | NORMAL_VOL | BUY | 1 | -55.65 | 0.0% | 0.0% | **INSUFFICIENT_SAMPLE** |
| RSI_REVERSAL | RANGE | NORMAL_VOL | BUY | 2 | 42.66 | 100.0% | 100.0% | **INSUFFICIENT_SAMPLE** |
| SMA200_TREND | TREND_UP | NORMAL_VOL | SELL | 13 | -41.82 | 15.4% | 23.1% | **STRUCTURALLY_TOXIC** |
| SMA200_TREND | RANGE | NORMAL_VOL | SELL | 12 | -49.54 | 8.3% | 8.3% | **STRUCTURALLY_TOXIC** |
| SMA200_TREND | RANGE | NORMAL_VOL | BUY | 4 | -18.14 | 0.0% | 0.0% | **INSUFFICIENT_SAMPLE** |
| SMA200_TREND | TREND_DOWN | NORMAL_VOL | BUY | 4 | -47.96 | 0.0% | 0.0% | **INSUFFICIENT_SAMPLE** |
| SMA200_TREND | TREND_UP | NORMAL_VOL | BUY | 4 | 23.33 | 75.0% | 75.0% | **INSUFFICIENT_SAMPLE** |
| SMA200_TREND | TREND_DOWN | NORMAL_VOL | SELL | 3 | -15.34 | 0.0% | 0.0% | **INSUFFICIENT_SAMPLE** |
| SMA200_TREND | TREND_UP | HIGH_VOL | SELL | 2 | -56.52 | 0.0% | 0.0% | **INSUFFICIENT_SAMPLE** |
| SMA200_TREND | TREND_DOWN | HIGH_VOL | BUY | 1 | -162.04 | 0.0% | 0.0% | **INSUFFICIENT_SAMPLE** |
| SMA200_TREND | TREND_DOWN | HIGH_VOL | SELL | 1 | -93.09 | 0.0% | 0.0% | **INSUFFICIENT_SAMPLE** |
| SMA200_TREND | TREND_UP | HIGH_VOL | BUY | 1 | -22.49 | 0.0% | 0.0% | **INSUFFICIENT_SAMPLE** |
| SMA50_BREAK | RANGE | NORMAL_VOL | SELL | 881 | -23.89 | 10.4% | 13.8% | **STRUCTURALLY_TOXIC** |
| SMA50_BREAK | TREND_DOWN | NORMAL_VOL | SELL | 135 | -20.40 | 12.6% | 17.8% | **STRUCTURALLY_TOXIC** |
| SMA50_BREAK | TREND_DOWN | HIGH_VOL | SELL | 43 | -29.22 | 9.3% | 11.6% | **STRUCTURALLY_TOXIC** |
| SMA50_BREAK | TREND_UP | NORMAL_VOL | SELL | 24 | -28.55 | 4.2% | 4.2% | **STRUCTURALLY_TOXIC** |
| SMA50_BREAK | RANGE | NORMAL_VOL | BUY | 14 | -1.17 | 28.6% | 35.7% | **WEAK** |
| SMA50_BREAK | RANGE | LOW_VOL | SELL | 12 | -2.71 | 8.3% | 25.0% | **WEAK** |
| SMA50_BREAK | TREND_UP | HIGH_VOL | SELL | 4 | -94.58 | 0.0% | 0.0% | **INSUFFICIENT_SAMPLE** |
| SMA50_BREAK | TREND_UP | HIGH_VOL | BUY | 3 | 11.38 | 66.7% | 66.7% | **INSUFFICIENT_SAMPLE** |
| SMA50_BREAK | TREND_UP | NORMAL_VOL | BUY | 1 | -27.53 | 0.0% | 0.0% | **INSUFFICIENT_SAMPLE** |