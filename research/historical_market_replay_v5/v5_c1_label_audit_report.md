# HMR-V5-C1: Economic Label & Objective Audit Report

> **Timestamp**: `2026-08-16T17:19:45.394193+00:00` | **Label Strategy**: `E4 (TP +50 bps / SL -30 bps)`

## 1. Label Class Balance Summary

| Symbol | Total Signals | Positives (Y=1) | Negatives (Y=0) | Positive Rate | BUY Pos % | SELL Pos % |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| `BTC` | 56872 | 42576 | 14296 | **`74.86%`** | 74.96% | 74.77% |
| `ETH` | 55202 | 48080 | 7122 | **`87.10%`** | 87.03% | 87.17% |
| `BNB` | 56968 | 45980 | 10988 | **`80.71%`** | 80.56% | 80.86% |
| `COMBINED` | 169042 | 136636 | 32406 | **`80.83%`** | 80.79% | 80.87% |

---

## 2. Temporal & Regime Stability Audit

### Temporal Stability

| Period | Total Signals | Positive Rate |
| :--- | :---: | :---: |
| **2023** | 84440 | `81.12%` |
| **2024** | 84602 | `80.54%` |
| `2023Q1` | 20768 | 81.39% |
| `2023Q2` | 21036 | 81.35% |
| `2023Q3` | 21305 | 81.25% |
| `2023Q4` | 21331 | 80.50% |
| `2024Q1` | 21161 | 80.83% |
| `2024Q2` | 21042 | 80.58% |
| `2024Q3` | 21230 | 79.81% |
| `2024Q4` | 21169 | 80.95% |

### Market Regime Stability

| Regime Type | Regime | Total Signals | Positive Rate |
| :--- | :--- | :---: | :---: |
| **Trend** | `Bull` | 24335 | `88.17%` |
| **Trend** | `Bear` | 23446 | `88.53%` |
| **Trend** | `Range` | 121261 | `77.87%` |
| **Volatility** | `High Vol` | 86523 | `82.04%` |
| **Volatility** | `Low Vol` | 82519 | `79.56%` |

---

## 3. Exit Duration Distributions (Bars Held)

| Metric | Mean (bars) | Median (bars) | Std Dev | Max (bars) |
| :--- | :---: | :---: | :---: | :---: |
| **Time-to-TP (Y=1)** | 2.4 | 1 | 2.5 | 52 |
| **Time-to-SL (Y=0)** | 5.0 | 4 | 3.6 | 41 |

- Total Exit Timeouts recorded: **`0`** (All exit paths resolved before maximum hold limit).

---

## 4. Signal Autocorrelation & Overlapping Path Dependence

| Symbol | Lag 1 Corr | Lag 2 Corr | Lag 3 Corr | Lag 4 Corr | Lag 5 Corr | Overlapping Signals % | Duplicate Entries % |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `BTC` | 0.0211 | -0.0018 | 0.0009 | -0.0021 | 0.0021 | **`97.6%`** | 0.0% |
| `ETH` | 0.0333 | -0.0040 | -0.0088 | -0.0022 | -0.0022 | **`88.0%`** | 0.0% |
| `BNB` | 0.0333 | 0.0040 | -0.0034 | 0.0022 | 0.0008 | **`94.5%`** | 0.0% |

---

## 5. Purged Walk-Forward Split Strategy Design

To prevent future path information leakage (due to high signal overlap), train/validation/test sets must use an embargo of **96 bars** (1 day).

### Proposed Walk-Forward Folds Split Layout Matrix:

| Fold | Segment | Start Time | End Time | Embargo Offset |
| :---: | :---: | :--- | :--- | :---: |
| **Fold 1** | **Train** | `2023-01-01 00:00` | `2023-06-30 23:45` | — |
| | **Validation** | `2023-07-02 00:00` | `2023-09-30 23:45` | 96 bars (1 day) |
| | **Test** | `2023-10-02 00:00` | `2023-12-31 23:45` | 96 bars (1 day) |
| **Fold 2** | **Train** | `2023-01-01 00:00` | `2023-12-31 23:45` | — |
| | **Validation** | `2024-01-02 00:00` | `2024-06-30 23:45` | 96 bars (1 day) |
| | **Test** | `2024-07-02 00:00` | `2024-12-31 23:45` | 96 bars (1 day) |
