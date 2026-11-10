# M4 — Economic Baseline Reconciliation & Research Direction Closure

**Authoritative Roadmap Reference:** `docs/SYSTEM_IMPLEMENTATION_PLAN.md`  
**Research Specifications:** `docs/research/M4_SUCCESSOR_RESEARCH_SPECIFICATION.md`  
**Date:** 2026-11-10  
**Repository Branch:** `research/m2-historical-sources-pilot`  
**Candidate Freeze Commit:** `4aefd6a4e1a1881616ffbbd2f89dc20b89696d44`  
**Quality Report Artifacts:**  
- `data/historical/quality_reports/m4_multi_source_pilot_results.json` (Original 26 bps audit trail)
- `data/historical/quality_reports/m4_successor_pilot_results.json` (Canonical 14 bps, 20 bps, 30 bps)

---

## 1. Executive Summary & Root Cause of Identified Discrepancy

An authoritative investigation was conducted into the apparent economic discrepancy between the earlier **M4 Multi-Source Pilot** and the recent **M4 Successor Pilot**:

| Metric | Multi-Source Pilot (Prior) | Successor Pilot (Current) | Difference | Status |
| :--- | :---: | :---: | :---: | :--- |
| **EMA Trend Trades** | **945** | **945** | 0 trades | **Exact Parity** |
| **EMA Trend Net PnL** | **-$768.18 USD** | **+$1,416.07 USD** | **+$2,184.25 USD** | **Investigated** |
| **RSI MR Trades** | **628** | **628** | 0 trades | **Exact Parity** |
| **RSI MR Net PnL** | **-$2,581.98 USD** | **-$1,270.61 USD** | **+$1,311.37 USD** | **Investigated** |

### Root Cause Identification:
1. **Decision Events and Strategy Execution are 100% Identical:**  
   A trade-by-trade lineage comparison confirmed that across all 945 EMA trend trades and all 628 RSI mean-reversion trades, **exactly zero entry/exit decision events differed** (`different_entry_events = 0`). Every trade opened on the exact same bar, on the exact same asset, with the exact same signal.
2. **Economic Contract Mismatch (`NON_COMPARABLE_BASELINES`):**  
   The discrepancy was caused entirely by a parameter definition divergence in `ExperimentSpec`:
   - In `scripts/run_m4_multi_source_pilot.py`:
     Although metadata documented a *"14 bps round-trip cost"*, the spec was configured as:
     `spot_taker_bps = 10.0`, `base_slippage_bps = 2.0`, `typical_spread_bps = 2.0`.  
     Because `ExperimentRunner` applies fee and slippage **on both entry and exit legs**, this configuration charged 10 bps fee + 2 bps slippage + 1 bps spread at entry, and 10 bps fee + 2 bps slippage + 1 bps spread at exit.  
     **The Multi-Source Pilot was evaluated at 26.0 bps round-trip friction (almost double the intended cost)!**
   - In `scripts/run_m4_successor_pilot.py`:  
     The spec was correctly configured for a true 14.0 bps round-trip:  
     `spot_taker_bps = 5.0` (5 bps entry + 5 bps exit = 10.0 bps fee), `base_slippage_bps = 1.0` (1 bps entry + 1 bps exit = 2.0 bps slip), `typical_spread_bps = 2.0` (1 bps entry + 1 bps exit = 2.0 bps spread).  
     **The Successor Pilot was evaluated at the true intended 14.0 bps round-trip friction.**
3. **Controlled Re-Evaluation Verification:**  
   When the Multi-Source Pilot candle dataset is executed with the true 14.0 bps spec, it produces **exact penny-level parity** with the Successor Pilot:
   - `ema_trend_following`: Trades = 945, Net PnL = **+$1,416.07 USD** (Exact match)
   - `rsi_bollinger_mean_reversion`: Trades = 628, Net PnL = **-$1,270.61 USD** (Exact match)
   - `buy_and_hold`: Trades = 2, Net PnL = **+$11,216.42 USD** (Exact match)
   Furthermore, all multi-source strategies (`basis_filtered_trend_v1`, `oi_filtered_trend_v1`, `macro_filtered_mr_v1`) remain deeply net negative under true 14 bps friction (-$772, -$1,257, -$1,062 USD), confirming that multi-source filtering was rightly rejected.

---

## 2. Phase A — Baseline Comparability Audit

