# Benchmark Comparison — Track B1 Conditional Allocation vs Baselines

This document presents the full economic evaluation across all chronological splits, comparing **Track B1 Conditional Allocation** against **Constant-Multiplier Track A (M=1.0177)**, **Track A v1 (Frozen)**, **Learned Policy v1 (Corrected)**, **BTC 50/50 Rebalanced**, **BTC Buy & Hold**, and **Cash 100%**.

## TRAIN Window (2022-01-01 → 2023-12-31)

| Metric | Track B1 Conditional | Constant-Mult Track A | Track A v1 (Frozen) | Learned Policy v1 | BTC 50/50 Rebal | BTC Buy & Hold | Cash 100% |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Net PnL (USDT)** | $+3,191.26 | $+2,789.41 | $+2,758.11 | $+591.79 | $+216.97 | $-964.30 | $0.00 |
| **Net CAGR** | +14.87% | +13.10% | +12.96% | +2.92% | +1.08% | -4.95% | +0.00% |
| **Cumulative Return** | +31.91% | +27.89% | +27.58% | +5.92% | +2.17% | -9.64% | +0.00% |
| **Max Drawdown** | -28.84% | -28.28% | -28.12% | -39.38% | -41.04% | -67.38% | 0.00% |
| **Calmar Ratio** | 0.52 | 0.46 | 0.46 | 0.07 | 0.03 | -0.07 | 0.00 |
| **Sharpe Ratio** | 0.63 | 0.58 | 0.58 | 0.24 | 0.17 | 0.18 | 0.00 |
| **Annualized Turnover** | 6.40x | 3.97x | 3.97x | 0.94x | 0.55x | 0.50x | 0.00x |
| **Total Fees (USDT)** | $332.42 | $210.63 | $211.17 | $49.32 | $29.73 | $29.91 | $0.00 |
| **Number of Trades** | 88 | 23 | 23 | 24 | 11 | 1 | 0 |
| **Average BTC Exposure** | 50.6% | 50.2% | 49.9% | 48.5% | 50.3% | 100.0% | 0.0% |
| **Worst Month Return** | -12.68% | -10.08% | -9.90% | -19.00% | -19.88% | -37.29% | 0.0% |

## VALIDATION Window (2024-01-01 → 2024-12-31)

| Metric | Track B1 Conditional | Constant-Mult Track A | Track A v1 (Frozen) | Learned Policy v1 | BTC 50/50 Rebal | BTC Buy & Hold | Cash 100% |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Net PnL (USDT)** | $+7,283.20 | $+7,837.64 | $+7,825.10 | $+5,166.18 | $+5,491.36 | $+11,964.83 | $0.00 |
| **Net CAGR** | +72.65% | +78.18% | +78.05% | +51.54% | +54.78% | +119.31% | +0.00% |
| **Cumulative Return** | +72.83% | +78.38% | +78.25% | +51.66% | +54.91% | +119.65% | +0.00% |
| **Max Drawdown** | -33.11% | -30.88% | -30.69% | -17.36% | -15.86% | -32.31% | 0.00% |
| **Calmar Ratio** | 2.19 | 2.53 | 2.54 | 2.97 | 3.45 | 3.69 | 0.00 |
| **Sharpe Ratio** | 1.44 | 1.53 | 1.53 | 1.73 | 1.78 | 1.76 | 0.00 |
| **Annualized Turnover** | 10.38x | 4.79x | 4.79x | 1.00x | 0.89x | 1.00x | 0.00x |
| **Total Fees (USDT)** | $380.63 | $172.89 | $172.48 | $34.50 | $30.02 | $29.91 | $0.00 |
| **Number of Trades** | 62 | 12 | 12 | 11 | 8 | 1 | 0 |
| **Average BTC Exposure** | 79.6% | 77.0% | 76.5% | 49.7% | 50.7% | 100.0% | 0.0% |
| **Worst Month Return** | -14.53% | -14.88% | -14.88% | -7.32% | -7.61% | -14.88% | 0.0% |

## REUSED_TEST Window (2025-01-01 → 2026-11-18)

