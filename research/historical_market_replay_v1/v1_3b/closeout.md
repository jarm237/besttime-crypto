# HMR-V1.3B Closeout Report

**Phase**: Diagnostic Ablation  
**Status**: ✅ **COMPLETE**  
**Date**: 2026-08-14  

---

## Acceptance Criteria Checklist

| Diagnostic Area | Verdict | Evidence / Finding |
| :--- | :---: | :--- |
| **TECHNICAL_SIGNAL_EDGE** | **NO** | `TECHNICAL_ONLY` Net PnL = -$1,975.81, Win Rate = 12.66%, PF = 0.054. |
| **RAW_MODEL_DISCRIMINATION** | **YES** | Raw model SELL ROC-AUC = **0.7399**, monotonic win rate (Q1: 4.4% → Q5: 44.7%). |
| **CALIBRATION_VALUE** | **NEGATIVE** | Calibration destroys resolution (SELL ROC-AUC 0.74 → 0.62) and collapses output. |
| **META_VALUE** | **NEUTRAL** | `NO_META` yields 0 trades; not the primary bottleneck. |
| **THRESHOLD_CONTRACT** | **MISMATCH** | Scale mismatch (thresholds 0.65/0.35 vs max calibrated 0.16) + sign mismatch on SELL EV. |
| **BUY_SIDE_EDGE** | **WEAK / UNKNOWN** | Extremely starved cohort (n=45 candidates), raw ROC-AUC = 0.60. |
| **SELL_SIDE_EDGE** | **YES (Model)** | Strong raw discriminative ranking on short trades. |
| **EXIT_CAPTURE** | **POOR** | `TECHNICAL_ONLY` Mean MFE = 0.72%, MAE = -0.79%, 70% trades have negative gross return. |
| **COST_DRAG** | **MATERIAL** | Friction adds -$1,172.69 drag on `TECHNICAL_ONLY` (-$803 gross vs -$1,975 net). |

---

## Results Matrix

| Scenario | Trades | BUY | SELL | Gross PnL ($) | Net PnL ($) | Win Rate | Profit Factor | MaxDD |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| **CURRENT_CLEAN** | 0 | 0 | 0 | — | — | — | — | — |
| **TECHNICAL_ONLY** | 379 | 40 | 339 | -803.12 | -1,975.81 | 12.66% | 0.054 | 20.17% |
| **NO_CALIBRATION** | 0 | 0 | 0 | — | — | — | — | — |
| **NO_META** | 0 | 0 | 0 | — | — | — | — | — |
| **TECHNICAL_LONG_ONLY** | 37 | 37 | 0 | -80.12 | -203.35 | 13.51% | 0.051 | 2.32% |
| **TECHNICAL_SHORT_ONLY** | 329 | 0 | 329 | -717.14 | -1,743.94 | 13.68% | 0.060 | 17.86% |
| **NO_CALIB_LONG_ONLY** | 0 | 0 | 0 | — | — | — | — | — |
| **NO_CALIB_SHORT_ONLY** | 0 | 0 | 0 | — | — | — | — | — |

---

## Exit Decomposition (B7)

| Scenario | BAD_ENTRY | COST_DESTROYED | EDGE_NOT_CAPTURED | GOOD_CAPTURE | Mean MFE | Mean MAE | Capture Ratio |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| **TECHNICAL_ONLY** | 265 | 66 | 0 | 48 | 0.72% | -0.79% | -41,686.81% |
| **TECHNICAL_LONG_ONLY** | 24 | 8 | 0 | 5 | 0.75% | -0.78% | -41,148.88% |
| **TECHNICAL_SHORT_ONLY** | 224 | 60 | 0 | 45 | 0.75% | -0.82% | -37,793.56% |

**Interpretation**: 
- **69.9%** of technical entries result in an immediate loss (`BAD_ENTRY`), proving the entries themselves lack edge without filtering.
- **17.4%** of technical entries are gross profitable but eaten by fees and slippage (`COST_DESTROYED`), confirming that cost friction is a significant headwind.

---

## Detailed Findings & Diagnostic Analysis

### 1. The Sign Mismatch in the Expected Value (EV) Gate

Under the corrected `P(win | proposed_trade)` semantics, `expected_return` is calculated as the expected return *of the trade* (which is a positive number for a profitable trade, regardless of whether it is a BUY or a SELL):
$$\text{Expected Return} = P(\text{win}) \times \text{TP} - P(\text{loss}) \times \text{SL}$$

However, in `MetaDecisionEngine.decide`, the SELL trade gating condition checks:
```python
elif expected_return <= -self.min_ev_pct and posterior <= self.sell_threshold:
    action = "SELL"
```
This check expects `expected_return` to be **negative** for SELL/SHORT trades. 
- Under the old `P(up)` semantics, this sign check made sense because a profitable short trade is associated with a negative asset price change.
- Under the new `P(win)` semantics, a profitable short trade is associated with a **positive** expected trade return.
- Consequently, any valid, high-probability SHORT candidate is blocked because its expected return is positive (failing `expected_return <= -0.05`).
- This explains why **`NO_CALIBRATION` generated exactly 0 trades**! Bypassing calibration was not enough because the sign mismatch in the EV gate blocked all short trades, and the scale mismatch blocked all long trades.

### 2. Model Discrimination vs. Calibrator Collapse

The threshold-free ranking diagnostics (B0) yielded a massive insight:
- **The Raw Model possesses strong discriminative power** for SELL/SHORT trades, with a **ROC-AUC of 0.7399** and **PR-AUC of 0.4354**.
- Monotonic quintile win rates for the raw model confirm this predictive value:
  - **Q1 (lowest score)**: 4.4% win rate, -0.86% mean gross return.
  - **Q3 (median score)**: 19.5% win rate, -0.46% mean gross return.
  - **Q5 (highest score)**: **44.7% win rate**, -0.10% mean gross return.
- However, **Isotonic Calibration destroys this resolution**. Because the calibration cohort contains only 3 wins in 409 samples, the calibrator collapses all probabilities into a tight, low range (max 16.67%).
- This drops the ROC-AUC from **0.74 to 0.62** and maps all candidates to the same low probability range, removing all sorting resolution.

---

## Strategic Recommendation for V1.3C (Root-Cause Classification)

The diagnostic results of V1.3B point to a clear classification:

1. **TECHNICAL_SIGNAL_HAS_NO_EDGE**: Technical triggers alone are unprofitable and heavily drag. Filtering is mandatory.
2. **MODEL_HAS_EDGE**: The ML ensemble has solid resolution/discrimination (ROC-AUC ~0.74).
3. **CALIBRATION_COLLAPSE**: Isotonic calibration destroys resolution due to extreme positive class starvation.
4. **THRESHOLD/EV CONTRACT MISMATCH**: The decision engine has a scale mismatch (0.65 threshold vs 0.16 max calibrated prob) and a sign mismatch (checking negative EV for short positions).

The next phase `HMR-V1.3C` should classify and resolve these bottlenecks by:
- Aligning the expected return sign in the decision engine for short positions.
- Bypassing or replacing the collapsed calibrator (e.g., evaluating dynamic threshold scaling or raw probability optimization).
- Performing threshold optimization on raw model outputs.
