# R6 Economic Integrity & H3 Predictive Value Falsification Report

**Clean Aligned Horizon**: 2022-01-16 00:00 UTC to 2026-11-16 19:00 UTC (42,379 hourly bars, ~4.84 years)  
**Execution & Accounting Standards**: Strict Causal Event Order | Order execution at `open[t_dec]` | Valuation at `close[t]` | 12.0 bps (stress: 25.0 bps)  

---

## 1. Executive Scientific Verdict

### Final Verdict: **`H3_INCREMENTAL_VALUE_NOT_SUPPORTED`**

> [!IMPORTANT]
> **Definitive Economic Falsification Finding**:
> Under strictly causal execution, **H3 (Breadth + Sentiment) delivered -2.38% net return with Sharpe 0.134**, compared to **+41.84% net return with Sharpe 0.423** for the Exposure-Matched Static Control (48.06% BTC / 51.94% Cash calibrated on Train+Val; In-Sample Reference).
> - **H3 failed to demonstrate incremental value over static exposure in the experiment**: its realized MaxDD (-39.51%) was virtually indistinguishable from the static exposure-matched benchmark (-38.97%), demonstrating that the risk reduction was driven by the average cash exposure (~54%) rather than timing skill.
> - In every single period—Train (2022-2023), Validation (2024), and Reused Holdout (2025-2026)—H3 underperformed the static exposure-matched benchmark by large margins (-13.5% in Train, -17.9% in Val, -8.8% in Holdout).
> - Incorporating Fear & Greed destroyed economic value: `Breadth-Only` produced **+12.36%**, whereas adding Sentiment in H3 dragged performance down to **-2.38%** due to buying into falling knives and severe transaction fee drag ($\$1,457.80$).

---

## 2. Phase 1 — Causal Execution Fidelity & Execution Trace

### Strict Event Sequence Definition:
1. **Decision Time**: Weekly boundary at Sunday 00:00:00 UTC (`decision_time`).
2. **Execution Time**: Target order executes at Sunday 00:00:00 UTC open price (`execution_time`).
3. **Source Bar Interval**: Closed bar $[t_{\text{dec}}-1, t_{\text{dec}})$, spanning from `source_bar_open_time` (Saturday 23:00 UTC) to `source_bar_close_time` (Sunday 00:00 UTC).
4. **Feature Availability**: Features become strictly available at `feature_available_at` (Sunday 00:00:00 UTC), coinciding with closed bar close.
5. **Mark-to-Market**: Hourly equity at `close[t]` evaluates using the exact holdings active during that hour.

### Point-in-Time Execution Trace (First 3 Decisions):

| Decision # | Decision Time (UTC) | Exec Time (UTC) | Source Bar Open | Source Bar Close | Feature Ready | Target BTC W | Target Cash W | Exec Price ($) | Traded ($) | Fee ($) | Post Cash ($) | Post BTC Units | Post Equity ($) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 0 | 2022-01-16 00:00:00+00:00 | 2022-01-16 00:00:00+00:00 | 2022-01-15 23:00:00+00:00 | 2022-01-16 00:00:00+00:00 | 2022-01-16 00:00:00+00:00 | 0.50 | 0.50 | $43,084.29 | $5,000.00 | $6.00 | $4,997.00 | 0.1160 | $9,992.31 |
| 1 | 2022-01-23 00:00:00+00:00 | 2022-01-23 00:00:00+00:00 | 2022-01-22 23:00:00+00:00 | 2022-01-23 00:00:00+00:00 | 2022-01-23 00:00:00+00:00 | 0.00 | 1.00 | $35,071.42 | $4,067.65 | $4.88 | $9,059.77 | 0.0000 | $9,059.77 |
| 2 | 2022-01-30 00:00:00+00:00 | 2022-01-30 00:00:00+00:00 | 2022-01-29 23:00:00+00:00 | 2022-01-30 00:00:00+00:00 | 2022-01-30 00:00:00+00:00 | 0.50 | 0.50 | $38,166.83 | $4,529.89 | $5.44 | $4,527.17 | 0.1186 | $9,012.77 |

---

## 3. Numerical Delta: Uncorrected R6 vs. Corrected Causal R6

| Metric | Uncorrected R6 (Same-hour mark-to-market leak) | Corrected Causal R6 (Strict next-open execution) | Numerical Delta | Causal Explanation |
| :--- | :--- | :--- | :--- | :--- |
| **H3 Net Return (%)** | -3.44% | -2.38% | +1.06%p | Removed order-reversal valuation mismatch at decision boundary |
| **H3 Max Drawdown (%)** | -38.04% | -39.51% | -1.47%p | Realized intra-week mark-to-market dip post rebalance execution |
| **H3 Annualized Sharpe** | 0.131 | 0.134 | +0.003 | Consistent hourly mark-to-market series |
| **H3 Total Fees ($)** | $1,481.58 | $1,457.80 | -$23.78 | Exact cash accounting at next-bar open prices |
| **H3 1-Way Turnover** | 116.8 | 117.9 | +1.1 | Complete 253 weekly rebalance cycles |
| **BTC Buy & Hold Ret (%)** | +50.57% | +50.57% | 0.00%p | Identical baseline benchmark |

