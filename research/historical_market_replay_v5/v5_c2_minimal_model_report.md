# HMR-V5-C2: Minimal Economic Selection Model Report

> **Timestamp**: `2026-08-16T17:26:30.738375+00:00` | **Model**: `Logistic Regression`

## 1. Governance Audit Verdict & Gate Results

- **Audit Verdict**: **`PROMOTE_FILTER_MODEL`**

**Verdict Rationale**: Logistic Regression model provides statistically real and executable economic improvement under P4.

### Governance Gates Evaluation Status

| Gate | Description | Status |
| :--- | :--- | :---: |
| `C2-G0` | Gate Criteria | **`PASS`** |
| `C2-G1` | Gate Criteria | **`PASS`** |
| `C2-G2` | Gate Criteria | **`PASS`** |
| `C2-G3` | Gate Criteria | **`PASS`** |
| `C2-G4` | Gate Criteria | **`PASS`** |
| `C2-G5` | Gate Criteria | **`PASS`** |
| `C2-G6` | Gate Criteria | **`PASS`** |
| `C2-G7` | Gate Criteria | **`PASS`** |
| `C2-G8` | Gate Criteria | **`PASS`** |

---

## 2. Statistical Discrimination Performance (Fold 2)

| Asset | Model AUC | Base AUC | Model LogLoss | Base LogLoss | Model Brier | Base Brier | PR-AUC (Model) | PR-AUC (Base) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `BTC` | 0.7284 | 0.5000 | 0.5136 | 0.5777 | 0.1710 | 0.1944 | 0.8817 | 0.7365 |
| `ETH` | 0.6967 | 0.5000 | 0.3465 | 0.3741 | 0.1032 | 0.1083 | 0.9437 | 0.8765 |
| `BNB` | 0.6961 | 0.5000 | 0.4589 | 0.4998 | 0.1474 | 0.1597 | 0.9004 | 0.8007 |

---

## 3. Economic Replay Out-Of-Sample Comparison (P4 Serialization)

### BTC Replay (Fold 2 Test Set)

| Policy | Threshold | Executed Trades | Gross EV (bps) | Net EV (Maker) | Net EV (Taker) | Rejection (Bad) | Retention (Good) | Ann. PnL % | Sharpe | Max DD % |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `S0: No Filtering (Baseline)` | 0.0000 | 1975 | 29.38 | 22.38 | 14.38 | 0.0% | 100.0% | 55.48% | 9.40 | 0.09% |
| `S1: Reject bottom 10%` | 0.5592 | 1996 | 34.61 | 27.61 | 19.61 | 34.2% | 87.5% | 73.34% | 9.92 | 0.09% |
| `S2: Reject bottom 20%` | 0.6276 | 1972 | 38.24 | 31.24 | 23.24 | 53.4% | 76.8% | 84.93% | 10.19 | 0.00% |
| `S3: Reject bottom 30%` | 0.6816 | 1933 | 40.69 | 33.69 | 25.69 | 66.9% | 66.2% | 91.54% | 10.41 | 0.00% |