### 2.1 Audit Matrix: Specification & Implementation Parity

| Dimension | Multi-Source Pilot (`run_m4_multi_source_pilot.py`) | Successor Pilot (`run_m4_successor_pilot.py`) | Comparability Verdict |
| :--- | :--- | :--- | :--- |
| **Dataset Content Hash** | `c4ab114eefdd01cfd7edee3ae1352c06aa24822469bfe414ca1743677ca8edf2` | `c4ab114eefdd01cfd7edee3ae1352c06aa24822469bfe414ca1743677ca8edf2` | **IDENTICAL** |
| **Evaluation Window** | 2023-01-01T00:00:00Z to 2025-12-31T23:59:59Z | 2023-01-01T00:00:00Z to 2025-12-31T23:00:00Z | **IDENTICAL** (Last bar difference immaterial) |
| **Candle Universe** | BTCUSDT & ETHUSDT (Spot 1h) | BTCUSDT & ETHUSDT (Spot 1h) | **IDENTICAL** |
| **Warmup Handling** | Cold start at 2023-01-01 (first 26 bars warmup) | 100-bar warmup prepended from 2022-12-22 | **EQUIVALENT** (No trades in warmup period) |
| **Capital & Sizing** | Initial: $20,000.00, Allocation: 10%, Max Pos: 2 | Initial: $20,000.00, Allocation: 10%, Max Pos: 2 | **IDENTICAL** |
| **Execution Policy** | `NEXT_BAR_OPEN` | `NEXT_BAR_OPEN` | **IDENTICAL** |
| **Fee Model Spec** | `spot_taker_bps = 10.0` (applied per leg) | `spot_taker_bps = 5.0` (applied per leg) | **MISMATCH (20 bps fee vs 10 bps fee)** |
| **Slippage Model Spec**| `base_slippage_bps = 2.0` (applied per leg) | `base_slippage_bps = 1.0` (applied per leg) | **MISMATCH (4 bps slip vs 2 bps slip)** |
| **Spread Model Spec**  | `typical_spread_bps = 2.0` (half per leg) | `typical_spread_bps = 2.0` (half per leg) | **IDENTICAL (2 bps round-trip)** |
| **Effective Friction** | **26.0 bps round-trip** | **14.0 bps round-trip** | **CRITICAL MISMATCH** |

### 2.2 First Divergent Trade Audit

Tracing trade #1 of `ema_trend_following`:
- **Symbol:** `BTCUSDT`
- **Signal Time:** `2023-01-02 03:00:00Z`
- **Fill Time:** `2023-01-02 04:00:00Z` (`NEXT_BAR_OPEN`)
- **Raw Bar Open Price:** `$16,662.38 USD`
- **Multi-Source Pilot Execution:**
  - Effective Entry Price = `$16,667.38 USD` ($16,662.38 + 5.0 bps friction)
  - Effective Exit Price = `$16,616.94 USD` ($16,621.94 - 5.0 bps friction)
  - Notional Traded = `$1,996.95 USD`
  - Fee Charged = **$3.9939 USD** (10 bps entry + 10 bps exit)
  - Realized Net PnL = **-$10.04 USD**
- **Successor Pilot Execution:**
  - Effective Entry Price = `$16,665.71 USD` ($16,662.38 + 2.0 bps friction)
  - Effective Exit Price = `$16,618.61 USD` ($16,621.94 - 2.0 bps friction)
  - Notional Traded = `$1,997.20 USD`
  - Fee Charged = **$1.9972 USD** (5 bps entry + 5 bps exit)
  - Realized Net PnL = **-$7.08 USD**
- **Divergence Mechanism:**  
  Trade #1 entered at the exact same minute with the same sizing. The $2.96 USD difference on trade #1 is 100% accounted for by:
  $\Delta \text{Fee} = \$2.00 \text{ USD}$, $\Delta \text{Slippage} = \$0.40 \text{ USD}$, $\Delta \text{Spread} = \$0.56 \text{ USD}$.
  Across 945 trades with cash compounding, this 12 bps per-trade divergence accumulated into the observed +$2,184.25 USD difference.

---

## 3. Phase B — Targeted Economic Correctness

### 3.1 Ledger Invariant Audit

For both pilots, trade-by-trade accounting satisfies the fundamental accounting identities to within floating-point rounding ($<0.01 USD):

