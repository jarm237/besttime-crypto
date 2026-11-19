# Benchmark Comparison — Learned Policy v1 Corrected vs Baselines

This document presents the rigorous economic evaluation across all chronological splits, comparing **Learned Policy v1 (Corrected)** against **Static 50/50**, **Rebalanced 50/50**, **Track A v1 (Frozen)**, **S5 Daily Trend BTC (Corrected)**, **BTC Buy & Hold**, and **Cash 100%**.

## TRAIN Window (2022-01-01 → 2023-12-31)

| Metric | Learned Policy v1 | BTC 50/50 Static | BTC 50/50 Rebalanced | Track A v1 (Frozen) | S5 Daily Trend BTC | BTC Buy & Hold | Cash 100% |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Net PnL (USDT)** | $+591.79 | $-482.87 | $+216.97 | $+2,758.11 | $+1,124.42 | $-964.30 | $0.00 |
| **Net CAGR** | +2.92% | -2.45% | +1.08% | +12.96% | +5.48% | -4.95% | +0.00% |
| **Cumulative Return** | +5.92% | -4.83% | +2.17% | +27.58% | +11.24% | -9.64% | +0.00% |
| **Max Drawdown** | -39.38% | -34.16% | -41.04% | -28.12% | -41.63% | -67.38% | 0.00% |
| **Calmar Ratio** | 0.07 | -0.07 | 0.03 | 0.46 | 0.13 | -0.07 | 0.00 |
| **Sharpe Ratio** | 0.24 | -0.02 | 0.17 | 0.58 | 0.33 | 0.18 | 0.00 |
| **Annualized Turnover** | 0.94x | 0.25x | 0.55x | 3.97x | 67.45x | 0.50x | 0.00x |
| **Total Fees (USDT)** | $49.32 | $14.98 | $29.73 | $211.17 | $3,413.70 | $29.91 | $0.00 |
| **Number of Trades** | 24 | 1 | 11 | 23 | 135 | 1 | 0 |
| **Average BTC Exposure** | 48.5% | 37.2% | 50.3% | 49.9% | 50.5% | 100.0% | 0.0% |
| **Worst Month Return** | -19.00% | -15.12% | -19.88% | -9.90% | -14.01% | -37.29% | 0.0% |

## VALIDATION Window (2024-01-01 → 2024-12-31)

| Metric | Learned Policy v1 | BTC 50/50 Static | BTC 50/50 Rebalanced | Track A v1 (Frozen) | S5 Daily Trend BTC | BTC Buy & Hold | Cash 100% |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Net PnL (USDT)** | $+5,166.18 | $+5,991.37 | $+5,491.36 | $+7,825.10 | $+1,998.47 | $+11,964.83 | $0.00 |
| **Net CAGR** | +51.54% | +59.77% | +54.78% | +78.05% | +19.94% | +119.31% | +0.00% |
| **Cumulative Return** | +51.66% | +59.91% | +54.91% | +78.25% | +19.98% | +119.65% | +0.00% |
| **Max Drawdown** | -17.36% | -20.48% | -15.86% | -30.69% | -34.39% | -32.31% | 0.00% |
| **Calmar Ratio** | 2.97 | 2.92 | 3.45 | 2.54 | 0.58 | 3.69 | 0.00 |
| **Sharpe Ratio** | 1.73 | 1.64 | 1.78 | 1.53 | 0.67 | 1.76 | 0.00 |
| **Annualized Turnover** | 1.00x | 0.50x | 0.89x | 4.79x | 67.77x | 1.00x | 0.00x |
| **Total Fees (USDT)** | $34.50 | $14.98 | $30.02 | $172.48 | $2,064.72 | $29.91 | $0.00 |
| **Number of Trades** | 11 | 1 | 8 | 12 | 68 | 1 | 0 |
| **Average BTC Exposure** | 49.7% | 60.1% | 50.7% | 76.5% | 56.3% | 100.0% | 0.0% |
| **Worst Month Return** | -7.32% | -9.33% | -7.61% | -14.88% | -15.09% | -14.88% | 0.0% |

## REUSED_TEST Window (2025-01-01 → 2026-11-18)

