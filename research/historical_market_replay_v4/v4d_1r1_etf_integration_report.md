# HMR-V4D-1-r1 Confirmatory ETF Integration Audit Report

> **Run class**: `CONFIRMATORY` | **Timestamp**: `2026-08-16T15:41:48.997148+00:00`

## Governance Rationale & Verdict Summary

- **Verdict**: `INTEGRATION_NOT_PROMOTED`
- **Economic Non-inferiority**: `PASS`
- **Risk Improvement**: `FAIL`
- **Risk-adjusted Utility**: `NOT_DEMONSTRATED`
- **ML Training**: `BLOCKED — overall_verdict is INTEGRATION_NOT_PROMOTED`

### Pre-registered Rules & Thresholds

| Gate / Parameter | Rule / Policy Source | Value |
| :--- | :--- | :--- |
| I1 rule | Frozen sizing adjustment | `Q5 -> 0.5x size, Q1-Q4 -> 1.0x` |
| I2 rule | Frozen exit width adjustment | `Q5 -> SL -2.25%, TP +4.5%; Q1-Q4 -> SL -1.5%, TP +3.0%` |
| G2 EV floor | Independent economic non-inferiority policy | `-5.0 bps` |
| G3 CVaR95 improvement | Volatility utility criteria | `10.0%` |
| G4 Max DD improvement | Drawdown mitigation criteria | `5.0%` |
| G5 Sharpe floor | Independent risk-adjusted policy | `-0.5` |

> [!IMPORTANT]
> **Threshold Provenance**: Thresholds (G2, G5) were frozen prior to execution based on
> independent economic and risk policies — not derived from observed exploratory run results.

## Signal Breakdown

| Metric | Count | % |
| :--- | :---: | :---: |
| Total signals tested | `13851` | 100% |
| Q5 signals (high-vol, 0.5× size / wider SL) | `2306` | `16.65%` |
| Q1–Q4 signals (baseline) | `11545` | `83.3%` |
| Unique ETF publication states (clustered) | `357` | — |

---

## Use Case 1: Volatility-Aware Sizing (I1)

**Frozen rule**: Q5 → 0.5× position size; Q1–Q4 → 1.0×

| Metric | Baseline | Vol-Aware (I1) | Δ | Status |
| :--- | :---: | :---: | :---: | :---: |
| Net EV (bps) | 18.93 | 17.07 | -1.85 | ✅ PASS (Survival) |
| Sharpe | 8.599 | 8.266 | -0.333 | ✅ PASS (Survival) |
| Max Drawdown (%) | 9.80 | 9.80 | 0.00 | ❌ FAIL (No Utility) |
| CVaR 95 (%) | -0.431496 | -0.416043 | 0.0155 | ❌ FAIL (No Utility) |
| CVaR 99 (%) | -0.604832 | -0.591699 | — | — |
| Win Rate (%) | 72.5002 | 72.5002 | — | — |
| Worst Trade (%) | -1.02 | -1.02 | — | — |
| Stop-Hit Rate (%) | 0.0 | 0.0 | — | — |
| Avg Bars Held | 72.0 | 72.0 | — | — |

### Clustered Inference (removing intraday correlation)

| Metric | Clustered Baseline | Clustered Vol-Aware (I1) |
| :--- | :---: | :---: |
| Clustered EV (bps) | 18.68 | 16.88 |
| Clustered Sharpe | 21.956 | 20.884 |

**I1 gate verdict**: `INTEGRATION_NOT_PROMOTED`

---

## Use Case 2: Dynamic Stop / Target Widths (I2)

**Frozen rule**: Q5 → SL −2.25%, TP +4.5%; Q1–Q4 → SL −1.5%, TP +3.0%

| Metric | Baseline | Dynamic Widths (I2) | Δ |
| :--- | :---: | :---: | :---: |
| Net EV (bps) | 18.93 | 18.93 | 0.00 |
| Max Drawdown (%) | 9.80 | 9.80 | 0.00 |
| Stop-Hit Rate (%) | 0.0 | 0.0 | — |
| Target-Hit Rate (%) | 0.0 | 0.0 | — |
| CVaR 95 (%) | -0.431496 | -0.431496 | — |
| Avg Bars Held | 72.0 | 72.0 | — |

**I2 gate verdict**: `CLOSED_NOT_EVALUATED_ARCHITECTURE_BOUNDARY`

---

## Simulation Architecture Boundary

> [!IMPORTANT]
> The outcome scaffold stores pre-computed 72-bar forward returns. Under the long signal set, the full
> return distribution ranges from −1.02% to +1.57%. Since neither the −1.5% SL nor the +3.0% TP bounds
> are ever crossed in this range, all trades timeout at 72 bars. This explains why stop-hit rates are 0.0%
> and I2 metrics are identical to baseline.
>
> Evaluating exit width modifications requires **path-aware OHLCV or finer data**, not the pre-computed
> outcome scaffold. Given that I1 sizing has failed utility gates, I2 is closed as
> `CLOSED_NOT_EVALUATED_ARCHITECTURE_BOUNDARY` to conserve engineering resources.

---

## Gate Summary

| Gate | Result |
| :--- | :--- |
| `G0_data_pit` | ✅ PASS |
| `G1_clustered_inference_i1` | ✅ PASS |
| `G1_clustered_inference_i2` | ✅ PASS |
| `G2_ev_noninferiority_i1` | ✅ PASS |
| `G3_cvar_improvement_i1` | ❌ FAIL — CVaR 95 improvement 3.6% < threshold 10.0% |
| `G4_dd_improvement_i1` | ❌ FAIL — Max DD delta 0.00%, improvement 0.0% < 5.0% |
| `G5_sharpe_noninferiority_i1` | ✅ PASS |
| `G6_period_stability` | ✅ PASS — Period B delta -2.15 bps, Period C delta -1.58 bps >= floor -5.0 bps |
| `G7_lag_robustness` | ✅ PASS — lagged (+4h) EV delta -1.85 bps >= floor -5.0 bps |

**I1 verdict**: `INTEGRATION_NOT_PROMOTED`
**I2 verdict**: `CLOSED_NOT_EVALUATED_ARCHITECTURE_BOUNDARY`
**Overall verdict**: **`INTEGRATION_NOT_PROMOTED`**
**ML training**: `BLOCKED — overall_verdict is INTEGRATION_NOT_PROMOTED`
