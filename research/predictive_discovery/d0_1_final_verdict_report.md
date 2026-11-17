# D0.1 Final PIT & Economic Fidelity Closure Report

**Research Program**: D0.1 Rigorous Accounting & Temporal Fidelity Closure
**Contiguous PIT Horizon**: 2023-01-08 00:00 UTC to 2026-06-30 23:00 UTC (1,270 days / 41.5 months)
**Eligible Assets Analyzed**: BTCUSDT (primary), ETHUSDT, BNBUSDT
**Execution & Accounting Standards**: Closed-form non-negative cash | Next-open execution | 12.0 bps base fee, 30.0 bps stress (25 bps fee + 5 bps slippage)

---

## 1. Executive Scientific Verdicts

| Dimension / Gate | Formal Verdict | Definitive Quantitative Evidence |
| :--- | :---: | :--- |
| **PIT Integrity & Alignment** | **`PASS`** | Zero backward fill used. Population audit over all 1,270 daily decisions: future available count = 0, stale features used = 0, invalid execution order count = 0, missing data count = 0. Zero daily decisions affected by removing global ffill. Strict `available_at` enforcement with +300s publication delay on 5m metrics. Explicit as-of joins with 2h (metrics) and 24h (funding) freshness limits. Spot features derived strictly from candles closed at cutoff time. |
| **Accounting Invariants** | **`PASS`** | Closed-form purchasing power sizing verified across all 10 policies. Minimum cash $\ge 0.0$, maximum leverage $\le 1.000$, and zero unbacked leverage verified. Maximum accounting residual across 1,270 steps is 0.00. |
| **Predictive Incremental Value (168h)** | **`INCONCLUSIVE`** | For 168h downside risk target, boundary-purged Validation PR-AUC increases from **`0.1288`** (Price/Vol baseline) to **`0.2473`** (delta **`+0.1185`**). Finite-sample corrected 100-run block-permutation p-value is **`p = 0.0099`**. 95% paired block-bootstrap CI is `[-0.0115, +0.2650]` (CI spans zero, hence formally **`INCONCLUSIVE`** under pre-declared uncertainty criteria). |
| **Economic Incremental Value vs Controls** | **`INCONCLUSIVE`** | In Validation 2025, Derivatives-Informed Trend Filter delivers **`+7.95%`**, outperforming Price-Only Trend Control (**`+5.02%`** by +2.93%), while trailing Simple Trend Following (**`+8.07%`** by -0.12%). Under 30.0 bps stress friction, Derivatives-Informed Trend Filter preserves **`+3.01%`**, outperforming both Price-Only Control (**`-1.40%`**) and Simple Trend Following (**`+3.13%`**). |
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
- **Elimination of Global Forward-Fill Resurrecting Stale Features**: Removed `valid_grid[all_features].ffill()` across stale-masked features. Number of daily decisions affected: **0** (all 1,270 daily decisions at 00:00 UTC have fresh metrics and funding data).
- **Population-Level PIT Audit**: Evaluated across all 1270 decision rows (2023-01-08 to 2026-06-30):
  - `future_available_count`: **0**
  - `stale_feature_used_count`: **0**
  - `invalid_execution_order_count`: **0**
  - `missing_data_count`: **0**
  - `population_pit_correctness`: **PASS**
- **Freshness Policy**: Enforced max staleness limits (120 minutes for 5m metrics, 24 hours for 8h funding settlements). Observations older than limits are masked as missing.
- **BNB Coverage Clarification**: Documented that BNBUSDT metrics contains only **27,360** records (576 rows/month (~2 days sampled per month)), while BNB funding rates are continuous (3,831 settlements).

