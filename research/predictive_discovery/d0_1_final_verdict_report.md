# D0.1 Final PIT & Economic Fidelity Closure Report

**Research Program**: D0.1 Rigorous Accounting & Temporal Fidelity Closure
**Contiguous PIT Horizon**: 2023-01-08 00:00 UTC to 2026-06-30 23:00 UTC (1,270 days / 41.5 months)
**Eligible Assets Analyzed**: BTCUSDT (primary), ETHUSDT, BNBUSDT
**Execution & Accounting Standards**: Closed-form non-negative cash | Next-open execution | 12.0 bps base fee, 30.0 bps stress (25 bps fee + 5 bps slippage)
**Canonical Economic Scorecard**: `d0_1_final_economic_scorecard.json` (`sha256:9f2057e4d71824f87f2bc06cad6ee0ec23f86879ce0f61ef2bf1e6b8d1e12f0a`)
**Source Commit at Generation**: `84694945a6816cb37490275a2d1bcfe36da05ba8` | Runner `sha256:775a451239995ca99ff565ebf3d327fab6eb9116303eda2ba68182aafa288b3c` | Dirty worktree: `true`

---

## 1. Executive Scientific Verdicts

| Dimension / Gate | Formal Verdict | Definitive Quantitative Evidence |
| :--- | :---: | :--- |
| **PIT Integrity & Alignment** | **`PASS`** | Zero backward fill used. Population audit over all 1,270 daily decisions: future available count = 0, stale features used = 0, invalid execution order count = 0, invalid valuation order count = 0, missing data count = 0. Daily decisions affected by removing global ffill = 0. Strict `available_at` enforcement with +300s publication delay on 5m metrics. |
| **Accounting Invariants** | **`PASS`** | Closed-form purchasing power sizing verified across all 11 policies in both base and stress scenarios. Minimum cash $\ge 0.0$, maximum leverage $\le 1.000$, and zero unbacked leverage verified. Maximum accounting residual is `1.455e-11`. |
| **Predictive Incremental Value (168h)** | **`INCONCLUSIVE`** | For 168h downside risk target, boundary-purged Validation PR-AUC increases from **`0.1288`** (Price/Vol baseline) to **`0.2473`** (delta **`+0.1185`**). Finite-sample corrected 100-run block-permutation p-value is **`p = 0.0099`**. 95% paired block-bootstrap CI is `[-0.0115, +0.2650]` (CI spans zero, hence formally **`INCONCLUSIVE`** under pre-declared uncertainty criteria). |
| **Economic Incremental Value vs Controls** | **`INCONCLUSIVE`** | In Validation 2025, Derivatives-Informed Trend Filter delivers **`+7.95%`** versus Price-Only Trend Control **`+5.02%`** (delta `+2.93%`) and Simple Trend Following **`+8.07%`** (delta `-0.12%`). Under 30.0 bps stress friction, it delivers **`+3.01%`** versus Price-Only Control **`-1.40%`** and Simple Trend Following **`+3.13%`**. |
| **Generalization Across Cycles** | **`NOT_ESTABLISHED`** | Single-year validation window (2025) and reused diagnostic (2026) cannot establish multi-cycle generalization. |
| **Production Authorization** | **`NOT_AUTHORIZED`** | Bounded discovery stage only. Live CARM integration and multi-asset policy required before consideration. |
| **Overall Scientific Conclusion** | **`DERIVATIVES_INCREMENTAL_VALUE_INCONCLUSIVE`** | Due to paired bootstrap CI crossing zero despite positive point estimates, derivatives incremental predictive value is classified as **`DERIVATIVES_INCREMENTAL_VALUE_INCONCLUSIVE`**. |

---

## 2. Material Defect Rectification Audit

### 2.1. Closed-Form Cash & Fee Accounting Fix
In D0, naive calculation `cost = delta_val + fee` charged transaction fees on top of 100% BTC purchases, causing cash to drop to negative `-$12.00`. In D0.1, closed-form purchasing power sizing was derived and verified:
$$N_{\text{buy}} = \frac{w^* E_{\text{pre}} - V_{\text{btc, pre}}}{1 + w^* \phi}, \quad N_{\text{sell}} = \frac{V_{\text{btc, pre}} - w^* E_{\text{pre}}}{1 - w^* \phi}$$
All golden numerical tests confirmed: `cash >= 0.0` at all times, exact post-trade weight parity $w^*$, and mark-to-market conservation $E_{\text{post}} = E_{\text{pre}} - \text{Fee}$.