| Metric | Learned Policy v1 | BTC 50/50 Static | BTC 50/50 Rebalanced | Track A v1 (Frozen) | S5 Daily Trend BTC | BTC Buy & Hold | Cash 100% |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Net PnL (USDT)** | $-1,466.29 | $-1,672.05 | $-1,472.99 | $-3,349.00 | $-3,055.36 | $-3,339.11 | $0.00 |
| **Net CAGR** | -8.08% | -9.27% | -8.12% | -19.49% | -17.62% | -19.43% | +0.00% |
| **Cumulative Return** | -14.66% | -16.72% | -14.73% | -33.49% | -30.55% | -33.39% | +0.00% |
| **Max Drawdown** | -29.77% | -30.72% | -30.74% | -42.08% | -45.49% | -53.74% | 0.00% |
| **Calmar Ratio** | -0.27 | -0.30 | -0.26 | -0.46 | -0.39 | -0.36 | 0.00 |
| **Sharpe Ratio** | -0.29 | -0.37 | -0.28 | -0.69 | -0.60 | -0.28 | 0.00 |
| **Annualized Turnover** | 0.72x | 0.27x | 0.47x | 6.40x | 67.95x | 0.53x | 0.00x |
| **Total Fees (USDT)** | $40.00 | $14.98 | $25.87 | $311.50 | $3,044.72 | $29.91 | $0.00 |
| **Number of Trades** | 16 | 1 | 8 | 30 | 128 | 1 | 0 |
| **Average BTC Exposure** | 48.9% | 48.0% | 50.3% | 54.6% | 48.9% | 100.0% | 0.0% |
| **Worst Month Return** | -9.85% | -9.43% | -10.27% | -17.52% | -14.42% | -20.43% | 0.0% |

## FULL_DIAGNOSTIC Window (2022-01-01 → 2026-11-18)

| Metric | Learned Policy v1 | BTC 50/50 Static | BTC 50/50 Rebalanced | Track A v1 (Frozen) | S5 Daily Trend BTC | BTC Buy & Hold | Cash 100% |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Net PnL (USDT)** | $+3,646.59 | $+1,741.22 | $+3,655.62 | $+5,419.98 | $-660.62 | $+3,477.24 | $0.00 |
| **Net CAGR** | +6.58% | +3.34% | +6.59% | +9.28% | -1.39% | +6.30% | +0.00% |
| **Cumulative Return** | +36.47% | +17.41% | +36.56% | +54.20% | -6.61% | +34.77% | +0.00% |
| **Max Drawdown** | -39.38% | -39.22% | -41.04% | -42.08% | -49.39% | -67.38% | 0.00% |
| **Calmar Ratio** | 0.17 | 0.09 | 0.16 | 0.22 | -0.03 | 0.09 | 0.00 |
| **Sharpe Ratio** | 0.38 | 0.26 | 0.38 | 0.44 | 0.12 | 0.37 | 0.00 |
| **Annualized Turnover** | 0.69x | 0.10x | 0.39x | 4.67x | 67.50x | 0.20x | 0.00x |
| **Total Fees (USDT)** | $116.24 | $14.98 | $62.84 | $1,047.28 | $9,789.04 | $29.91 | $0.00 |
| **Number of Trades** | 50 | 1 | 25 | 63 | 330 | 1 | 0 |
| **Average BTC Exposure** | 48.8% | 52.1% | 50.5% | 57.2% | 51.1% | 100.0% | 0.0% |
| **Worst Month Return** | -19.00% | -15.12% | -19.88% | -17.52% | -16.76% | -37.29% | 0.0% |

## Transaction Cost Stress Testing (Full Period)
| Fee Level | Net PnL (USDT) | Net CAGR | Max Drawdown | Calmar | Sharpe | Annualized Turnover | Total Fees |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **12.0bps** | $+3,729.42 | +6.71% | -39.33% | 0.17 | 0.39 | 0.69x | $46.65 |
| **20.0bps** | $+3,692.54 | +6.65% | -39.35% | 0.17 | 0.39 | 0.69x | $77.64 |
| **30.0bps** | $+3,646.59 | +6.58% | -39.38% | 0.17 | 0.38 | 0.69x | $116.24 |
| **50.0bps** | $+3,555.14 | +6.43% | -39.44% | 0.16 | 0.38 | 0.69x | $192.99 |