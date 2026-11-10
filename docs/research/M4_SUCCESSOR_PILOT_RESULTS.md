# M4 Successor Research — 9-Variant Controlled Pilot Results & Attribution

**Authoritative Roadmap Reference:** `docs/SYSTEM_IMPLEMENTATION_PLAN.md`  
**Specification Reference:** `docs/research/M4_SUCCESSOR_RESEARCH_SPECIFICATION.md`  
**Date:** 2026-11-10  
**Repository Branch:** `research/m2-historical-sources-pilot`  
**Base Commit / Freeze Tag:** `4aefd6a4e1a1881616ffbbd2f89dc20b89696d44`  
**Evaluation Engine:** `btc_scraper.research.baseline_runner.ExperimentRunner`  
**Quality Report Artifact:** `data/historical/quality_reports/m4_successor_pilot_results.json`

---

## 1. Executive Summary & Research Context

Following the definitive historical OOS evaluation and rejection of the initial frozen candidate `vol_aware_mean_reversion_v1` (`HISTORICAL_OOS_REJECTED_FOR_PROMOTION`, Net PnL -$15.69 USD, Profit Factor 0.80, Multi-Asset Gate FAIL), this controlled development pilot evaluated **9 pre-registered successor variants** across 3 distinct hypothesis families on 36 months of development data (`2023-01-01` to `2025-12-31`).

### Primary Objectives:
1. Determine whether cost-aware hurdle filtering (**H-S1**), genuine USD-M Futures open interest confirmation (**H-S2**), or higher-timeframe 4h closed-candle trend alignment (**H-S3**) generate statistically robust incremental economic value after transaction friction.
2. Maintain strict non-contamination guarantees: **H1/2026** and **H2/2026** holdout windows remain strictly unaccessed and preserved.
3. Apply realistic and stressed transaction cost models (14 bps baseline round-trip, plus 20 bps and 30 bps stress).

### Key Empirical Findings:
1. **H-S1 (Cost-Aware Entry Hurdle - 30, 40, 50 bps to BB SMA)**:  
   Filters out 12–14% of trades and reduces drawdown marginally (from 9.56% to 9.18%), but **fails to resolve the underlying negative expectancy** of 1h mean reversion (-$1,259 to -$1,295 Net PnL). Filtering by expected distance to the mean does not solve adverse selection (catching falling knives). **Disposition: RISK_REDUCTION_ONLY / NOT_PROMOTABLE (V1, V2); REJECTED (V3)**.
2. **H-S2 (Genuine Open Interest Expansion)**:  
   **Catastrophic value destruction**. While the unconstrained EMA trend baseline achieved +$1,416.07 Net PnL, conditioning entries on expanding USD-M Futures Open Interest ($\Delta OI_{24h} > 0$, $\ge +2\%$) flipped net performance deeply negative (-$793 to -$1,705 Net PnL, PF 0.80–0.83). Large perpetual OI surges in crypto correspond to late-stage retail FOMO and crowded leverage tops immediately preceding liquidation cascades. **Disposition: ALL 3 VARIANTS DECISIVELY REJECTED**.
3. **H-S3 (Higher-Timeframe 4h Closed-Candle Trend Alignment)**:  
   **Demonstrated significant structural risk reduction and positive alpha generation over baseline**:
   - Slashed trade count by 52% (from 628 to ~298 trades), saving >$1,100 in friction.
   - Slashed maximum drawdown by more than half: from **9.56% down to 4.71%** (`H_S3_V2`).
   - Turned deeply negative 1h MR (-$1,270.61) into nominally positive performance (+$80.16 for V2, +$212.98 for V3) at 14 bps.
   - Generated consistent positive PnL on BTC (+$354 for V2, +$416 for V3).
   - **However, H-S3 is NOT promotable to candidate freeze**:
     - *Stress Sensitivity*: Turns negative under 20 bps stress (-$266 and -$138) and 30 bps stress (-$831 and -$710). Expectancy is only +$0.27 to +$0.71 per trade (<4 bps of notional), leaving no safety buffer for real-world slippage.
     - *Walk-Forward Consistency*: Only 1 of 3 validation folds was positive (`positive_folds: 1/3`).
     - *Statistical Multi-Testing*: 95% stationary block bootstrap CI spans zero (V3: `[-$5.03, +$5.83] USD`), failing Holm-Bonferroni significance (`NULL_NOT_REJECTED`).
     - *Multi-Asset Imbalance*: ETH remains negative (-$202.95 on V3), failing the cross-asset consistency requirement.
   - **Disposition: INCONCLUSIVE / INSUFFICIENT_ECONOMIC_MARGIN_FOR_PROMOTION**.

