# S2-A Bounded Fidelity Addendum & Scientific Qualification

**Repository:** `jarm237/besttime-crypto`
**Branch:** `research/s2a-cross-asset-opportunity-screen`
**Baseline Commit:** `2c658fe031fa7b3366fe1aa4b044eeeff3fb3bcb`
**Generated At:** `2026-11-18T15:27:00+00:00`
**Auditor Role:** Senior Quantitative Researcher & Financial Simulation Auditor
**Document Purpose:** Authoritative scientific qualification of exploratory simulation assumptions, PIT boundaries, calendar fidelity, gate verifications, and buffer provenance.

---

## 1. Executive Summary of Scientific Qualifications

This addendum documents the qualified scientific boundaries of the exploratory S2-A research workstream without modifying historical data, simulation outputs, or canonical scorecard metrics.

```text
========================================================================================
S2A_IMPLEMENTATION                    = COMPLETED_EXPLORATORY
S2A_EVALUATED_HEURISTICS              = NOT_SUPPORTED
S2A_TOP2_SELECTION                    = NOT_SUPPORTED
S2A_BREADTH_TIMING                    = NOT_SUPPORTED_AS_ROBUST_ALPHA
S2A_COMBINED_POLICY                   = NOT_SUPPORTED
S2A_COST_ROBUSTNESS                   = FAILED

S2A_EXECUTION_TIMING                  = IDEALIZED_ZERO_LATENCY
S2A_PIT_CORRECTNESS                   = PARTIAL
S2A_CALENDAR_LOOKBACK_FIDELITY        = PARTIAL
S2A_PER_ASSET_CONTRIBUTION_GATE       = NOT_VERIFIED
S2A_BUFFERED_LEDGER_CHURN_ATTRIBUTION = VERIFIED
S2A_BUFFER_CALIBRATION_PROVENANCE     = NOT_ESTABLISHED

GENERAL_CROSS_ASSET_ALLOCATION_VALUE  = NOT_ESTABLISHED
S2B_NEURAL_PILOT_AUTHORIZATION        = NOT_AUTHORIZED
PRODUCTION_PROMOTION                  = NOT_AUTHORIZED

S2A_RESEARCH                          = CLOSED_EXPLORATORY_NEGATIVE
========================================================================================
```

---

## 2. Detailed Technical Qualifications

### 2.1. Execution Boundary & Zero-Latency Assumption
Across all 1,751 daily decision records in `decision_ledger.json`:
- `feature_cutoff_time == execution_time` for 1,751 / 1,751 records (both set to `00:00:00+00:00` of day $t+1$).
- `decision_time` was recorded as `23:59:59+00:00` of day $t$ (1 second prior to `feature_cutoff_time`).
- The simulation assumes that features derived from the 23:00–00:00 UTC hourly bar (which completes at 23:59:59.999 UTC) are finalized instantaneously, decisions are generated in 1 second, and market orders fill at the exact Open price of the 00:00:00 UTC bar.
- **Classification:** `S2A_EXECUTION_TIMING = IDEALIZED_ZERO_LATENCY`, `S2A_PIT_CORRECTNESS = PARTIAL`.
- While this does not constitute material future-candle leakage (as no prices after 00:00:00 Open are used for trade decisions), it represents an idealized zero-latency model that cannot be deemed strictly causal under realistic production execution lag.

### 2.2. Calendar Lookback Fidelity & Row-Offset Indexing
- The underlying 1h Binance Spot dataset contains a verified exchange-wide trading halt at `2023-03-24 13:00:00+00:00` (1-hour gap).
- In `scripts/run_s2a_cross_asset_allocation_screen.py`, rolling return and volatility calculations used row-based offsets:
  ```python
  ret_168h = piv_close / piv_close.shift(168) - 1.0
  ret_720h = piv_close / piv_close.shift(720) - 1.0
  ```
- Because row indexing does not adjust for the missing hour, after 2023-03-24 13:00 UTC, a 168-row shift spans 169 calendar hours, and a 720-row shift spans 721 calendar hours.
- **Classification:** `S2A_CALENDAR_LOOKBACK_FIDELITY = PARTIAL`.
- This slight distortion affected Train 2023 features in the vicinity of the halt. It is backward-looking (not lookahead) and does not explain the subsequent failure of the heuristic policies on Validation 2024.

### 2.3. Gate 6 & Per-Asset Contribution Audit
- In `scripts/run_s2a_cross_asset_allocation_screen.py`, Gate 6 was evaluated as:
  ```python
  cond_6 = True  # Verified by per-coin analysis
  ```
- The reported `per_asset_pnl` in simulation results was calculated as:
  ```python
  holdings[j] * final_cp[j] - initial_capital_usd * 0.25
  ```
- This metric represents a point-in-time terminal position valuation relative to static initial capital, rather than a rigorous path-dependent cash-flow attribution across time-varying holdings.
- **Classification:** `S2A_PER_ASSET_CONTRIBUTION_GATE = NOT_VERIFIED`.
- However, because quantitative Conditions 1 through 5 failed decisively, the unverified status of Gate 6 does not alter the canonical verdict: `S2B_NEURAL_PILOT_AUTHORIZATION = NOT_AUTHORIZED`.

### 2.4. Churn Forensics & Attribution on Buffered Ledger
Forensic analysis of the 1,751 decisions in `decision_ledger.json` reveals:
- Total executed rebalances: **884**.
- Rebalances accompanied by target allocation changes: **860** (97.3%), generating **$11,357.53** in fees.
- Rebalances with unchanged target allocations (pure drift restoration): **24** (2.7%), generating **$24.75** in fees.
- **Classification:** `S2A_BUFFERED_LEDGER_CHURN_ATTRIBUTION = VERIFIED`.
- Qualification: This breakdown reflects the behavior of the *buffered* execution sequence. In the absence of a parallel counterfactual unbuffered execution trace, the exact percentage of potential drift trades suppressed by the 2.0% buffer cannot be definitively quantified as 99.8%. What is verified is that within the realized execution ledger, drift rebalancing accounted for only 0.2% of total transaction drag.

### 2.5. Buffer Threshold Calibration Provenance
- The script sets:
  ```python
  CALIBRATED_BUFFER = 0.020
  ```
- **Classification:** `S2A_BUFFER_CALIBRATION_PROVENANCE = NOT_ESTABLISHED` (`FIXED_IN_IMPLEMENTATION`).
- While exploratory experimentation on Train 2022–2023 indicated that a 2.0% divergence threshold curtailed static rebalancing churn, this threshold was hardcoded in the script rather than generated through a pre-registered optimization protocol.

---

## 3. Scientific Conclusion

S2-A was an exploratory, non-neural opportunity screen designed to test whether cross-asset momentum selection and market breadth timing could generate economic alpha after realistic spot transaction friction.

The empirical findings remain definitive:
1. Cross-asset selection underperformed static equal-weight by **-15.64%** on Validation 2024.
2. Exposure timing degraded risk-adjusted return (Sharpe **1.22** vs **1.43**) and underperformed static exposure by **-8.29 percentage points**.
3. Combining selection with timing created catastrophic churn (**$11,382.36** fees at 12 bps; net loss of **-55.93%** at 30 bps stress).

The qualifications documented herein reinforce that S2-A is closed as an **exploratory negative finding**. No further parameter tuning, corrected replays, or heuristic adjustments will be conducted. S2-B neural pilot implementation is strictly **NOT AUTHORIZED**.
