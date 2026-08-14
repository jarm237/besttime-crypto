# R5–R6 — Calibration Diagnosis & Root Cause

**Gate**: `CALIBRATION_COLLAPSE_CAUSE = KNOWN`

## Summary Metrics

| Metric | Training Set | Calibration Set (Dec 2024) | Shift |
| :--- | :---: | :---: | :---: |
| Total Samples | `9,347` | `409` | - |
| Wins (y=1) | `127` | `3` | - |
| Base Win Rate | `1.3587%` | `0.7335%` | `-0.6252%` |

## Breakdown By Symbol

| Symbol | Total Samples | Wins | Win Rate |
| :--- | :---: | :---: | :---: |
| BNB | `122` | `0` | `0.00%` |
| BTC | `145` | `3` | `2.07%` |
| ETH | `142` | `0` | `0.00%` |

## Breakdown By Technical Action

| Action | Total Samples | Wins | Win Rate |
| :--- | :---: | :---: | :---: |
| SELL | `394` | `2` | `0.51%` |
| BUY | `15` | `1` | `6.67%` |

## Classified Root Causes

### ⚠️ CALIBRATION_POSITIVE_STARVATION
Calibration dataset has critically few positive samples (wins < 10), which causes isotonic regression to flatten predictions to near-zero.

### ⚠️ CALIBRATION_SAMPLE_TOO_SMALL
Calibration cohort size (409) is too small to perform stable probability calibration.

### ⚠️ TEMPORAL_DISTRIBUTION_SHIFT
Win rate dropped by 46.0% in calibration period compared to training (0.73% vs 1.36%).

### ⚠️ SIDE_DISTRIBUTION_IMBALANCE
Extremely imbalanced technical signals in calibration set: 96.3% are SELL signals.

## Calibration Remediation Recommendation

Based on the identified root causes, we recommend:
1. **Isotonic regression is highly sensitive to sample size and positive sparsity**. A cohort of 3 positive instances out of 409 causes isotonic calibration to map all probabilities above the raw score of the last win to a flat maximum of `16.67%`.
2. **Branch C (Sigmoid Calibration / Platt Scaling)** or **Branch B (Expanded Calibration Period)** should be pursued in phase R8 to remediate the collapse, rather than continuing to use isotonic regression on such a starved dataset.