---

## 2. Experimental Setup & Governance Controls

| Parameter | Specification | Enforcement Mechanism |
| :--- | :--- | :--- |
| **Development Horizon** | 2023-01-01 00:00:00Z to 2025-12-31 23:00:00Z (36 months) | Bounded Parquet loaders + 100-bar warmup prepending |
| **Walk-Forward Splits** | 3 Chronological Folds with 24-hour Purge Gap | Strict date interval slicing |
| **Symbol Universe** | BTCUSDT and ETHUSDT (Spot 1h) | Multi-asset concurrent backtest engine |
| **Execution Timing** | `NEXT_BAR_OPEN` | Signals emitted at bar close $T$, filled at bar $T+1$ open |
| **Cost Model (Baseline)** | 14.0 bps round-trip | Spot: 5 bps maker + 5 bps taker fee + 2 bps spread + 2 bps slippage |
| **Cost Stress Models** | 20.0 bps and 30.0 bps round-trip | Monotonic friction stress audit |
| **Funding Deduction** | Excluded (Spot Long-Only) | Contract invariant: Spot positions do not pay derivatives funding |
| **Burned Window H1/2026** | 2026-01-01 to 2026-06-30 | `BURNED_FOR_PROMOTION` (Unused) |
| **Burned Window H2/2026** | 2026-07-01 to 2026-11-09 | `BURNED_FOR_SUCCESSOR_SELECTION` (Pristine, Unaccessed) |
| **Search Budget** | Exactly 9 Pre-Registered Variants across 3 Families | Hard freeze; zero exploratory retuning |

---

## 3. Comprehensive Performance Scorecard (13 Configurations)

All configurations evaluated on initial capital of **$20,000.00 USD** with 10% notional allocation per trade (max 2 concurrent positions).

