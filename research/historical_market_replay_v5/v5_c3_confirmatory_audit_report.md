# HMR-V5-C3: Confirmatory Model & Selection Policy Audit Report

> **Timestamp**: `2026-08-16T17:30:54.722321+00:00` | **Split Taxonomy**: `CONFIRMATORY_WITHIN_RESEARCH_WINDOW`
> **Frozen Canonical Policy**: `S3`

## 1. Governance Audit Verdict & Gate Results

- **Audit Verdict**: **`PROMOTE_FILTER_MODEL`**

**Verdict Rationale**: Confirmatory holdout audit validates model selection utility OOS. Ready for production modelization.

### Governance Gates Evaluation Status

| Gate | Description | Status |
| :--- | :--- | :---: |
| `C3-G0` | Gate Criteria | **`PASS`** |
| `C3-G1` | Gate Criteria | **`PASS`** |
| `C3-G2` | Gate Criteria | **`PASS`** |
| `C3-G3` | Gate Criteria | **`PASS`** |
| `C3-G4` | Gate Criteria | **`PASS`** |
| `C3-G5` | Gate Criteria | **`PASS`** |
| `C3-G6` | Gate Criteria | **`PASS`** |
| `C3-G7` | Gate Criteria | **`PASS`** |
| `C3-G8` | Gate Criteria | **`PASS`** |
| `C3-G9` | Gate Criteria | **`PASS`** |

---

## 2. Statistical Discrimination on untouched Confirmatory Period (2024-H2)

| Symbol | Model AUC | Base AUC | Model LogLoss | Base LogLoss | Model Brier | Base Brier | PR-AUC (Model) | PR-AUC (Base) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `BTC` | 0.7284 | 0.5000 | 0.5136 | 0.5777 | 0.1710 | 0.1944 | 0.8817 | 0.7365 |
| `ETH` | 0.6967 | 0.5000 | 0.3465 | 0.3741 | 0.1032 | 0.1083 | 0.9437 | 0.8765 |
| `BNB` | 0.6961 | 0.5000 | 0.4589 | 0.4998 | 0.1474 | 0.1597 | 0.9004 | 0.8007 |

---

## 3. Primary Control vs. Treatment Confirmatory Comparison (P4 Serialization)

| Asset | Group | Executed Trades | Gross EV (bps) | Net EV (Maker) | Net EV (Taker) | Rejection (Bad) | Retention (Good) | Ann. PnL % | Sharpe | Max DD % | Exposure % |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `BTC` | `CONTROL (No ML)` | 1975 | 29.38 | 22.38 | 14.38 | — | 100.0% | 55.48% | 35.80 | 0.09% | 51.7% |
| | `TREATMENT (S3)` | 1933 | 40.69 | 33.69 | 25.69 | 66.9% | 66.2% | 91.54% | 62.47 | 0.00% | 40.3% |
| `ETH` | `CONTROL (No ML)` | 2970 | 40.63 | 33.63 | 25.63 | — | 100.0% | 170.70% | 85.68 | 0.00% | 27.2% |
| | `TREATMENT (S3)` | 2826 | 43.15 | 36.15 | 28.15 | 40.1% | 80.8% | 176.94% | 94.78 | 0.00% | 23.9% |
| `BNB` | `CONTROL (No ML)` | 2581 | 34.72 | 27.72 | 19.72 | — | 100.0% | 104.19% | 56.72 | 0.00% | 37.0% |
| | `TREATMENT (S3)` | 2452 | 41.39 | 34.39 | 26.39 | 54.1% | 71.7% | 131.89% | 75.01 | 0.00% | 30.2% |
| `COMBINED` | `CONTROL (No ML)` | 7526 | 35.65 | 28.65 | 20.65 | — | 100.0% | 752.57% | 95.86 | 0.00% | 100.0% |
| | `TREATMENT (S3)` | 7211 | 41.89 | 34.89 | 26.89 | 57.1% | 73.2% | 1116.31% | 126.81 | 0.00% | 94.4% |
