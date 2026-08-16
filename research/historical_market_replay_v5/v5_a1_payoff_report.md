# HMR-V5-A1: Entry-to-Payoff Surface Audit Report

> **Timestamp**: `2026-08-16T16:05:02.887176+00:00` | **Historical Window**: `2023-01-01 to 2024-12-31`

## Governance Rationale & Verdict

- **Audit Verdict**: **`PROMOTE_PAYOFF_ARCHITECTURE`**
- **ML Training**: `BLOCKED — V5-A payoff edge must be proven and promoted first`

**Verdict Wording**: Exploitable price movements exist post-entry, and cost floors are cleanly exceeded. Proceed to V5-B exit architecture comparison.

---

## Overall Payoff Surface Summary (BTC)

### BUY Side (long_30_20)

| Horizon | Signals | Mean Return (bps) | Std Dev (bps) | 95% CI (bps) | Mean MFE (bps) | Mean MAE (bps) | Capture Ratio | Cost-Adj EV (5 bps) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `30m` | 28451 | 21.85 | 25.17 | [21.56, 22.14] | 36.48 | 11.61 | 3.14 | 16.85 |
| `1h` | 28450 | 19.45 | 26.79 | [19.14, 19.76] | 45.07 | -0.61 | 74.37 | 14.45 |
| `2h` | 28449 | 18.87 | 27.38 | [18.55, 19.18] | 52.41 | -11.04 | 4.75 | 13.87 |
| `4h` | 28445 | 18.93 | 28.27 | [18.63, 19.25] | 59.50 | -19.80 | 3.01 | 13.94 |
| `8h` | 28439 | 19.01 | 29.21 | [18.67, 19.33] | 66.47 | -27.52 | 2.42 | 14.01 |
| `12h` | 28430 | 19.57 | 30.30 | [19.20, 19.90] | 70.62 | -31.82 | 2.22 | 14.57 |
| `24h` | 28413 | 19.67 | 33.29 | [19.27, 20.07] | 78.22 | -39.22 | 1.99 | 14.67 |
| `48h` | 28371 | 20.52 | 38.88 | [20.04, 20.98] | 87.08 | -47.16 | 1.85 | 15.52 |
| `72h` | 28333 | 21.40 | 43.54 | [20.87, 21.90] | 93.36 | -52.50 | 1.78 | 16.40 |

### SELL Side (short_30_20)

| Horizon | Signals | Mean Return (bps) | Std Dev (bps) | 95% CI (bps) | Mean MFE (bps) | Mean MAE (bps) | Capture Ratio | Cost-Adj EV (5 bps) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `30m` | 28419 | 21.66 | 25.11 | [21.39, 21.96] | 36.31 | 11.45 | 3.17 | 16.66 |
| `1h` | 28419 | 19.50 | 26.53 | [19.18, 19.80] | 44.84 | -0.67 | 66.73 | 14.50 |
| `2h` | 28417 | 18.65 | 27.10 | [18.33, 18.95] | 52.09 | -11.17 | 4.66 | 13.65 |
| `4h` | 28416 | 18.36 | 27.88 | [18.01, 18.66] | 58.94 | -20.07 | 2.94 | 13.36 |
| `8h` | 28410 | 18.47 | 29.19 | [18.11, 18.79] | 65.78 | -27.89 | 2.36 | 13.47 |
| `12h` | 28405 | 18.57 | 30.18 | [18.21, 18.88] | 69.78 | -32.24 | 2.16 | 13.57 |
| `24h` | 28385 | 17.98 | 33.27 | [17.57, 18.35] | 76.99 | -39.99 | 1.93 | 12.97 |
| `48h` | 28343 | 17.13 | 38.58 | [16.67, 17.59] | 84.82 | -49.05 | 1.73 | 12.13 |
| `72h` | 28299 | 16.32 | 43.12 | [15.83, 16.86] | 90.02 | -55.17 | 1.63 | 11.32 |

---

## Multi-Asset Stability Check (24h Horizon)

| Asset | Side | Signals | Mean Return (bps) | 95% CI (bps) | Mean MFE (bps) | Mean MAE (bps) | Capture Ratio | Cost-Adj EV (5 bps) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `BTC` | `BUY` | 28413 | 19.67 | [19.27, 20.07] | 78.22 | -39.22 | 1.99 | 14.67 |
| `BTC` | `SELL` | 28385 | 17.98 | [17.57, 18.35] | 76.99 | -39.99 | 1.93 | 12.97 |
| `ETH` | `BUY` | 27602 | 29.22 | [28.66, 29.81] | 120.25 | -59.08 | 2.04 | 24.22 |
| `ETH` | `SELL` | 27525 | 29.62 | [29.05, 30.19] | 118.43 | -59.86 | 1.98 | 24.62 |
| `BNB` | `BUY` | 28710 | 23.35 | [22.90, 23.83] | 94.90 | -48.56 | 1.95 | 18.35 |
| `BNB` | `SELL` | 28184 | 22.68 | [22.23, 23.16] | 94.39 | -48.51 | 1.95 | 17.68 |