---

## 4. Phase 4 — Comprehensive H3 Economic Falsification Scorecard

| Strategy / Benchmark | Fee Rate | Final Equity ($) | Net Ret (%) | Excess vs BTC | Excess vs Cash | Max DD (%) | Sharpe [95% CI] | Sortino | Mean Cash W | 1-Way TO | Fees ($) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **H3_BREADTH_PLUS_SENTIMENT_base_12bps** | 12 bps | $9,762.38 | **-2.38%** | -52.95% | -2.38% | -39.51% | 0.134 [-0.70, 1.10] | 0.188 | 0.54 | 117.9 | $1,457.80 |
| **H3_BREADTH_PLUS_SENTIMENT_stress_25bps** | 25 bps | $8,373.31 | **-16.27%** | -66.84% | -16.27% | -41.68% | 0.030 [-0.82, 1.01] | 0.041 | 0.54 | 117.9 | $2,803.63 |
| **EXPOSURE_MATCHED_BTC_CASH_CONTROL_base_12bps (Train+Val Calibrated Ref)** | 12 bps | $14,184.42 | **+41.84%** | -8.73% | +41.84% | -38.97% | 0.423 [-0.45, 1.24] | 0.597 | 0.52 | 3.5 | $49.36 |
| **EXPOSURE_MATCHED_BTC_CASH_CONTROL_stress_25bps (Train+Val Calibrated Ref)** | 25 bps | $14,119.51 | **+41.20%** | -9.37% | +41.20% | -39.02% | 0.419 [-0.45, 1.24] | 0.592 | 0.52 | 3.5 | $102.56 |
| **STATIC_BTC_CASH_50_50_base_12bps** | 12 bps | $14,301.52 | **+43.02%** | -7.55% | +43.02% | -40.27% | 0.423 [-0.45, 1.24] | 0.597 | 0.50 | 3.5 | $49.88 |
| **STATIC_BTC_CASH_50_50_stress_25bps** | 25 bps | $14,235.63 | **+42.36%** | -8.21% | +42.36% | -40.32% | 0.419 [-0.45, 1.24] | 0.592 | 0.50 | 3.5 | $103.65 |
| **BREADTH_ONLY_base_12bps** | 12 bps | $11,236.42 | **+12.36%** | -38.21% | +12.36% | -48.35% | 0.238 [-0.59, 1.13] | 0.334 | 0.52 | 128.0 | $1,461.14 |
| **BREADTH_ONLY_stress_25bps** | 25 bps | $9,511.03 | **-4.89%** | -55.46% | -4.89% | -49.55% | 0.134 [-0.69, 1.03] | 0.187 | 0.52 | 128.0 | $2,781.78 |
| **SENTIMENT_ONLY_base_12bps** | 12 bps | $8,691.88 | **-13.08%** | -63.65% | -13.08% | -46.22% | 0.035 [-0.83, 0.91] | 0.049 | 0.64 | 102.0 | $1,061.13 |
| **SENTIMENT_ONLY_stress_25bps** | 25 bps | $7,610.61 | **-23.89%** | -74.46% | -23.89% | -47.79% | -0.063 [-0.94, 0.81] | -0.088 | 0.64 | 102.0 | $2,065.72 |
| **BENCHMARK_BTC_BUY_AND_HOLD_base_12bps** | 12 bps | $15,056.78 | **+50.57%** | +0.00% | +50.57% | -67.38% | 0.420 [-0.45, 1.24] | 0.592 | 0.00 | 1.0 | $12.00 |
| **BENCHMARK_100PCT_CASH_base_12bps** | 12 bps | $10,000.00 | **+0.00%** | -50.57% | +0.00% | 0.00% | 0.000 [0.00, 0.00] | 0.000 | 1.00 | 0.0 | $0.00 |
| **BENCHMARK_EW_WEEKLY_REBAL_base_12bps** | 12 bps | $8,079.93 | **-19.20%** | -69.77% | -19.20% | -70.41% | 0.259 [-0.71, 1.11] | 0.356 | 0.00 | 5.9 | $122.27 |

### Multi-Seed Temporal Permutation Null Distribution (50 Seeds)

To avoid drawing conclusions from a single arbitrary random shuffle, we evaluated H3 against an empirical null distribution of 50 deterministic temporal permutations (seeds 101 to 150):