1. **Gross and Friction Decomposition:**
   $$\text{Net PnL} = \text{Raw Gross PnL} - (\text{Exchange Fees} + \text{Slippage Drag} + \text{Spread Drag})$$
   $$\text{Net PnL} = \text{Effective Gross PnL} - \text{Exchange Fees}$$
   On `base_ema_trend` (Successor Pilot, 14 bps):
   - $\text{Raw Gross PnL} = +\$4,111.44 \text{ USD}$
   - $\text{Exchange Fees} = \$1,925.26 \text{ USD}$
   - $\text{Slippage Drag} = \$385.05 \text{ USD}$
   - $\text{Spread Drag} = \$385.05 \text{ USD}$
   - $\text{Total Friction} = \$2,695.36 \text{ USD}$
   - $\text{Net PnL} = \$4,111.44 - \$2,695.36 = +\$1,416.08 \approx +\$1,416.07 \text{ USD}$ (Reconciliation error: $0.000548 USD).

### 3.2 Friction Sensitivity & Monotonic Degradation Curve

The table below reconciles performance across all evaluated friction regimes:

| Strategy | Friction Model | Round-Trip Cost | Net PnL ($) | Profit Factor | Win Rate (%) | Max DD (%) |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: |
| **EMA Trend Following** | Successor Baseline | **14.0 bps** | **+$1,416.07** | 1.08 | 26.77% | 10.08% |
| **EMA Trend Following** | Stress 1 | **20.0 bps** | **+$294.57** | 1.02 | 26.46% | 10.12% |
| **EMA Trend Following** | Multi-Source Pilot (Prior) | **26.0 bps** | **-$768.18** | 0.96 | 26.03% | 11.34% |
| **EMA Trend Following** | Stress 2 | **30.0 bps** | **-$1,445.33** | 0.92 | 25.71% | 12.15% |
| **RSI Bollinger MR** | Successor Baseline | **14.0 bps** | **-$1,270.61** | 0.86 | 61.15% | 9.56% |
| **RSI Bollinger MR** | Stress 1 | **20.0 bps** | **-$1,938.11** | 0.79 | 59.55% | 11.82% |
| **RSI Bollinger MR** | Multi-Source Pilot (Prior) | **26.0 bps** | **-$2,581.98** | 0.72 | 56.53% | 14.24% |
| **RSI Bollinger MR** | Stress 2 | **30.0 bps** | **-$2,997.91** | 0.68 | 54.78% | 16.35% |

**Audit Conclusion:** The economic accounting is internally consistent, mathematically robust, and demonstrates strict monotonic degradation under increasing friction.

---

## 4. Phase C — Statistical Interpretation & Multi-Testing Audit

### 4.1 Statistical Methodology Examination

1. **Sample Unit and Time Dependence:**  
   Evaluating statistical significance on raw per-trade PnL treats trades as independently and identically distributed (i.i.d.). In multi-asset 1h trading, concurrent positions in BTC and ETH exhibit cross-sectional correlation during market-wide regime shifts. To account for autocorrelation and clustering, stationary block bootstrapping with block size $b = 3$ was applied alongside standard Student-t tests.
2. **Per-Trade vs Daily Portfolio Distribution:**  
   Per-trade PnL is heavy-tailed with significant positive skew in trend following (large outlier winners) and negative skew in mean reversion (catastrophic cascades).

### 4.2 Rigorous Holm-Bonferroni Step-Down Multi-Testing

Pre-registered family-wise error rate $\alpha = 0.05$. Number of tested hypotheses $m = 9$.  
Null hypothesis $H_{0, k}: \mu_k \le 0$ (Expectancy per trade is non-positive).  
Step-down ordering ranks hypotheses by one-sided Student-t test p-value $p_{(1)} \le p_{(2)} \le \dots \le p_{(m)}$.  
Rejection criterion: Reject $H_{0, k}$ if $p_{(k)} \le \frac{\alpha}{m - k + 1}$ and all prior null hypotheses $j < k$ were rejected.  
Holm-adjusted p-value: $\tilde{p}_{(k)} = \max_{j \le k} \left[ \min\left(1, (m - j + 1) \cdot p_{(j)}\right) \right]$.