| ID | Family | Trades | Raw Gross ($) | Friction ($) | Net PnL (14 bps) | Net PnL (20 bps) | Net PnL (30 bps) | PF | Max DD (%) | Net Exp ($) | 95% Bootstrap CI ($) | Folds+ | Disposition |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **always_flat** | ANCHOR | 0 | $0.00 | $0.00 | **$0.00** | $0.00 | $0.00 | 0.00 | 0.00% | $0.00 | N/A | 0/3 | `ANCHOR_ZERO_DRIFT` |
| **buy_and_hold** | ANCHOR | 2 | +$11,244.20 | $27.78 | **+$11,216.42** | +$11,209.59 | +$11,197.85 | N/A | 22.45% | +$5,608.21 | N/A | 1/3 | `PASSIVE_BENCHMARK` |
| **base_rsi_bb_mr** | BASELINE_MR | 628 | +$1,173.34 | $2,443.95 | **-$1,270.61** | -$1,938.11 | -$2,997.91 | 0.86 | 9.56% | -$2.02 | [-5.54, +1.86] | 1/3 | `BASELINE_MR` |
| **base_ema_trend** | BASELINE_TR | 945 | +$4,111.44 | $2,695.36 | **+$1,416.07** | +$294.57 | -$1,445.33 | 1.08 | 10.08% | +$1.50 | [-1.43, +4.53] | 1/3 | `BASELINE_TREND` |
| **H_S1_V1** | H_S1 | 553 | +$895.53 | $2,154.96 | **-$1,259.43** | -$1,850.54 | -$2,794.36 | 0.84 | 9.18% | -$2.28 | [-6.60, +1.83] | 1/3 | `RISK_REDUCTION_ONLY` |
| **H_S1_V2** | H_S1 | 550 | +$881.08 | $2,143.72 | **-$1,262.64** | -$1,850.38 | -$2,789.04 | 0.84 | 9.18% | -$2.30 | [-6.49, +1.81] | 1/3 | `RISK_REDUCTION_ONLY` |
| **H_S1_V3** | H_S1 | 543 | +$822.40 | $2,117.70 | **-$1,295.30** | -$1,874.83 | -$2,800.86 | 0.84 | 9.20% | -$2.39 | [-6.78, +1.57] | 1/3 | `REJECTED` |
| **H_S2_V1** | H_S2 | 670 | +$205.15 | $1,910.24 | **-$1,705.09** | -$2,404.92 | -$3,512.04 | 0.83 | 14.21% | -$2.54 | [-6.55, +1.76] | 1/3 | `REJECTED` |
| **H_S2_V2** | H_S2 | 264 | -$40.06 | $753.64 | **-$793.70** | -$1,091.70 | -$1,578.01 | 0.82 | 7.26% | -$3.01 | [-9.79, +4.15] | 1/3 | `REJECTED` |
| **H_S2_V3** | H_S2 | 389 | -$150.84 | $1,109.56 | **-$1,260.40** | -$1,684.67 | -$2,370.36 | 0.80 | 10.33% | -$3.24 | [-8.66, +2.72] | 1/3 | `REJECTED` |
| **H_S3_V1** | H_S3 | 288 | +$636.56 | $1,119.44 | **-$482.88** | -$809.33 | -$1,341.19 | 0.88 | 6.03% | -$1.68 | [-7.88, +4.00] | 1/3 | `RISK_REDUCTION_ONLY` |
| **H_S3_V2** | H_S3 | 298 | +$1,238.16 | $1,158.00 | **+$80.16** | -$266.83 | -$831.75 | 1.02 | **4.71%** | +$0.27 | [-5.10, +5.59] | 1/3 | `INCONCLUSIVE` |
| **H_S3_V3** | H_S3 | 300 | +$1,378.85 | $1,165.87 | **+$212.98** | -$138.25 | -$710.01 | 1.06 | 4.75% | +$0.71 | [-5.03, +5.83] | 1/3 | `INCONCLUSIVE` |

---

## 4. Incremental Economic Value vs Respective Baselines

Variants in **H-S1** and **H-S3** are compared directly against `base_rsi_bb_mr`.  
Variants in **H-S2** are compared directly against `base_ema_trend`.

| Variant ID | Family | Ref Baseline | $\Delta$ Trades | Friction Saved ($) | $\Delta$ Net PnL ($) | $\Delta$ PF | $\Delta$ Max DD (%) | $\Delta$ Expectancy ($) | Economic Assessment |
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **H_S1_V1** (30 bps) | H_S1 | `base_rsi_bb_mr` | -75 | +$288.99 | **+$11.18** | -0.02 | -0.38% | -$0.26 | Friction saved offset by worse trade selection. |
| **H_S1_V2** (40 bps) | H_S1 | `base_rsi_bb_mr` | -78 | +$300.23 | **+$7.97** | -0.02 | -0.38% | -$0.28 | Friction saved offset by worse trade selection. |
| **H_S1_V3** (50 bps) | H_S1 | `base_rsi_bb_mr` | -85 | +$326.25 | **-$24.69** | -0.02 | -0.36% | -$0.37 | Over-filtering good bounce trades; net degradation. |
| **H_S2_V1** ($\Delta OI > 0$) | H_S2 | `base_ema_trend` | -275 | +$785.12 | **-$3,121.16** | -0.25 | +4.13% | -$4.04 | Severe degradation; buying crowded leverage tops. |
| **H_S2_V2** ($\Delta OI \ge 2\%$) | H_S2 | `base_ema_trend` | -681 | +$1,941.72 | **-$2,209.77** | -0.26 | -2.82% | -$4.51 | Heavy filtering saves fee but destroys trend alpha. |
| **H_S2_V3** ($\Delta OI > 0 \land SMA$) | H_S2 | `base_ema_trend` | -556 | +$1,585.80 | **-$2,676.47** | -0.28 | +0.25% | -$4.74 | Consistent negative alpha across both filters. |
| **H_S3_V1** (4h EMA 100) | H_S3 | `base_rsi_bb_mr` | -340 | +$1,324.51 | **+$787.73** | +0.02 | -3.53% | +$0.34 | Massive friction elimination; drawdown cut by 37%. |
| **H_S3_V2** (4h EMA 150) | H_S3 | `base_rsi_bb_mr` | -330 | +$1,285.95 | **+$1,350.77** | +0.16 | **-4.85%** | +$2.29 | Flips net PnL positive; cuts drawdown in half. |
| **H_S3_V3** (4h EMA 200) | H_S3 | `base_rsi_bb_mr` | -328 | +$1,278.08 | **+$1,483.59** | +0.20 | -4.81% | +$2.73 | Flips net PnL to +$212.98; cuts drawdown in half. |

