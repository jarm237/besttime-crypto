# S2-A Source Fidelity, Causal Execution & Economic Evidence Closure Addendum

**Repository:** `jarm237/besttime-crypto`
**Branch:** `research/s2a-cross-asset-opportunity-screen`
**Starting Baseline Commit:** `6613c4eb889b1244e544db49a21b23a08b6daca3`
**Audit Completion Date:** `2026-11-18T14:22:00+00:00`
**Auditor Role:** Senior Quantitative Researcher & Financial Simulation Auditor

> **Scientific status update:** The authoritative scoped interpretation is documented in `s2a_bounded_fidelity_addendum.md`. It supersedes earlier unqualified PIT, execution-fidelity, asset-contribution and buffer-calibration claims. Historical economic metrics remain unchanged.

---

## 1. Executive Closure Verdicts

```text
========================================================================================
S2A_IMPLEMENTATION_STATUS              = COMPLETED_VALIDATED
S2A_SOURCE_FIDELITY                    = PASS
S2A_EXECUTION_TIMING                   = PASS_WITH_EXPLICIT_ZERO_LATENCY_ASSUMPTION
S2A_PIT_CORRECTNESS                    = PASS
S2A_ACCOUNTING_CORRECTNESS             = PASS
S2A_FEE_RECONCILIATION                 = PASS
S2A_LEDGER_SCORECARD_CONSISTENCY       = PASS
S2A_TOP2_SELECTION                     = NOT_SUPPORTED
S2A_BREADTH_TIMING                     = NOT_SUPPORTED
S2A_COMBINED_TOP2_BREADTH              = NOT_SUPPORTED
S2A_ECONOMIC_OPPORTUNITY               = NOT_SUPPORTED
GENERAL_CROSS_ASSET_ALLOCATION_VALUE   = NOT_ESTABLISHED
S2B_NEURAL_PILOT_AUTHORIZATION         = NOT_AUTHORIZED
PRODUCTION_PROMOTION                   = NOT_AUTHORIZED
OVERALL_CONCLUSION                     = S2A_CLOSED_VALIDATED_NEGATIVE
========================================================================================
```

---

## 2. Source Fidelity & Causal Execution Audit

### A. Timestamp & Candle Availability Semantics
- **Source Data:** Binance Spot 1h cached parquet data (`data/historical_unified_replay/`), 42,739 hourly timestamps across BTC, ETH, SOL, BNB from 2022-01-01 00:00 UTC to 2026-11-16 19:00 UTC.
- **Bar Definition:** In Binance Spot hourly candles, timestamp $t_{open}$ is the bar opening time; the bar closes at $t_{close} = t_{open} + \text{1 hour}$.
- **Feature Cutoff:** Decision at day $t$ 23:59:59 UTC uses closed hourly bars strictly up to `source_feature_bar` = 23:00 UTC (which closes at 23:59:59 UTC).
- **Execution:** Rebalancing trades execute at Day $t+1$ 00:00:00 UTC Open (`open_prices[t]`). Open and Close do not share a timestamp.
- **Latency Assumption:** Zero-latency execution is explicitly assumed between the 23:59:59 candle close and the 00:00:00 next candle open. No future candle data is leaked.
- **Valuation:** Portfolio equity is marked-to-market hourly using subsequent candle Close prices (`close_prices[t]`), ensuring $t_{exec} \le t_{val}$.

### B. Row-Level Trace Verification

| Trace Scenario | Date (UTC) | Feature Bar (Open $\to$ Close) | Decision Timestamp | Execution Bar | Execution Price (BTC) | Pre-Trade Equity | Fee Paid | Post-Trade Equity | Notes |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **Normal Day** | 2024-06-15 | 23:00 $\to$ 23:59:59 | 23:59:59 | 2024-06-16 00:00 Open | $66,228.25 | $20,508.98 | $12.31 | $20,496.67 | Signal rebalance from 100% Cash to 25% BTC, 25% ETH, 50% Cash. |
| **Split Boundary** | 2023-12-31 | 23:00 $\to$ 23:59:59 | 23:59:59 | 2024-01-01 00:00 Open | $42,283.58 | $14,904.03 | $0.00 | $14,904.03 | Divergence 0.28% < 2.0% buffer threshold. No trade executed, zero fee. |
| **Market Halt Gap** | 2023-03-24 | 23:00 $\to$ 23:59:59 | 23:59:59 | 2023-03-25 00:00 Open | $27,454.46 | $8,512.35 | $10.21 | $8,502.13 | Breadth turned risk-off, clean rebalance into 100% Cash ($8,502.13). |

---

## 3. Portfolio Accounting & Fee Reconciliation

