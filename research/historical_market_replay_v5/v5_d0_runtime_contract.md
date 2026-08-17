# HMR-V5-D0: Runtime Contract Freeze Report

> **Status**: `FROZEN` | **Trained-At**: `2023-12-31` | **Validated-At**: `2026-08-16`

This document defines and freezes the production runtime configuration for **HMR-V5-D** to prevent post-holdout parameter drift and guarantee research-to-production parity.

---

## 1. Frozen Runtime Definitions

### Feature Schema & Ordering
- **Feature Schema**: `['return_8', 'return_32', 'return_72', 'abs_move_72']`
- **Dtype**: All features are `float64`.
- **Order Hash**: `4b6845c43d8a6e873a11b689025e172d7f8d6bb77636e0971b86c35bb5f37ccb`

### Preprocessing (StandardScaler Parameters)
- **BTC**:
  - Means: `[2.09026201e-05, 4.40000733e-05, 9.81883681e-05, 9.15007367e-03]`
  - Scale/Std: `[0.00338879, 0.00357247, 0.00379798, 0.00184502]`
- **ETH**:
  - Means: `[1.06146508e-05, 2.58741852e-05, 8.14050822e-05, 1.34114299e-02]`
  - Scale/Std: `[0.00505429, 0.0052093, 0.00544563, 0.0026645]`
- **BNB**:
  - Means: `[3.00802984e-06, 3.94632389e-05, 4.82320300e-05, 1.09052278e-02]`
  - Scale/Std: `[0.00406818, 0.00421984, 0.00444918, 0.00221289]`

### Model Coefficients & Intercepts
- **BTC**:
  - Coefficients: `[0.01096789, -0.04227064, -0.00135683, 0.92312112]`
  - Intercept: `1.3263772394595157`
- **ETH**:
  - Coefficients: `[-0.00690789, -0.03412055, 0.02184058, 0.88750206]`
  - Intercept: `2.1287354465140993`
- **BNB**:
  - Coefficients: `[-0.02679497, 0.02540484, -0.01176299, 0.87520967]`
  - Intercept: `1.6735316436198269`

---

## 2. Frozen Selection Policy & Absolute Thresholds

Rather than computing cross-sectional percentiles dynamically online, the production runtime applies the absolute thresholds resolved from the **S3** validation evidence:

| Asset | Selected Policy | Score Threshold |
| :--- | :---: | :---: |
| **BTC** | `S3` (30th percentile) | **`0.6815743466054911`** |
| **ETH** | `S3` (30th percentile) | **`0.8280730473863367`** |
| **BNB** | `S3` (30th percentile) | **`0.7566326790486391`** |

*Online Rule*:
- If predicted probability $p \ge \text{Threshold} \implies$ signal is eligible.
- If $p < \text{Threshold} \implies$ signal is rejected.

---

## 3. Fallback & Execution Semantics

- **Execution Contract**: `P4` (Single concurrency per asset, 96 bars cooldown).
- **Exit Contract**: `E4` (TP +50 bps / SL -30 bps / Max hold 96 bars).
- **Maker Cost**: 7 bps.
- **Taker Cost**: 15 bps (stress).
- **Missing Features**: Raise an exception or default to 0.0 to reject trade.
- **Invalid Scores**: Reject signal.