| Metric | H3 Actual | Null Mean (50 seeds) | Null Median | Null 5th–95th Percentile | H3 Percentile Rank in Null |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Net Return (base_12bps)** | -2.38% | +0.97% | -8.06% | [-58.49%, +96.62%] | **56.0%** |
| **Net Return (stress_25bps)** | -16.27% | -13.72% | -21.52% | [-64.50%, +69.17%] | **56.0%** |

### Chronological Sub-Period Stability Across Regimes

| Strategy / Benchmark | Train (2022-2023) | Validation (2024) | Reused Holdout (2025-2026) | Economic Robustness Verdict |
| :--- | :--- | :--- | :--- | :--- |
| **H3_BREADTH_PLUS_SENTIMENT_base_12bps** | -5.37% | +32.36% | -22.00% | Consistently Inferior to Exposure-Matched |
| **EXPOSURE_MATCHED_BTC_CASH_CONTROL_base_12bps** | +8.13% | +50.22% | -13.17% | Superior Risk-Adjusted |
| **STATIC_BTC_CASH_50_50_base_12bps** | +8.12% | +52.54% | -13.79% | Benchmark |
| **BREADTH_ONLY_base_12bps** | -19.90% | +50.33% | -6.54% | Benchmark |
| **SENTIMENT_ONLY_base_12bps** | -18.12% | +19.22% | -10.95% | Catastrophic Fees |
| **BENCHMARK_BTC_BUY_AND_HOLD_base_12bps** | -1.83% | +120.31% | -31.20% | Benchmark |
| **BENCHMARK_100PCT_CASH_base_12bps** | +0.00% | +0.00% | +0.00% | Benchmark |
| **BENCHMARK_EW_WEEKLY_REBAL_base_12bps** | -21.32% | +103.38% | -50.40% | Benchmark |

---

## 5. Direct Answers to the 5 Mandatory Research Questions

1. **Does H3 beat static / exposure-matched controls after fees?**
   - **NO. H3 severely underperforms.** The Exposure-Matched Control (holding 48.06% BTC / 51.94% Cash calibrated on Train+Val; In-Sample Reference) returned **+41.84%** with Sharpe **0.423** and fees of only $49.35. H3 returned **-2.38%** with Sharpe **0.134** and paid $1,457.80 in fees. H3 underperformed the static control by **-44.22%** net.
2. **Does Fear & Greed add incremental economic value over Breadth-only?**
   - **NO. Sentiment actively destroys value.** `Breadth-Only` delivered **+12.36%** net return. Adding Sentiment (H3) dropped net return by **-14.74%p** down to **-2.38%**, while `Sentiment-Only` produced **-13.08%**. Fear & Greed dip-buying triggered premature entries during ongoing bear drawdowns.
3. **Does Breadth add incremental value over simple BTC trend/volatility?**
   - Breadth alone reduces drawdown (-48.35% vs -67.38% for BTC), but binary switching between 100% BTC and Cash generates massive turnover ($128\times$) and fee erosion. Static exposure diversification achieves equal drawdown protection without switching drag.
4. **Did H3 reduce Max Drawdown via informed timing or simply via high cash holding?**
   - **H3 failed to demonstrate incremental value over static exposure in the experiment**: its realized MaxDD (-39.51%) was virtually indistinguishable from the static exposure-matched benchmark (-38.97%), demonstrating that the risk reduction was driven by the average cash exposure (~54%) rather than timing skill.
5. **Is H3 stable across Train/Val and does it hold up in Reused Holdout?**
   - H3 underperformed the exposure-matched static control in **every single sub-period**: Train (-5.37% vs +8.13%), Validation (+32.36% vs +50.22%), and Holdout (-22.00% vs -13.17%).

---

## 6. Phase 5 — Unified Neural Research Decision

### Architectural Follow-Up:
1. **Do NOT build a 12-feature neural network around H3 / Sentiment**: Converting an empirically falsified heuristic rule into a neural model will not create alpha; it would only overfit the fee drag and whipsaws.
2. **Core Empirical Truth of Crypto Trading Research**: 
   - Cross-sectional altcoin picking is dominated by idiosyncratic noise and turnover drag.
   - Binary all-or-nothing market timing rules create massive whipsaw costs ($>100\times$ turnover).
   - Continuous static or slow-moving portfolio diversification (e.g. 50/50 BTC/Cash) naturally delivers superior Sharpe ratios (0.423 vs 0.134) with minimal turnover (3.5x).
3. **Single Grounded Next Experiment**: 
   - Before testing any complex deep network, test a **Continuous Kelly / Volatility-Targeted Sizing Policy**: 
     Instead of binary switching (0% or 100% cash), dynamically adjust cash exposure as a continuous function of BTC 168h realized volatility ($w_{\text{btc}} = \min(1.0, \sigma_{\text{target}} / \sigma_{168h})$) with a turnover threshold buffer (only trade if weight delta $> 5\%$).
   - Determine if continuous volatility scaling beats static 50/50 exposure after fees.