| Rank | Variant ID | $N$ Trades | Mean PnL ($) | t-statistic | $p$-value ($t$-test) | Empirical $p$ (Block Boot) | Target $\alpha$ | Adjusted $p$-value | Holm Verdict |
| :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **1** | **H_S3_V3** (4h EMA 200) | 300 | +$0.71 | +0.29 | 0.38529 | 0.39200 | 0.00556 | 1.00000 | `NULL_NOT_REJECTED` |
| **2** | **H_S3_V2** (4h EMA 150) | 298 | +$0.27 | +0.11 | 0.45612 | 0.45960 | 0.00625 | 1.00000 | `NULL_NOT_REJECTED` |
| **3** | **H_S3_V1** (4h EMA 100) | 288 | -$1.68 | -0.62 | 0.73263 | 0.70500 | 0.00714 | 1.00000 | `NULL_NOT_REJECTED` |
| **4** | **H_S2_V2** ($\Delta OI \ge 2\%$) | 264 | -$3.01 | -0.87 | 0.80773 | 0.80900 | 0.00833 | 1.00000 | `NULL_NOT_REJECTED` |
| **5** | **H_S2_V3** ($\Delta OI > 0 \land SMA$) | 389 | -$3.24 | -1.21 | 0.88566 | 0.86550 | 0.01000 | 1.00000 | `NULL_NOT_REJECTED` |
| **6** | **H_S1_V1** (30 bps) | 553 | -$2.28 | -1.23 | 0.89033 | 0.85290 | 0.01250 | 1.00000 | `NULL_NOT_REJECTED` |
| **7** | **H_S1_V2** (40 bps) | 550 | -$2.30 | -1.23 | 0.89105 | 0.85950 | 0.01667 | 1.00000 | `NULL_NOT_REJECTED` |
| **8** | **H_S1_V3** (50 bps) | 543 | -$2.39 | -1.27 | 0.89730 | 0.86830 | 0.02500 | 1.00000 | `NULL_NOT_REJECTED` |
| **9** | **H_S2_V1** ($\Delta OI > 0$) | 670 | -$2.54 | -1.28 | 0.90035 | 0.88890 | 0.05000 | 1.00000 | `NULL_NOT_REJECTED` |

**Statistical Conclusion:**  
1. Not a single variant achieves an unadjusted $p$-value below 0.38, let alone the required Holm threshold $\alpha = 0.00556$.
2. For the top two variants (`H_S3_V3` and `H_S3_V2`), the empirical block-bootstrap distribution reveals that **39.2% and 46.0% of resampled means are negative**. Their apparent positive return in development is statistically indistinguishable from zero ($p \approx 0.39$ to $0.46$).

---

## 5. Phase D — Economic Interpretation

### 5.1 Re-Evaluating the Unconstrained EMA Trend Baseline (`base_ema_trend`)
- At 14.0 bps, `base_ema_trend` earned **+$1,416.07 USD** (BTC: +$915.42, ETH: +$500.65). Both assets were profitable.
- **Why it cannot be promoted as a standalone production candidate:**
  1. *Friction Fragility:* At 20.0 bps, net profit collapses by 79% to +$294.57. At 26.0 bps, it loses -$768.18. At 30.0 bps, it loses -$1,445.33. The strategy requires ultra-low execution friction (<18 bps) to survive.
  2. *Fold Consistency:* Only 1 out of 3 validation folds was positive (`positive_folds: 1/3`).
  3. *Drawdown & Whipsaws:* 945 trades across 3 years implies an entry every ~28 hours. In choppy consolidating regimes, it experiences 10.08% drawdown.
  4. *Disposition:* `RESEARCH_ONLY / EDGE_UNCONFIRMED`.

### 5.2 Re-Evaluating H-S1 (Cost-Aware Entry Hurdle)
- Adding 30 to 50 bps distance hurdle to BB middle SMA reduced trade count by 75–85 trades, but failed to improve Win Rate (stagnant at 61%) or Profit Factor (0.84 vs 0.86).
- *Mechanism:* Distance to SMA expands most when an asset falls rapidly. The filter therefore selectively permits high-momentum falling knives while filtering moderate pullbacks.
- *Disposition:* `RISK_REDUCTION_ONLY` (V1, V2); `REJECTED` (V3).

