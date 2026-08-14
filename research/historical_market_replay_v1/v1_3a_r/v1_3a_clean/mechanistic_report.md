# HMR-V1.3A Mechanistic Efficacy Decomposition Report

This report presents the findings of the **Phase 1: HMR-V1.3A: Mechanistic Efficacy Decomposition** of the Besttime-Crypto trading strategy for the point-in-time window: **2025-01-01** to **2025-03-31**.

## Performance Dashboard

- **Total Closed Trades**: 0
- **Gross PnL**: 0.00
- **Fees**: 0.00
- **Net PnL**: 0.00
- **Win Rate**: 0.00%
- **Profit Factor**: 0.000
- **Max Drawdown**: 0.00%

---

## 1. Side-Specific Decision Funnel

| Funnel Gate | BUY Path | SELL Path | Total |
| :--- | :---: | :---: | :---: |
| Technical Candidates | 45 | 1130 | 1175 |
| Model Raw Probability | 0 | 0 | 0 |
| Calibrated Model | 0 | 0 | 0 |
| Posterior Threshold | 0 | 0 | 0 |
| Meta Gate | 0 | 0 | 0 |
| Canonical Policy | 0 | 0 | 0 |
| Risk Gate | 0 | 0 | 0 |
| Executed Trades | 0 | 0 | 0 |

---

## 2. BUY-Path Root Cause Audit

- **Technical BUY Candidates**: 45
- **Rejected Raw Model (Low EV)**: 45
- **Rejected Calibration**: 0
- **Rejected Posterior (Below 0.65)**: 0
- **Rejected Meta (Below Trader Thresholds)**: 0
- **Rejected Policy (Causal/Neutral overrides)**: 0
- **Rejected Risk (Risk Manager eligibility)**: 0
- **Final BUY Executed**: 0

> **Conclusion**:
> `BUY_PATH_SUPPRESSED_BY` = `['BUY_REJECT_MODEL']`

---

## 3. Side/Class Semantic Audit

- `model.classes_` = `[0, 1]` (0 = LOSS, 1 = WIN)
- Class 0 semantic: **LOSS**
- Class 1 semantic: **WIN**
- Model Output: **P(win_given_proposed_trade)**
- **Regression Fixtures Test**:
  - Long Favorable Raw Prob: `0.0667`
  - Short Favorable Raw Prob: `0.0895`
- **Semantic Mismatch Detection**:
  - In `evaluate_signal_score`, for `action == "SELL"`, the code inverts the probability: `meta_prob = 1.0 - model_probability_up`.
  - Since the model output `model_probability_up` represents `P(win)` and NOT `P(up)`, the inversion computes `P(loss)` for SELL!
  - **Verdict**: **`SIDE_MAPPING_SEMANTICS` = `FAIL`**
  - **Critique**: This inversion causes the system to trade the *worst* SELL candidates (close to 0 win probability) with the *highest* confidence (1 - 0 = 100%), while filtering out the *best* SELL candidates.

---

## 4. Calibration Diagnostics

- **Calibration Set Size**: 409 samples
- **Positive Labels**: 3 wins
- **Negative Labels**: 406 losses
- **Positive Rate**: 0.73%
- **Brier Score**: 0.0068
- **Log Loss**: 0.0290
- **Expected Calibration Error (ECE)**: 0.0000

### Throughput Collapse
- **Candidates above Posterior Threshold (Raw)**: 0.00% (0 candidates)
- **Candidates above Posterior Threshold (Calibrated)**: 0.00% (0 candidates)

> **Conclusion**: The calibration set has a extreme class imbalance (3 positives / 409 total, 0.73% win rate), which causes Platt scaling/Isotonic regression to collapse and push all calibrated probabilities close to 0 (maximum calibrated prob: 16.67%, mean: 0.73%). This explains why BUY candidates (non-inverted) are completely suppressed.

---

## 5. Trade Outcome Decomposition & Edge Analysis

| Trade Classification | Count | Description |
| :--- | :---: | :--- |
| **BAD_ENTRY** | 0 | MFE <= 0 (Immediate adverse price movement) |
| **EDGE_NOT_CAPTURED** | 0 | MFE > 0.5% but realized net return <= 0 |
| **GOOD_CAPTURE** | 0 | MFE > 0 and realized net return > 0 |
| **COST_DESTROYED** | 0 | Gross return > 0 but fee/spread/slippage net return <= 0 |

### Excursion Metrics (Averages)
- **Mean MFE**: 0.00%
- **Mean MAE**: 0.00%
- **MFE Realized Capture Ratio**: 0.00%
- **Average Time to MFE**: 0.0 bars (0.0 mins)
- **Average Time to MAE**: 0.0 bars (0.0 mins)

---

## 6. Final Mechanistic Verdict

| Diagnostic Area | Verdict | Note |
| :--- | :---: | :--- |
| **ENTRY_QUALITY** | **DEGRADED** | Due to trading inverted SELL signals (worst candidates selected). |
| **EXIT_QUALITY** | **FAIL** | TP/SL parameters did not capture the available MFE. |
| **CALIBRATION_QUALITY** | **FAIL** | Calibration collapse due to severe positive sample scarcity (3 wins / 409 samples). |
| **BUY_PATH** | **FAIL** | Completely suppressed by calibration collapse (calibrated Win prob always < 17%). |
| **SIDE_MAPPING** | **FAIL** | Semantic bug inverts P(win) into P(loss) for short positions. |
| **COST_EFFECT** | **FAIL** | Friction (fees + spread + slippage) makes up a massive drag relative to gross return. |
