# NEURAL_N0_TIMELINE_RECONCILIATION

## Executive Summary

During Phase N0, the initial neural dataset was reported as:
```text
dataset_start = 2023-01-02 23:00 UTC
dataset_end = 2025-12-31 22:00 UTC
samples = 21,957
train_samples = 14,544
validation_samples = 7,365
```

A root-cause timeline audit was conducted under Phase N0.1 across all 5 universe assets (`BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`, `DOGEUSDT`). This audit revealed a critical **dataset filtering defect** inherited from monthly CSV warmup conventions that artificially discarded **4,346 valid hourly candles** and generated **1,789 spurious inter-bar discontinuities**.

Following reconstruction directly from raw Binance Spot 1h klines, the authoritative timeline is now fully reconciled.

---

## 1. Root Cause Classification

### Why N0 had 1,789 Spurious Gaps & 21,957 Samples
- In `data/fresh_training_data_2023_2026/`, each monthly file (`{COIN}_1h_{YYYY-MM}.csv`) prepends a 10-day indicator initialization period (`WARMUP_DAYS["1h"] = 10`) marked with `is_warmup = 1`.
- When concatenating monthly files, the pipeline previously filtered `df[df["is_warmup"] == 0]`.
- Because the end of month $M$ overlaps with the 10-day warmup prefix of month $M+1$, timestamp deduplication and intersection logic inadvertently discarded valid trading bars whenever `is_warmup == 1` from the subsequent month collided with `is_warmup == 0` from the prior month.
- **Classification**: **Reporting and dataset filtering defect**. The underlying Binance Spot exchange data was never missing those bars.

---

## 2. Reconstructed Authoritative Coverage Matrix

| Asset | Source | Expected Bars (2023–2025) | Available Bars | Coverage (%) | Missing Bars | Timestamp Jumps > 1h |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: |
| **BTCUSDT** | Binance Spot 1h | 26,304 | 26,303 | 99.9962% | 1 | 1 (`2023-03-24 13:00`) |
| **ETHUSDT** | Binance Spot 1h | 26,304 | 26,303 | 99.9962% | 1 | 1 (`2023-03-24 13:00`) |
| **SOLUSDT** | Binance Spot 1h | 26,304 | 26,303 | 99.9962% | 1 | 1 (`2023-03-24 13:00`) |
| **BNBUSDT** | Binance Spot 1h | 26,304 | 26,303 | 99.9962% | 1 | 1 (`2023-03-24 13:00`) |
| **DOGEUSDT** | Binance Spot 1h | 26,304 | 26,303 | 99.9962% | 1 | 1 (`2023-03-24 13:00`) |
| **Synchronized Common Universe** | **All 5 Assets** | **26,304** | **26,303** | **99.9962%** | **1** | **1** |

---

## 3. Discontinuity & Trading Halt List

Across 3 calendar years (26,304 hours = 1,096 days $\times$ 24 hours), exactly **one** single gap exists across all 5 assets:

- **Missing Timestamp**: `2023-03-24 13:00:00 UTC`
- **Gap Interval**: `2023-03-24 12:00:00 UTC` $\to$ `2023-03-24 14:00:00 UTC` (2-hour jump)
- **Root Cause**: Official Binance Exchange-Wide Matching Engine Outage (a bug in trailing stop order processing halted all Spot trading on Binance between ~11:30 and 14:00 UTC on March 24, 2023).
- **Execution Treatment**: Handled strictly as an exchange trading halt (`is_halt = True`). No forward-filling of prices, no synthetic orders, and no fills are permitted across this gap. The portfolio state remains frozen from 12:00 UTC until trading resumed at 14:00 UTC.

---

## 4. Exact Evaluation Horizons

With lookback window $T = 48$ hours, the sequence index is structured as:

- **Full Reconstructed Series**: 26,303 hourly timestamps (`2023-01-01 00:00:00` to `2025-12-31 23:00:00`).
- **Feature Lookback**: $T = 48$ bars.
- **Valid Sequence Samples**: $26,303 - 48 = 26,255$ samples (excluding lookback warm-up).
- **Training Period (2023–2024)**:
  - Timeline: `2023-01-03 00:00:00 UTC` to `2024-12-31 23:00:00 UTC` (17,495 decision steps).
- **Purge Gap**: 48 hours (`2025-01-01 00:00:00 UTC` to `2025-01-02 23:00:00 UTC`).
- **Adaptive Validation Period (2025)**:
  - Timeline: `2025-01-03 00:00:00 UTC` to `2025-12-31 23:00:00 UTC` (8,712 decision steps).
- **Burned 2026 Holdout**: Sealed and untouched (`2026-01-01` onward).

---

## 5. Mapping and Closed-Candle Causality Verification

- Input tensor $\mathbf{X}_t$ at step $t$ utilizes data exclusively from $[t - T + 1, t]$.
- Bar $t$ is closed at timestamp $t$; all features ($r_{1h}, \text{vol\_spread}, \text{volume\_ratio}, r_{4h}$) are backward-looking functions of closed bars.
- Target vector $\mathbf{y}_t = \mathbf{P}_{t+1} / \mathbf{P}_t$ evaluates the subsequent 1h price movement over $(t, t+1]$.
- No open-price leakage or next-bar data is accessed prior to order submission.