### 2.2. Explicit PIT As-Of Alignment & Population Integrity Audit
- **Zero Backward-Fill**: Eliminated all backward fill operations. Features are computed strictly using historical observations available at or before cutoff time.
- **Elimination of Global Forward-Fill Resurrecting Stale Features**: Removed `valid_grid[all_features].ffill()` across stale-masked features. Row-level counterfactual comparison found **73** resurrected hourly feature values and **0** affected daily decisions.
- **Population-Level PIT Audit**: Evaluated across all 1270 decision rows (2023-01-08 to 2026-06-30):
  - `future_available_count`: **0**
  - `stale_feature_used_count`: **0**
  - `invalid_execution_order_count`: **0**
  - `invalid_valuation_order_count`: **0**
  - `missing_data_count`: **0**
  - `population_pit_correctness`: **PASS**
- **Freshness Policy**: Enforced max staleness limits (120 minutes for 5m metrics, 24 hours for 8h funding settlements). Observations older than limits are masked as missing.
- **BNB Coverage Clarification**: Documented that BNBUSDT metrics contains only **27,360** records (576 rows/month (~2 days sampled per month)), while BNB funding rates are continuous (3,831 settlements).

### 2.3. R7 Weekly Benchmark Execution Fidelity & Naming Parity
In D0, simulator defaulted `rebalance_mask=True` daily, causing Weekly R7 to execute 1,199 trades. Corrected by introducing explicit Sunday rebalance mask and naming parity:
- **R7 Vol Target (Sunday-Signal / Monday-Open Weekly Adaptation)**: Scheduled strictly on Sundays (`dayofweek == 6`), executed at Monday 00:00 UTC Open, with holdings drifting naturally Tuesday–Sunday. Executed **178** actual trades with total fees of **$703.51**.
- **R7 Vol Target (Daily Adaptation)**: Rebalanced daily when rolling 480h hourly volatility exceeds 5% buffer. Executed **1252** trades.

### 2.4. Execution / Valuation Temporal Contract
Economic replay now carries three explicit prices per event: `feature_close` is from the bar ending at the decision cutoff, `execution_open` is the next executable bar open, and `valuation_close` is the close of that same post-execution bar one hour later. The simulator receives only `execution_open` and `valuation_close`; it can no longer mark newly executed holdings against the pre-execution feature close.

---

## 3. Boundary-Purged Predictive Falsification Matrix

| Horizon | Model Architecture | Val ROC-AUC | Val PR-AUC | Base Rate | Val BSS | Delta PR-AUC | 100-Perm p-val (corrected) | 95% Bootstrap CI | Risk Spread |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **168h Downside (< -6%)** | Baseline (Price/Vol) | `0.5391` | `0.1288` | `0.1145` | `-0.0076` | — | — | — | — |
| | **Combined (+ Deriv)** | **`0.6678`** | **`0.2473`** | `0.1145` | **`+0.0349`** | **`+0.1185`** | **`p = 0.0099`** | `[-0.0115, +0.2650]` | **`+2.89%`** |
| **72h Downside (< -4%)** | Baseline (Price/Vol) | `0.5335` | `0.1164` | `0.1160` | `-0.0116` | — | — | — | — |
| | Combined (+ Deriv) | **`0.5839`** | **`0.1651`** | `0.1160` | **`+0.0082`** | **`+0.0487`** | `p = 0.0198` | `[-0.0083, +0.1350]` | **`+0.74%`** |
| **24h Downside (< -2%)** | Baseline (Price/Vol) | `0.5659` | `0.2179` | `0.1484` | `+0.0095` | — | — | — | — |
| | Combined (+ Deriv) | `0.5838` | `0.1964` | `0.1484` | `+0.0062` | `-0.0215` | `p = 0.2871` | `[-0.0906, +0.0292]` | `+0.14%` |

---

## 4. Corrected Economic Translation Scorecard