---

## 5. Multi-Asset Performance Breakdown (BTC vs ETH)

| Variant ID | Family | BTC Trades | BTC Net PnL ($) | ETH Trades | ETH Net PnL ($) | Cross-Asset Gate Verdict |
| :--- | :--- | :---: | :---: | :---: | :---: | :--- |
| `base_rsi_bb_mr` | BASELINE_MR | 311 | -$70.42 | 317 | -$1,200.19 | FAIL (Both negative, ETH catastrophic) |
| `base_ema_trend` | BASELINE_TR | 457 | +$915.42 | 488 | +$500.65 | **PASS** (Both assets positive) |
| `H_S1_V1` | H_S1 | 262 | -$80.27 | 291 | -$1,179.15 | FAIL (Both negative) |
| `H_S1_V2` | H_S1 | 261 | -$67.53 | 289 | -$1,195.12 | FAIL (Both negative) |
| `H_S1_V3` | H_S1 | 255 | -$99.51 | 288 | -$1,195.79 | FAIL (Both negative) |
| `H_S2_V1` | H_S2 | 334 | -$653.02 | 336 | -$1,052.07 | FAIL (Both negative) |
| `H_S2_V2` | H_S2 | 121 | +$166.09 | 143 | -$959.78 | FAIL (ETH deeply negative) |
| `H_S2_V3` | H_S2 | 197 | -$605.79 | 192 | -$654.61 | FAIL (Both negative) |
| `H_S3_V1` | H_S3 | 144 | +$207.23 | 144 | -$690.10 | FAIL (ETH deeply negative) |
| `H_S3_V2` | H_S3 | 152 | +$354.35 | 146 | -$274.19 | FAIL (ETH negative) |
| `H_S3_V3` | H_S3 | 148 | +$415.93 | 152 | -$202.95 | FAIL (ETH negative) |

---

## 6. In-Depth Failure Attribution & Ablation Analysis

### 6.1 Family 1: H-S1 (Cost-Aware Entry Hurdle)
- **Mechanism Tested:** Enforces a minimum expected distance from price to the middle Bollinger Band (`sma_20`) before taking an oversold dip entry (30, 40, 50 bps).
- **Ablation Finding:** As the hurdle increases from 0 bps (baseline) to 50 bps:
  - Trade count steadily declines: 628 $\rightarrow$ 553 $\rightarrow$ 550 $\rightarrow$ 543.
  - Transaction friction decreases by ~$300 USD.
  - Net PnL marginally improves at 30 bps (+$11.18) and 40 bps (+$7.97), but deteriorates at 50 bps (-$24.69).
  - Profit factor is stagnant at 0.84 (worse than baseline 0.86).
- **Root Cause of Economic Failure:**  
  A hurdle based on the instantaneous distance between current price and `sma_20` is a static geometric property of the Bollinger Band, not an indicator of mean-reverting momentum. When an asset experiences severe negative momentum (a cascade or liquidation wick), the distance to `sma_20` expands dramatically (often >100 bps). Consequently, the hurdle filter actively admits the worst falling knives while filtering out modest, well-behaved pullback dips. The filter thus fails to improve win rate or payoff ratio.

