# Benchmark Comparison — Learned Policy v1 vs Baselines

This document presents the rigorous economic evaluation across all chronological splits, comparing **Learned Policy v1** against **Track A v1 (Frozen)**, **S5 Daily Trend BTC (Corrected)**, **BTC Buy & Hold**, and **Cash 100%**.

## TRAIN Window (2022-01-01 → 2023-12-31)

| Metric | Learned Policy v1 | Track A v1 (Frozen) | S5 Daily Trend BTC | BTC Buy & Hold | Cash 100% |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Net PnL (USDT)** | $+607.03 | $+2,758.11 | $+1,124.42 | $-964.30 | $0.00 |
| **Net CAGR** | +2.99% | +12.96% | +5.48% | -4.95% | +0.00% |
| **Cumulative Return** | +6.07% | +27.58% | +11.24% | -9.64% | +0.00% |
| **Max Drawdown** | -39.55% | -28.12% | -41.63% | -67.38% | 0.00% |
| **Calmar Ratio** | 0.08 | 0.46 | 0.13 | -0.07 | 0.00 |
| **Sharpe Ratio** | 0.24 | 0.58 | 0.33 | 0.18 | 0.00 |
| **Annualized Turnover** | 1.01x | 3.97x | 67.45x | 0.50x | 0.00x |
| **Total Fees (USDT)** | $52.40 | $211.17 | $3,413.70 | $29.91 | $0.00 |
| **Number of Trades** | 26 | 23 | 135 | 1 | 0 |
| **Average BTC Exposure** | 49.0% | 49.9% | 50.5% | 100.0% | 0.0% |
| **Worst Month Return** | -19.16% | -9.90% | -14.01% | -37.29% | 0.0% |

## VALIDATION Window (2024-01-01 → 2024-12-31)

| Metric | Learned Policy v1 | Track A v1 (Frozen) | S5 Daily Trend BTC | BTC Buy & Hold | Cash 100% |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Net PnL (USDT)** | $+5,294.33 | $+7,825.10 | $+1,998.47 | $+11,964.83 | $0.00 |
| **Net CAGR** | +52.82% | +78.05% | +19.94% | +119.31% | +0.00% |
| **Cumulative Return** | +52.94% | +78.25% | +19.98% | +119.65% | +0.00% |
| **Max Drawdown** | -17.06% | -30.69% | -34.39% | -32.31% | 0.00% |
| **Calmar Ratio** | 3.10 | 2.54 | 0.58 | 3.69 | 0.00 |
| **Sharpe Ratio** | 1.76 | 1.53 | 0.67 | 1.76 | 0.00 |
| **Annualized Turnover** | 1.27x | 4.79x | 67.77x | 1.00x | 0.00x |
| **Total Fees (USDT)** | $44.45 | $172.48 | $2,064.72 | $29.91 | $0.00 |
| **Number of Trades** | 15 | 12 | 68 | 1 | 0 |
| **Average BTC Exposure** | 49.7% | 76.5% | 56.3% | 100.0% | 0.0% |
| **Worst Month Return** | -6.83% | -14.88% | -15.09% | -14.88% | 0.0% |

## REUSED_TEST Window (2025-01-01 → 2026-11-18)

| Metric | Learned Policy v1 | Track A v1 (Frozen) | S5 Daily Trend BTC | BTC Buy & Hold | Cash 100% |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Net PnL (USDT)** | $-1,459.46 | $-3,349.00 | $-3,055.36 | $-3,339.11 | $0.00 |
| **Net CAGR** | -8.05% | -19.49% | -17.62% | -19.43% | +0.00% |
| **Cumulative Return** | -14.59% | -33.49% | -30.55% | -33.39% | +0.00% |
| **Max Drawdown** | -30.25% | -42.08% | -45.49% | -53.74% | 0.00% |
| **Calmar Ratio** | -0.27 | -0.46 | -0.39 | -0.36 | 0.00 |
| **Sharpe Ratio** | -0.29 | -0.69 | -0.60 | -0.28 | 0.00 |
| **Annualized Turnover** | 0.73x | 6.40x | 67.95x | 0.53x | 0.00x |
| **Total Fees (USDT)** | $40.54 | $311.50 | $3,044.72 | $29.91 | $0.00 |
| **Number of Trades** | 17 | 30 | 128 | 1 | 0 |
| **Average BTC Exposure** | 48.7% | 54.6% | 48.9% | 100.0% | 0.0% |
| **Worst Month Return** | -9.83% | -17.52% | -14.42% | -20.43% | 0.0% |

## FULL_DIAGNOSTIC Window (2022-01-01 → 2026-11-18)

| Metric | Learned Policy v1 | Track A v1 (Frozen) | S5 Daily Trend BTC | BTC Buy & Hold | Cash 100% |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Net PnL (USDT)** | $+3,574.73 | $+5,419.98 | $-660.62 | $+3,477.24 | $0.00 |
| **Net CAGR** | +6.46% | +9.28% | -1.39% | +6.30% | +0.00% |
| **Cumulative Return** | +35.75% | +54.20% | -6.61% | +34.77% | +0.00% |
| **Max Drawdown** | -39.55% | -42.08% | -49.39% | -67.38% | 0.00% |
| **Calmar Ratio** | 0.16 | 0.22 | -0.03 | 0.09 | 0.00 |
| **Sharpe Ratio** | 0.38 | 0.44 | 0.12 | 0.37 | 0.00 |
| **Annualized Turnover** | 0.73x | 4.67x | 67.50x | 0.20x | 0.00x |
| **Total Fees (USDT)** | $122.01 | $1,047.28 | $9,789.04 | $29.91 | $0.00 |
| **Number of Trades** | 53 | 63 | 330 | 1 | 0 |
| **Average BTC Exposure** | 49.1% | 57.2% | 51.1% | 100.0% | 0.0% |
| **Worst Month Return** | -19.16% | -17.52% | -16.76% | -37.29% | 0.0% |

## Transaction Cost Stress Testing (Full Period)
| Fee Level | Net PnL (USDT) | Net CAGR | Max Drawdown | Calmar | Sharpe | Annualized Turnover | Total Fees |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **12.0bps** | $+3,661.59 | +6.60% | -39.48% | 0.17 | 0.38 | 0.73x | $48.98 |
| **20.0bps** | $+3,622.92 | +6.54% | -39.51% | 0.17 | 0.38 | 0.73x | $81.50 |
| **30.0bps** | $+3,574.73 | +6.46% | -39.55% | 0.16 | 0.38 | 0.73x | $122.01 |
| **50.0bps** | $+3,478.88 | +6.31% | -39.63% | 0.16 | 0.37 | 0.73x | $202.53 |