---

## Regime & Temporal Stability (BTC 24h Horizon)

### Temporal Stability

| Side | Sub-segment | Signals | Mean Return (bps) | 95% CI (bps) | Mean MFE (bps) | Mean MAE (bps) | Capture Ratio |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| `BUY` | Year 2023 | 14205 | 20.38 | [19.78, 20.94] | 80.32 | -40.39 | 1.99 |
| `BUY` | Year 2024 | 14208 | 18.96 | [18.42, 19.51] | 76.12 | -38.05 | 2.00 |
| `BUY` | Quarter 2023Q1 | 3531 | 19.76 | [18.61, 20.99] | 80.68 | -42.21 | 1.91 |
| `BUY` | Quarter 2023Q2 | 3527 | 21.23 | [20.20, 22.31] | 79.61 | -38.19 | 2.08 |
| `BUY` | Quarter 2023Q3 | 3599 | 18.73 | [17.51, 19.81] | 79.94 | -41.60 | 1.92 |
| `BUY` | Quarter 2023Q4 | 3548 | 21.83 | [20.76, 22.86] | 81.03 | -39.52 | 2.05 |
| `BUY` | Quarter 2024Q1 | 3612 | 20.35 | [19.33, 21.38] | 78.11 | -38.89 | 2.01 |
| `BUY` | Quarter 2024Q2 | 3526 | 19.11 | [18.02, 20.14] | 77.17 | -38.67 | 2.00 |
| `BUY` | Quarter 2024Q3 | 3542 | 18.66 | [17.64, 19.68] | 74.47 | -36.99 | 2.01 |
| `BUY` | Quarter 2024Q4 | 3528 | 17.68 | [16.58, 18.77] | 74.69 | -37.63 | 1.99 |
| `SELL` | Year 2023 | 14098 | 17.90 | [17.29, 18.45] | 78.92 | -41.37 | 1.91 |
| `SELL` | Year 2024 | 14287 | 18.05 | [17.52, 18.57] | 75.09 | -38.64 | 1.94 |
| `SELL` | Quarter 2023Q1 | 3483 | 19.59 | [18.39, 20.71] | 81.56 | -41.18 | 1.98 |
| `SELL` | Quarter 2023Q2 | 3487 | 16.49 | [15.42, 17.60] | 76.07 | -41.14 | 1.85 |
| `SELL` | Quarter 2023Q3 | 3530 | 19.91 | [18.70, 21.09] | 80.46 | -41.04 | 1.96 |
| `SELL` | Quarter 2023Q4 | 3598 | 15.67 | [14.64, 16.71] | 77.60 | -42.10 | 1.84 |
| `SELL` | Quarter 2024Q1 | 3552 | 17.20 | [16.15, 18.23] | 76.26 | -40.41 | 1.89 |
| `SELL` | Quarter 2024Q2 | 3560 | 17.54 | [16.47, 18.57] | 75.66 | -39.48 | 1.92 |
| `SELL` | Quarter 2024Q3 | 3615 | 17.95 | [17.01, 18.98] | 72.97 | -37.96 | 1.92 |
| `SELL` | Quarter 2024Q4 | 3560 | 19.49 | [18.43, 20.52] | 75.49 | -36.72 | 2.06 |

### Regime Stability

| Side | Regime Type | Sub-segment | Signals | Mean Return (bps) | 95% CI (bps) | Mean MFE (bps) | Mean MAE (bps) | Capture Ratio |
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| `BUY` | Trend | UPTREND | 12196 | 16.31 | [15.74, 16.85] | 74.79 | -42.62 | 1.75 |
| `BUY` | Trend | DOWNTREND | 16217 | 22.19 | [21.65, 22.66] | 80.80 | -36.66 | 2.20 |
| `BUY` | Volatility | HIGH_VOL | 13660 | 20.83 | [20.24, 21.41] | 80.48 | -40.15 | 2.00 |
| `BUY` | Volatility | LOW_VOL | 14753 | 18.60 | [18.06, 19.11] | 76.12 | -38.35 | 1.98 |
| `SELL` | Trend | UPTREND | 18566 | 19.34 | [18.86, 19.84] | 78.37 | -38.40 | 2.04 |
| `SELL` | Trend | DOWNTREND | 9819 | 15.39 | [14.73, 16.03] | 74.38 | -43.01 | 1.73 |
| `SELL` | Volatility | HIGH_VOL | 13588 | 17.23 | [16.64, 17.78] | 78.46 | -41.69 | 1.88 |
| `SELL` | Volatility | LOW_VOL | 14797 | 18.66 | [18.12, 19.17] | 75.64 | -38.44 | 1.97 |

---

## Scientific Interpretation

- **Payoff Capture boundary**: Since high/low columns are not present in the outcome scaffold,
  the MFE and MAE are computed from close-to-close price paths. Actual intraday high/low excursions
  will be higher than reported here.
- **Rejection Rationale**: A hard stop verdict is triggered when mean returns fail to cover the lowest
  fee bracket (2.5 bps) or when the bootstrap 95% confidence intervals overlap with zero.