### 6.2 Family 2: H-S2 (Genuine Open Interest Expansion)
- **Mechanism Tested:** Filters EMA(12, 26) bullish trend breakout entries by requiring genuine expansion in USD-M Perpetual Futures Open Interest ($\Delta OI_{24h} > 0$, $\Delta OI_{24h} \ge +2\%$, or $OI > \text{SMA}_{5d}(OI)$).
- **Ablation Finding:**
  - Raw EMA Trend (`base_ema_trend`): Net 14bps = **+$1,416.07**, PF = 1.08, Win Rate = 33.7%, Avg Win = $46.85, Avg Loss = -$20.35 (Payoff 2.30).
  - Conditioned on OI (`H_S2_V1`): Net 14bps = **-$1,705.09**, PF = 0.83, Payoff drops to 1.76.
  - Conditioned on OI $\ge +2\%$ (`H_S2_V2`): Net 14bps = **-$793.70**, PF = 0.82.
- **Root Cause of Economic Failure:**  
  In crypto market structure, large open interest surges on perpetual futures do not represent clean trend confirmation. Instead:
  1. **Leverage Crowding & Exhaustion:** Rapid OI expansion during a price rise signifies leveraged long positioning entering near local resistance. These positions create fragile order books susceptible to long squeezes.
  2. **Latency of OI Aggregation:** By the time 24-hour Open Interest exhibits a +2% expansion, the initial momentum impulse is largely complete. Entering on this signal systematically buys the top of local distribution ranges.
  3. **Whipsaw Liquidation:** When price subsequently pulls back, liquidations cascades trigger stop losses, producing larger average losses ($40% higher loss rate) compared to the unconstrained trend follower.

### 6.3 Family 3: H-S3 (Higher-Timeframe 4h Closed-Candle Trend Alignment)
- **Mechanism Tested:** Enforces that 1h mean-reversion dip buys are executed ONLY when the higher-timeframe 4h trend is bullish (1h close occurs above closed 4h EMA 100, 150, or 200).
- **Ablation Finding:**
  - `H_S3_V1` (4h EMA 100): Net PnL -$482.88 (+$787 vs baseline), Drawdown cut from 9.56% to 6.03%.
  - `H_S3_V2` (4h EMA 150): Net PnL **+$80.16** (+$1,350 vs baseline), Drawdown cut to **4.71%**, PF 1.02.
  - `H_S3_V3` (4h EMA 200): Net PnL **+$212.98** (+$1,483 vs baseline), Drawdown cut to 4.75%, PF 1.06.
- **Value Analysis:**
  - The HTF closed-candle trend filter is structurally effective: it eliminates counter-trend dip buying during multi-day market sell-offs, removing 328 low-probability trades and saving >$1,270 in fees and slippage.
  - On BTC, it generated consistent net profits across all variants (+ $207 to +$416).
- **Why H-S3 Fails Promotion Gates:**
  1. **Fragility to Friction (Negative Expectancy under Stress):**  
     At 20 bps round-trip friction, `H_S3_V2` turns negative (-$266.83) and `H_S3_V3` turns negative (-$138.25). At 30 bps, losses deepen to -$831 and -$710. The edge is entirely consumed by a minor 6 bps increase in transaction friction.
  2. **Sub-Threshold Expectancy:**  
     Net expectancy per trade is only **+$0.27** (V2) and **+$0.71** (V3) on $2,000 notional (1.3 to 3.5 bps). In live spot trading, bid-ask spread expansion during volatility easily exceeds 4 bps, which would render the strategy unprofitable in production.
  3. **Walk-Forward Consistency & Bootstrap Bounds:**  
     Only 1 of 3 validation folds was profitable. The 95% block bootstrap confidence interval spans negative values (`[-$5.03, +$5.83] USD`), and the Holm-Bonferroni test confirms `NULL_NOT_REJECTED`.
  4. **Multi-Asset Asymmetry:**  
     ETH remained net negative (-$202.95 on V3, -$274.19 on V2), failing the cross-asset consistency gate.