- **Weight and Cash Invariants:** For all $N=4$ crypto assets, target weights $w_i \ge 0$, cash weight $w_{cash} \ge 0$, $\sum w_i + w_{cash} = 1.0$.
- **Leverage Invariant:** Cash never goes negative ($cash \ge 0$), no unbacked leverage.
- **Fee Accounting:** 12 bps base and 30 bps stress fee charged exclusively on executed crypto notional ($traded\_notional = equity\_before \cdot \sum |\Delta w_{crypto}|$). Cash reallocations incur 0.0% fee.
- **Turnover Definition:** `gross_asset_turnover` is defined as the cumulative sum of step-wise two-sided asset weight changes $\sum_k \sum_i |\Delta w_{i,k}|$, which totals 250.16x of portfolio value across the 4.8-year full horizon.
- **Churn Forensics:**
  - Total executed rebalances: **884** (out of 1,751 calendar days).
  - Signal-driven rebalances: **860** (97.3% of trades), incurring **$11,357.53** in fees (99.8%).
  - Drift-restoration rebalances: **24** (2.7% of trades), incurring **$24.75** in fees (0.2%).
  - Conclusion: Churn is overwhelmingly **SIGNAL-DRIVEN**, caused by frequent top-2 ranking rotations and market breadth risk-on/risk-off toggling. The 2.0% buffer successfully eliminated almost all drift churn.

---

## 4. Policy Performance & Attribution Decomposition

### Validation 2024 (Primary Diagnostic Split)

| Policy | Net Return (12 bps) | Net Return (30 bps) | Sharpe (12 bps) | Max Drawdown | Trades | Gross Turnover | Total Fees (12 bps) | Mean Cash W |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **A. BTC Buy & Hold** | +121.04% | +120.64% | 1.76 | -32.31% | 1 | 1.00x | $12.00 | 0.0% |
| **B. EW 4-Asset Buy & Hold** | +94.48% | +94.13% | 1.40 | -37.88% | 1 | 1.00x | $12.00 | 0.0% |
| **C. Static 50/50 EW** | **+47.35%** | **+47.05%** | **1.43** | **-19.23%** | 16 | 1.11x | **$15.41** | 49.7% |
| **D. Selection Top-2** | +31.71% | +16.57% | 1.03 | -23.77% | 143 | 67.79x | $964.16 | 49.9% |
| **E. Timing Breadth** | +52.79% | +35.54% | 1.22 | -22.09% | 125 | 66.49x | $1,088.66 | 37.0% |
| **F. Combined Top-2** | +34.17% | +3.55% | 0.87 | -29.13% | 199 | 143.65x | $2,233.22 | 37.0% |

### Economic Attribution

| Split Horizon | Selection Value ($D - C$) | Timing Value ($E - C$) | Combined Value ($F - \max(D,E,C)$) | F vs Static ($F - C$) | Strongest Control |
| :--- | :---: | :---: | :---: | :---: | :--- |
| **Train (2022–2023)** | +22.21% | -10.62% | +9.77% | +31.98% | Policy D (+39.26%) |
| **Validation (2024)** | **-15.64%** | **+5.44%** | **-18.62%** | **-13.18%** | Policy E (+52.79%) |
| **Reused (2025–2026)** | -5.86% | -19.45% | -14.12% | -14.12% | Policy C (-15.45%) |
| **Full Horizon (2022–2026)** | -1.47% | -40.06% | -5.10% | -5.10% | Policy C (+45.94%) |

### Ex-Post Comparator vs True Timing Skill
- Policy E achieved +52.79% return with an average exposure of 63.0%.
- An **ex-post static exposure-matched comparator** (fixed 63.0% EW / 37.0% cash) achieved **+61.08%** return with a **1.44 Sharpe** and only **$23.81** in fees.
- Dynamic timing underperformed the static beta exposure by **-8.29 percentage points** after transaction friction. This confirms that Policy E's excess return over Policy C was entirely beta-driven, not timing alpha.

---

## 5. Statistical Falsification Summary

- **Paired Block Bootstrap (Validation 2024 Daily Returns):**
  - $F - C$: 95% CI = `[-0.001437, +0.001729]` (covers zero, statistically insignificant).
  - $D - C$: 95% CI = `[-0.000800, +0.000356]` (covers zero).
  - $E - C$: 95% CI = `[-0.000936, +0.001646]` (covers zero).
- **Temporal Shuffle (100 runs):** Shuffled timing return mean = `+33.79%` (Std = `27.92%`), range `[-30.68%, +120.81%]`.
- **Rank Permutation (100 runs):** Shuffled selection return mean = `+18.14%` (Std = `11.54%`), range `[-17.16%, +48.87%]`.

---

## 6. S2-B Gate Audit & Final Hard Stop

- All 5 out of 6 quantitative gates failed:
  1. Failed to outperform strongest control ($F = +34.17\%$ vs $E = +52.79\%$).
  2. Incremental return at 30 bps stress fee collapsed to $-43.50\%$ vs Static 50/50.
  3. Risk-adjusted Sharpe (0.87) and Max Drawdown (-29.13%) severely degraded vs Static 50/50 (Sharpe 1.43, MaxDD -19.23%).
  4. Selection value negative (-15.64%); timing Sharpe degraded.
  5. Bootstrap 95% confidence intervals cover zero.
- **S2-B Neural Pilot Authorization is NOT AUTHORIZED.**
- Research workstream S2-A is hereby **CONCLUDED** with a verified negative finding.
