# VCB V5 Cross-Sectional Holdout Research Report

## 1. Executive Summary

- **Pipeline**: `hmr_v5_vcb_v5_cross_sectional_research`
- **Candidate ID**: `VCB_V5_SELL_ONLY_9ASSET`
- **Specification SHA-256**: `524ac4ed6a7ff7f9d72a413296668b61d486d962d229a4bb7d02cc505e5d1fbf`
- **Semantic Artifact SHA-256**: `852a35b1276638ea76b9dad00a30cfd3a2fd3aa04c43ba6de29407d0d538634a`
- **Epistemic Classification**: `DEBUG_EXPOSED_CROSS_SECTIONAL_DIAGNOSTIC`
- **Admission Verdict**: `VCB_V5_REJECTED_CROSS_SECTIONAL_HOLDOUT`
- **System Operating Disposition**:
  - `candidate_selection_verdict`: `NO_CANDIDATE_SELECTED`
  - `prospective_status`: `PROSPECTIVE_NOT_STARTED`
  - `runtime_candidate_spec`: `null`
  - `activation_manifest`: `null`

---

## 2. Gate Evaluation Scorecard (Primary Holdout Universe: DOGE, IOTA, NEAR, SOL, TRX, ZEC)

| Gate | Description | Threshold | Observed | Verdict |
|---|---|---|---|---|
| Gate 1 | Sample Size (Trades) | $\ge 100$ | 748 | ✅ PASS |
| Gate 2 | Net Expectancy @ 14 bps | $> 0.0$ bps | 2.14 bps | ✅ PASS |
| Gate 3 | Profit Factor | $> 1.0$ | 1.0205 | ✅ PASS |
| Gate 4 | Daily Block Bootstrap 95% CI Lower | $> 0.0$ bps/day | -3.354 bps/day | ❌ FAIL |
| Gate 5 | Cross-Sectional Breadth | $\ge 4$ active assets | 6 assets | ✅ PASS |
| Gate 6 | Concentration Risk | $< 80.0\%$ max share | 19.7% | ✅ PASS |
| Gate 7 | Maximum Drawdown | $\le 20.0\%$ | 20.28% | ❌ FAIL |
| Gate 8 | Friction Tolerance @ 20 bps | $\ge -5.0$ bps | -3.85 bps | ✅ PASS |

---

## 3. Primary Holdout Quantitative Metrics

- **Period**: `[2024-01-01, 2026-07-01)` (912 calendar days)
- **Executed Trades**: 748
- **Gross Expectancy**: 16.15 bps
- **Net Expectancy @ 14 bps**: 2.14 bps
- **Win Rate**: 34.9%
- **Profit Factor**: 1.0205
- **Daily Block Bootstrap 95% CI**: `[-3.354, 4.244]` bps/day
- **Cost Sensitivity**:
  - Net @ 10 bps: 6.15 bps
  - Net @ 14 bps: 2.14 bps
  - Net @ 20 bps: -3.85 bps
  - Net @ 30 bps: -13.85 bps

---

## 4. Trade Rate & Sample Accumulation Velocity

| Metric | V4 Baseline (3 Design Assets) | V5 Holdout (6 Holdout Assets) | Speedup Factor |
|---|---|---|---|
| Trades / Calendar Day | 0.2202 | 0.8202 | 3.72x |
| Projected Trades (90 Days) | 19.8 | 73.8 | 3.72x |
| Estimated Days to N=100 | 454.1 days | 121.9 days | - |

---

## 5. Temporal Stability Diagnostics

| Sub-Window | Trades | Net Expectancy @ 14 bps | Profit Factor | Win Rate |
|---|---|---|---|---|
| HOLDOUT_2024_ANNUAL | 298 | 6.77 bps | 1.0661 | 35.9% |
| HOLDOUT_2025_ANNUAL | 291 | -5.67 bps | 0.9471 | 33.3% |
| HOLDOUT_2026_H1_SEMESTER | 159 | 7.76 bps | 1.0760 | 35.8% |

---

## 6. Diagnostic Reference: Exposed Design Assets (BTC, ETH, BNB)

- **Executed Trades**: 308
- **Net Expectancy @ 14 bps**: 0.58 bps
- **Note**: Exposed design assets are presented strictly as a diagnostic baseline and do not enter primary admission criteria.

---

## 7. Chronology Audit & Epistemic Demotion

- **Chronology Audit Verdict**: `PRE_REGISTRATION_NOT_PROVABLE`
- **Epistemic Classification**: `DEBUG_EXPOSED_CROSS_SECTIONAL_DIAGNOSTIC`
- **Earliest Artifact Filesystem Creation**: `2026-11-04T02:17:21.769903+00:00`
- **Internal Spec Lock Time**: `2026-11-04T03:16:10.906048+00:00`
- **Earliest Known Raw Read / Debug Run**: `2026-11-04T02:17:21+00:00`
- **Governance Epistemic Note**: Candidate specification was originally intended to lock prior to reading holdout candles, but during debugging data was read and evaluator was launched before the final lock artifact. Chronology audit verdict is PRE_REGISTRATION_NOT_PROVABLE. Metrics are retained strictly as post-hoc diagnostic data, not confirmatory out-of-sample evidence, and cannot be used for prospective admission.
- **Historical Search Status**: `HISTORICAL_CANDIDATE_SEARCH_STOPPED`
- **Historical Stop Rationale**: Candidates V1 through V5 have all failed primary daily block bootstrap confidence interval selection criteria (Gate 4 / Gate 7) and/or lack independent unexposed pre-registration chronology. The complete 2023-2026-H1 historical market dataset in this workspace is now fully consumed. No untouched historical validation window remains. Any further candidate exploration on this dataset increases multiple testing bias and overfitting risk. Candidate search on historical data is officially stopped.