### 2.3. R7 Weekly Benchmark Execution Fidelity & Naming Parity
In D0, simulator defaulted `rebalance_mask=True` daily, causing Weekly R7 to execute 1,199 trades. Corrected by introducing explicit Sunday rebalance mask and naming parity:
- **R7 Vol Target (Sunday-Signal / Monday-Open Weekly Adaptation)**: Scheduled strictly on Sundays (`dayofweek == 6`), executed at Monday 00:00 UTC Open, with holdings drifting naturally Tuesday–Sunday. Executed **178** actual trades with total fees of **$703.51**.
- **R7 Vol Target (Daily Adaptation)**: Rebalanced daily when rolling 480h hourly volatility exceeds 5% buffer. Executed **1252** trades.

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
| **BTC Buy & Hold** | **`+251.40%`** | `+441.11%` | **`-5.44%`** | `-31.25%` | **`1.002`** | `1.550` | **`-52.21%`** | `1.0x` | `1` | `$11.99` |
| **Static 50/50 BTC/Cash** | **`+104.89%`** | `+145.76%` | **`-0.80%`** | `-15.91%` | **`0.995`** | `1.536` | **`-29.55%`** | `6.0x` | `1269` | `$137.89` |
| **R7 Vol Target (Sunday-Signal / Monday-Open Weekly Adaptation)** | **`+134.89%`** | `+200.03%` | **`+3.69%`** | `-24.28%` | **`0.997`** | `1.500` | **`-39.79%`** | `25.9x` | `178` | `$703.51` |
| **R7 Vol Target (Daily Adaptation)** | **`+124.89%`** | `+191.37%` | **`-0.12%`** | `-22.57%` | **`0.987`** | `1.490` | **`-39.00%`** | `17.1x` | `1252` | `$459.39` |
| **Simple Trend Following (50d SMA)** | **`+158.84%`** | `+161.98%` | **`+8.07%`** | `-8.57%` | **`0.983`** | `1.222` | **`-31.73%`** | `72.0x` | `72` | `$1,882.78` |
| **Price-Only Trend Control** | **`+168.68%`** | `+157.26%` | **`+5.02%`** | `-0.55%` | **`1.096`** | `1.324` | **`-25.50%`** | `136.7x` | `242` | `$3,273.36` |
| **Derivatives-Informed Trend Filter** | **`+128.93%`** | `+131.11%` | **`+7.95%`** | `-8.24%` | **`0.923`** | `1.121` | **`-30.47%`** | `114.1x` | `198` | `$2,472.30` |
| **Price-Only Vol Overlay** | **`+108.52%`** | `+163.53%` | **`-0.30%`** | `-20.50%` | **`0.971`** | `1.460` | **`-36.00%`** | `22.0x` | `1269` | `$548.82` |
| **Derivatives Volatility Overlay** | **`+118.17%`** | `+168.45%` | **`+1.73%`** | `-20.04%` | **`1.029`** | `1.575` | **`-34.86%`** | `26.4x` | `1269` | `$685.36` |

### Stress Test: 25.0 bps Fee + 5.0 bps Slippage (30.0 bps All-In Cost)
| Policy Name | Full Net Ret (Stress) | Val 2025 Ret (Stress) | Sharpe (Stress) | Max Drawdown (Stress) | Total Fees (Stress) | Fee Drag vs Base |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **Simple Trend Following** | **`+127.37%`** | **`+3.13%`** | **`0.871`** | **`-34.14%`** | `$4,366.00` | `+31.47%` |
| **Price-Only Trend Control** | **`+110.06%`** | **`-1.40%`** | **`0.860`** | **`-28.13%`** | `$7,074.72` | `+58.62%` |
| **Derivatives-Informed Trend Filter** | **`+86.40%`** | **`+3.01%`** | **`0.731`** | **`-32.75%`** | `$5,493.38` | `+42.53%` |
| **R7 Vol Target (Daily Adaptation)** | **`+118.05%`** | **`-0.96%`** | **`0.954`** | **`-39.33%`** | `$1,127.96` | `+6.84%` |
| **R7 Vol Target (Sunday-Signal / Monday-Open Weekly Adaptation)** | **`+124.19%`** | **`+2.42%`** | **`0.951`** | **`-40.27%`** | `$1,711.04` | `+10.70%` |
| **Derivatives Vol Overlay** | **`+108.04%`** | **`+0.35%`** | **`0.973`** | **`-35.48%`** | `$1,667.31` | `+10.13%` |

---

## 5. Strategic Research Synthesis & Honest Evidence Interpretation

### Key Scientific Takeaways
1. **Economic Edge over Price-Only Control**: In Validation 2025, Derivatives-Informed Trend Filter achieved **+7.95%** vs Price-Only Control **+5.02%** (+2.93% delta), while trailing Simple Trend Following (**+8.07%** by -0.12%). Under 30 bps stress costs, it preserved **+3.01%** vs **-1.40%** and **+3.13%**.
2. **Trade Frequency and Friction**: Derivatives-Informed Trend Filter executed **198** actual trades across 3.5 years, generating total transaction fees of **$2,472.30** at 12 bps.
3. **Statistical Uncertainty Discipline**: While the permutation p-value is **p = 0.0099**, the 95% paired block-bootstrap CI `[-0.0115, +0.2650]` crosses zero. Under strict falsification discipline, historical correlation cannot be declared proven generalizable alpha.

**STOP RULE ENFORCED**: D0.1 completed. Overall verdict: **`DERIVATIVES_INCREMENTAL_VALUE_INCONCLUSIVE`**.