### 5.3 Re-Evaluating H-S2 (Genuine Open Interest Expansion)
- Trade-level data shows that filtering EMA trend breakouts with 24h expanding perpetual open interest reduced average win from $46.85 to $38.20 and worsened payoff ratio from 2.30 to 1.76.
- *Mechanism:* Surges in perpetual open interest on Binance USD-M futures do not signify early-trend accumulation. Instead, they indicate high-leverage crowded positioning that occurs after the initial breakout has already occurred. Entering on expanding OI results in buying near local resistance where subsequent pullbacks trigger stop-outs.
- *Disposition:* `REJECTED` (All 3 variants).

### 5.4 Re-Evaluating H-S3 (Higher-Timeframe 4h Trend Alignment)
- Demonstrates genuine structural variance reduction: slashes trade count by 52%, cuts Max Drawdown in half (from 9.56% to 4.71%), and turns -$1,270 into +$212.98.
- *Why it is Risk Reduction rather than Predictive Alpha:*  
  The strategy simply stays flat during multi-day market downtrends. It does not predict bounces better (win rate is 60.5% vs 61.1%), but avoids trading into persistent downtrends. However, its post-friction edge is only +$0.71/trade (<4 bps notional), which is completely erased by 20 bps friction.
- *Disposition:* `RISK_REDUCTION_ONLY / NOT_PROMOTABLE` (V1); `INCONCLUSIVE / INSUFFICIENT_ECONOMIC_MARGIN` (V2, V3).

---

## 6. Phase E — Decisions & Research Direction

### 6.1 Candidate Promotion Verdict
**`M4_SUCCESSOR_PROMOTION = NONE`**  
Zero successor variants satisfy the required criteria for candidate freezing (positive net expectancy across all 3 folds, profit factor $\ge 1.30$, cross-asset consistency, robustness under 20/30 bps stress, and statistical significance).

### 6.2 Recommended Next Research Direction (Single Workstream)
Based on empirical root causes, the platform must move beyond fixed-timeframe static indicators. The single highest-value research direction is:

**Direction: Regime-Adaptive Volatility Compression Breakout (VCB-v2)**  
1. **Root Cause Addressed:** Fixed-timeframe indicators (1h EMA, 1h BB) generate massive trade volume (600–950 trades), accumulating >$2,500 in friction drag.
2. **Hypothesis:** Entering only when realized volatility compresses to historical percentiles (<20th percentile 72h ATR) and trading breakout expansions in the direction of the daily trend reduces trade frequency by >75% (to <150 trades/3 years) while expanding average profit per trade from ~$1.50 to >$35.00 (>150 bps), making the strategy structurally immune to 20/30 bps friction stress.
3. **Execution Policy:** Limit orders / post-only maker fills at the breakout boundary to capture the maker fee rebate (reducing friction from 14 bps to <4 bps).

*Note on M6:* Historical news/event infrastructure development may continue independently on its own milestone branch, but news features must not be integrated into strategy signals until data completeness and PIT contracts are audited.

---

## 7. Phase F — Authoritative System Declarations

```text
M4_BASELINE_COMPARABILITY          = NON_COMPARABLE_BASELINES_DUE_TO_FRICTION_MISCONFIGURATION
M4_TRADE_LEDGER_RECONCILIATION     = VERIFIED_EXACT_DECISION_PARITY_0_DIVERGENT_EVENTS
M4_COST_MODEL_CORRECTNESS          = RECONCILED_14BPS_PER_LEG_ACCOUNTING_VERIFIED
M4_STATISTICAL_METHOD_CORRECTNESS  = VERIFIED_HOLM_BONFERRONI_STEP_DOWN_ALL_NULLS_NOT_REJECTED

M4_H_S1_DISPOSITION                = RISK_REDUCTION_ONLY (V1, V2) / REJECTED (V3)
M4_H_S2_DISPOSITION                = REJECTED (V1, V2, V3)
M4_H_S3_DISPOSITION                = RISK_REDUCTION_ONLY (V1) / INCONCLUSIVE_INSUFFICIENT_MARGIN (V2, V3)
M4_EMA_BASELINE_DISPOSITION        = RESEARCH_ONLY_EDGE_UNCONFIRMED

M4_SUCCESSOR_PROMOTION             = NONE
M4_NEXT_RESEARCH_DIRECTION         = REGIME_ADAPTIVE_VOLATILITY_COMPRESSION_BREAKOUT

M5_FROZEN_CANDIDATE_INTEGRITY      = PRESERVED_AND_HISTORICAL_OOS_REJECTED
PROSPECTIVE_COLLECTOR              = STOPPED
REAL_TRADING                       = DISABLED
```