---

## 7. Multi-Testing Correction (Holm-Bonferroni Family-Wise Error Rate)

Null hypothesis $H_0$: Variant expectancy $\le 0$. Pre-registered $\alpha = 0.05$. Number of variants $m = 9$.

| Rank | Variant ID | Expectancy ($) | Target $\alpha = \frac{0.05}{m - k + 1}$ | Bootstrap 95% CI Lower Bound ($) | Verdict |
| :---: | :---: | :---: | :---: | :---: | :--- |
| 1 | **H_S3_V3** | +$0.71 | 0.00556 | -$5.03 | `NULL_NOT_REJECTED` (CI spans zero) |
| 2 | **H_S3_V2** | +$0.27 | 0.00625 | -$5.10 | `NULL_NOT_REJECTED` (CI spans zero) |
| 3 | **H_S3_V1** | -$1.68 | 0.00714 | -$7.88 | `NULL_NOT_REJECTED` (Negative expectancy) |
| 4 | **H_S1_V1** | -$2.28 | 0.00833 | -$6.60 | `NULL_NOT_REJECTED` (Negative expectancy) |
| 5 | **H_S1_V2** | -$2.30 | 0.01000 | -$6.49 | `NULL_NOT_REJECTED` (Negative expectancy) |
| 6 | **H_S1_V3** | -$2.39 | 0.01250 | -$6.78 | `NULL_NOT_REJECTED` (Negative expectancy) |
| 7 | **H_S2_V1** | -$2.54 | 0.01667 | -$6.55 | `NULL_NOT_REJECTED` (Negative expectancy) |
| 8 | **H_S2_V2** | -$3.01 | 0.02500 | -$9.79 | `NULL_NOT_REJECTED` (Negative expectancy) |
| 9 | **H_S2_V3** | -$3.24 | 0.05000 | -$8.66 | `NULL_NOT_REJECTED` (Negative expectancy) |

**Conclusion:** Zero variants achieved statistically significant positive expectancy at the 5% family-wise error rate.

---

## 8. Authoritative Declarations & Final System State

1. **Frozen M5 ETH Candidate Status:**  
   `vol_aware_mean_reversion_v1` is permanently closed with disposition `HISTORICAL_OOS_REJECTED_FOR_PROMOTION` (Net PnL -$15.69 USD, 13 trades, Multi-Asset Gate FAIL). It was strictly untouched, unmodified, and unretuned throughout this experiment.
2. **Burned Windows Status:**  
   - `2026-01-01` to `2026-06-30`: `BURNED_FOR_PROMOTION` (Permanently invalid for promotion).
   - `2026-07-01` to `2026-11-09`: `BURNED_FOR_SUCCESSOR_SELECTION` (Pristine, untouched, zero lookahead or exposure).
3. **Successor Selection Verdict:**  
   Zero of the 9 pre-registered successor variants meet the promotion criteria for candidate freezing:
   - `H_S1_V1`, `H_S1_V2`: `RISK_REDUCTION_ONLY / NOT_PROMOTABLE`
   - `H_S1_V3`: `REJECTED`
   - `H_S2_V1`, `H_S2_V2`, `H_S2_V3`: `REJECTED`
   - `H_S3_V1`: `RISK_REDUCTION_ONLY / NOT_PROMOTABLE`
   - `H_S3_V2`, `H_S3_V3`: `INCONCLUSIVE / INSUFFICIENT_ECONOMIC_MARGIN_FOR_PROMOTION`
4. **Runtime Collector Status:**  
   `STOPPED`. No daemon running.
5. **Windows Scheduled Task:**  
   `DISABLED`.
6. **Live / Real Trading Status:**  
   `DISABLED` (`real_orders = False`).
7. **Git Repository State:**  
   Clean research branch `research/m2-historical-sources-pilot`. Zero unauthorized commits, zero pushes.