| Metric | Track B1 Conditional | Constant-Mult Track A | Track A v1 (Frozen) | Learned Policy v1 | BTC 50/50 Rebal | BTC Buy & Hold | Cash 100% |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Net PnL (USDT)** | $-2,645.78 | $-3,328.31 | $-3,349.00 | $-1,466.29 | $-1,472.99 | $-3,339.11 | $0.00 |
| **Net CAGR** | -15.07% | -19.36% | -19.49% | -8.08% | -8.12% | -19.43% | +0.00% |
| **Cumulative Return** | -26.46% | -33.28% | -33.49% | -14.66% | -14.73% | -33.39% | +0.00% |
| **Max Drawdown** | -38.64% | -41.91% | -42.08% | -29.77% | -30.74% | -53.74% | 0.00% |
| **Calmar Ratio** | -0.39 | -0.46 | -0.46 | -0.27 | -0.26 | -0.36 | 0.00 |
| **Sharpe Ratio** | -0.46 | -0.68 | -0.69 | -0.29 | -0.28 | -0.28 | 0.00 |
| **Annualized Turnover** | 7.87x | 6.35x | 6.40x | 0.72x | 0.47x | 0.53x | 0.00x |
| **Total Fees (USDT)** | $392.20 | $309.35 | $311.50 | $40.00 | $25.87 | $29.91 | $0.00 |
| **Number of Trades** | 82 | 30 | 30 | 16 | 8 | 1 | 0 |
| **Average BTC Exposure** | 58.6% | 54.9% | 54.6% | 48.9% | 50.3% | 100.0% | 0.0% |
| **Worst Month Return** | -16.26% | -17.52% | -17.52% | -9.85% | -10.27% | -20.43% | 0.0% |

## FULL_DIAGNOSTIC Window (2022-01-01 → 2026-11-18)

| Metric | Track B1 Conditional | Constant-Mult Track A | Track A v1 (Frozen) | Learned Policy v1 | BTC 50/50 Rebal | BTC Buy & Hold | Cash 100% |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Net PnL (USDT)** | $+7,119.38 | $+5,516.82 | $+5,419.98 | $+3,646.59 | $+3,655.62 | $+3,477.24 | $0.00 |
| **Net CAGR** | +11.64% | +9.42% | +9.28% | +6.58% | +6.59% | +6.30% | +0.00% |
| **Cumulative Return** | +71.19% | +55.17% | +54.20% | +36.47% | +36.56% | +34.77% | +0.00% |
| **Max Drawdown** | -38.64% | -41.91% | -42.08% | -39.38% | -41.04% | -67.38% | 0.00% |
| **Calmar Ratio** | 0.30 | 0.22 | 0.22 | 0.17 | 0.16 | 0.09 | 0.00 |
| **Sharpe Ratio** | 0.50 | 0.44 | 0.44 | 0.38 | 0.38 | 0.37 | 0.00 |
| **Annualized Turnover** | 7.37x | 4.64x | 4.67x | 0.69x | 0.39x | 0.20x | 0.00x |
| **Total Fees (USDT)** | $1,641.52 | $1,044.80 | $1,047.28 | $116.24 | $62.84 | $29.91 | $0.00 |
| **Number of Trades** | 230 | 63 | 63 | 50 | 25 | 1 | 0 |
| **Average BTC Exposure** | 59.6% | 57.5% | 57.2% | 48.8% | 50.5% | 100.0% | 0.0% |
| **Worst Month Return** | -16.26% | -17.52% | -17.52% | -19.00% | -19.88% | -37.29% | 0.0% |

## Transaction Cost Stress Testing for Track B1 (Full Period)
| Fee Level | Net PnL (USDT) | Net CAGR | Max Drawdown | Calmar | Sharpe | Annualized Turnover | Total Fees |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **12.0bps** | $+8,264.89 | +13.13% | -37.75% | 0.35 | 0.54 | 7.37x | $682.04 |
| **20.0bps** | $+7,746.60 | +12.47% | -38.15% | 0.33 | 0.53 | 7.37x | $1,117.66 |
| **30.0bps** | $+7,119.38 | +11.64% | -38.64% | 0.30 | 0.50 | 7.37x | $1,641.52 |
| **50.0bps** | $+5,930.64 | +10.01% | -40.13% | 0.25 | 0.46 | 7.37x | $2,623.67 |