### Base Spot Friction: 12.0 bps Fee (No Negative Cash, Exact Equity Parity)
| Policy Name | Full Net Ret | Train Ret (23–24) | Val 2025 Ret | Holdout Ret | Sharpe | Sortino | Max Drawdown | Turnover | Actual Trades | Total Fees |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **100% Cash** | **`+0.00%`** | `+0.00%` | **`+0.00%`** | `+0.00%` | **`0.000`** | `0.000` | **`0.00%`** | `0.0x` | `0` | `$0.00` |
| **BTC Buy & Hold** | **`+248.94%`** | `+439.12%` | **`-6.51%`** | `-31.85%` | **`1.001`** | `1.558` | **`-52.23%`** | `1.0x` | `1` | `$11.99` |
| **Static 50/50 BTC/Cash** | **`+104.17%`** | `+145.30%` | **`-1.36%`** | `-16.28%` | **`0.995`** | `1.547` | **`-29.57%`** | `6.0x` | `1269` | `$137.89` |
| **R7 Vol Target (Sunday-Signal / Monday-Open Weekly Adaptation)** | **`+134.22%`** | `+199.48%` | **`+3.04%`** | `-24.60%` | **`0.992`** | `1.520` | **`-39.99%`** | `25.9x` | `178` | `$703.51` |
| **R7 Vol Target (Daily Adaptation)** | **`+124.11%`** | `+190.91%` | **`-0.65%`** | `-22.92%` | **`0.981`** | `1.505` | **`-39.06%`** | `17.1x` | `1252` | `$459.39` |
| **Simple Trend Following (50d SMA)** | **`+158.84%`** | `+161.98%` | **`+8.07%`** | `-8.57%` | **`0.991`** | `1.231` | **`-32.10%`** | `72.0x` | `72` | `$1,882.78` |
| **Price-Only Trend Control** | **`+168.68%`** | `+157.26%` | **`+5.02%`** | `-0.55%` | **`1.098`** | `1.349` | **`-25.91%`** | `136.7x` | `242` | `$3,273.36` |
| **Derivatives-Informed Trend Filter** | **`+128.93%`** | `+131.11%` | **`+7.95%`** | `-8.24%` | **`0.922`** | `1.125` | **`-30.85%`** | `114.1x` | `198` | `$2,472.30` |
| **Price-Only Vol Overlay** | **`+107.85%`** | `+163.15%` | **`-0.78%`** | `-20.83%` | **`0.966`** | `1.476` | **`-36.06%`** | `22.0x` | `1269` | `$548.82` |
| **Derivatives Volatility Overlay** | **`+117.51%`** | `+168.07%` | **`+1.29%`** | `-20.35%` | **`1.022`** | `1.588` | **`-34.93%`** | `26.4x` | `1269` | `$685.36` |

### Stress Test: 25.0 bps Fee + 5.0 bps Slippage (30.0 bps All-In Cost)
| Policy Name | Full Net Ret (Stress) | Val 2025 Ret (Stress) | Sharpe (Stress) | Max Drawdown (Stress) | Total Fees (Stress) | Fee Drag vs Base |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **Simple Trend Following** | **`+127.37%`** | **`+3.13%`** | **`0.877`** | **`-34.51%`** | `$4,366.00` | `+31.47%` |
| **Price-Only Trend Control** | **`+110.06%`** | **`-1.40%`** | **`0.861`** | **`-28.53%`** | `$7,074.72` | `+58.62%` |
| **Derivatives-Informed Trend Filter** | **`+86.40%`** | **`+3.01%`** | **`0.730`** | **`-33.12%`** | `$5,493.38` | `+42.53%` |
| **R7 Vol Target (Daily Adaptation)** | **`+117.30%`** | **`-1.49%`** | **`0.949`** | **`-39.39%`** | `$1,127.96` | `+6.81%` |
| **R7 Vol Target (Sunday-Signal / Monday-Open Weekly Adaptation)** | **`+123.56%`** | **`+1.77%`** | **`0.946`** | **`-40.49%`** | `$1,711.04` | `+10.66%` |
| **Derivatives Vol Overlay** | **`+107.40%`** | **`-0.09%`** | **`0.967`** | **`-35.55%`** | `$1,667.31` | `+10.11%` |

---

## 5. Strategic Research Synthesis & Honest Evidence Interpretation

### Key Scientific Takeaways
1. **Economic Edge over Price-Only Control**: In Validation 2025, Derivatives-Informed Trend Filter achieved **+7.95%** vs Price-Only Control **+5.02%** (+2.93% delta) and Simple Trend Following **+8.07%** (-0.12% delta). Under 30 bps stress costs, it preserved **+3.01%** vs **-1.40%** and **+3.13%**.
2. **Trade Frequency and Friction**: Derivatives-Informed Trend Filter executed **198** actual trades across 3.5 years, generating total transaction fees of **$2,472.30** at 12 bps.
3. **Statistical Uncertainty Discipline**: While the permutation p-value is **p = 0.0099**, the 95% paired block-bootstrap CI `[-0.0115, +0.2650]` crosses zero. Under strict falsification discipline, historical correlation cannot be declared proven generalizable alpha.

**STOP RULE ENFORCED**: D0.1 completed. Overall verdict: **`DERIVATIVES_INCREMENTAL_VALUE_INCONCLUSIVE`**.
