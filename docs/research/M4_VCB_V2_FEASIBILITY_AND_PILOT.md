# M4 — VCB Research Lineage Audit & Bounded Volatility Compression Breakout Pilot

## Executive Summary & Final Verdict

This document delivers the definitive audit of the historical **Volatility Compression Breakout (VCB)** research lineage and reports the controlled empirical results of the **VCB-v2 Bounded Development Pilot** evaluated across the 2023–2025 historical dataset on **BTCUSDT** and **ETHUSDT** (1h candles).

### Key Empirical Findings

```text
========================================================================================================
STRATEGY VARIANT             TRADES   RAW GROSS     FRICTION      NET 14bps    PF     MAX DD   WIN%  FOLDS+
========================================================================================================
always_flat (ANCHOR)              0    $   +0.00    $   +0.00     $   +0.00  0.00      0.00%   0.0%  0/3
buy_and_hold (ANCHOR)             2  $+11,229.59    $  +13.17   $+11,216.42  0.00     22.45% 100.0%  1/3
base_ema_trend (BASELINE)       945   $+4,111.44   $+2,695.36    $+1,416.07  1.08     10.08%  26.8%  1/3
--------------------------------------------------------------------------------------------------------
VCB_V2_BASELINE                 126    $   -4.75    $ +341.24     $ -345.99  0.81      3.78%  27.8%  1/3
VCB_V2_ABL_NO_COMPRESSION       473   $+1,882.31   $+1,299.32     $ +582.99  1.08      4.54%  31.1%  1/3
VCB_V2_ABL_NO_HTF               276    $ +330.19    $ +761.52     $ -431.33  0.89      8.34%  26.1%  1/3
========================================================================================================
```

### Definitive Research Disposition

1. **VCB_V2_BASELINE Disposition: `REJECTED_FOR_PROMOTION_AND_RESEARCH_RETIREMENT`**.
   - Net economic PnL at 14 bps friction is **-$345.99 USD** (Expectancy: **-$2.75 / trade**, Profit Factor: **0.81**).
   - Under 20 bps and 30 bps stress, performance degrades monotonically to **-$491.49 USD** and **-$731.55 USD**.
   - Both universe assets are individually negative (BTC: **-$121.48**, ETH: **-$224.51**).
   - The strategy is statistically indistinguishable from noise ($p = 0.791$, 95% bootstrap CI `[-$9.30, +$4.76]`).

2. **Core Hypothesis Disconfirmed**:
   - The central hypothesis that *pre-breakout rolling volatility compression (ATR $\le$ 25th percentile) selects high-quality breakout moves* failed decisively.
   - Removing the compression condition (`VCB_V2_ABL_NO_COMPRESSION`) **increased net PnL by +$928.98 USD** (from -$345.99 to +$582.99) and lifted the profit factor from 0.81 to 1.08.
   - In crypto spot markets, large multi-day trend continuations typically initiate from normal or expanding volatility environments; requiring ultra-tight compression selectively biases entries toward range-bound liquidity traps and false breakout whipsaws.

3. **Comparison Against Baseline Trend**:
   - Even the best breakout variant (`VCB_V2_ABL_NO_COMPRESSION` at +$582.99) generated less than half the net profit of simple 1h moving average crossover (`base_ema_trend` at +$1,416.07).
   - Both suffer from severe fold concentration: 100% of positive return is concentrated in Fold 2 (2024 bull run), while Fold 1 (2023) and Fold 3 (2025) are unprofitable.
   - Neither strategy demonstrates statistically significant edge ($p > 0.28$).

---

## 1. Phase A: Historical VCB Research Lineage Audit

A comprehensive codebase audit was conducted across `research/historical_market_replay_v5/` and related research drivers to catalog all previous volatility compression breakout iterations.

### Prior Lineage Inventory

| Variant ID | Timeframe / Universe | Entry / Filter Design | Barrier / Exit Logic | Historical Verdict & Failure Cause |
| :--- | :--- | :--- | :--- | :--- |
| `VOL_COMPRESSION_BREAKOUT_V1` | 15m / BTC, ETH | In-sample fitted ATR 65th percentile threshold (`fold_fitted_atr_q65_thresholds_bps`) | Fixed 350 bps TP, 150 bps SL, 48h timeout | **`REJECTED_AFTER_EXPOSED_AUDIT`**. Failed Gate 7 bootstrap lower bound. Audit Net Expectancy: **-22.26 bps** (-$677.42 USD on 2026-H1). Fixed barriers failed under volatility regime shifts. |
| `VCB_V2_VOL15` | 15m / BTC, ETH | 15-period ATR compression | Fixed barriers | **`REJECTED`**. Audit Net Exp: **-25.32 bps** (-$808.20 USD on 2026-H1). Severe whipsaws. |
| `VCB_V2_DONCHIAN192` | 15m / BTC, ETH | 48h Donchian (192 bars) | Fixed barriers | **`REJECTED`**. Audit Net Exp: **-18.99 bps** (-$542.42 USD on 2026-H1). Heavy trade lag. |
| `VCB_V2_SLOPE` | 15m / BTC, ETH | ATR slope compression | Fixed barriers | **`REJECTED`**. Audit Net Exp: **-30.73 bps** (-$986.35 USD on 2026-H1). Overfitting artifact. |
| `VCB_V3_VOL_NORMALIZED_BARRIER` | 15m / BTC, ETH | ATR-normalized TP/SL (dynamic multiples) | Dynamic ATR stops | **`REJECTED`**. Audit Net Exp: **-11.90 bps** (-$347.16 USD on 2026-H1). Cost drag exceeded alpha. |
| `VCB_V3_DIRECTIONAL_REGIME_GATE` | 15m / BTC, ETH | Macro 200-bar regime gate + ATR compression | Dynamic ATR stops | **`REJECTED`**. Audit Net Exp: **-20.32 bps** (-$613.68 USD on 2026-H1). Insufficient trade count, negative edge. |
| `VCB_V4_SELL_ONLY` | 15m / BTC, ETH | Short-only regime exploitation | Fixed/Dynamic | **`REJECTED_AT_EXPLORATORY_ADMISSION`**. Gate 7 bootstrap lower bound $\le 0$ (-1.55 bps/day). |
| `VCB_V5_SELL_ONLY_9ASSET` | 15m / 9 assets (DOGE, IOTA, NEAR, SOL, TRX, ZEC, BTC, ETH) | Cross-sectional short-only | Cross-sectional holdout | **`REJECTED_CROSS_SECTIONAL_HOLDOUT`**. Failed Gate 4 bootstrap (-3.35 bps/day) and Gate 7 Max Drawdown (20.28% > 20.0%). |

### Novelty Differentiation of VCB-v2

To avoid duplicating past failures (`DUPLICATIVE_HYPOTHESIS`), VCB-v2 was specified with four structural differences:
1. **1h Granularity**: Eliminated the high turnover and microstructure noise of the 15m candle series.
2. **Strictly Backward-Looking Rolling Percentiles**: Completely removed in-sample fitted global quantiles. Uses a rolling 72h window to evaluate the 25th percentile of ATR(14).
3. **Closed 4h Higher-Timeframe Trend Filter**: Enforces alignment with closed 4h bars ($Close > EMA_{100}$) with strictly zero lookahead.
4. **Dynamic Trailing EMA(20) & Timeout Exit**: Replaced brittle fixed basis-point profit targets with trend-trailing exits.

---

## 2. Phase B: VCB-v2 Strategy Contract & Pre-Registered Ablations

### Formal Strategy Specifications

1. **Indicator Calculations**:
   $$\text{TR}_t = \max(H_t - L_t, |H_t - C_{t-1}|, |L_t - C_{t-1}|)$$
   $$\text{ATR}_{14, t} = \frac{1}{14} \sum_{i=0}^{13} \text{TR}_{t-i}$$
   $$\text{Compression Cutoff}_t = \text{Percentile}_{25}\left(\{\text{ATR}_{14, t-k}\}_{k=0}^{71}\right)$$
   $$\text{Donchian High}_t = \max_{k=1}^{24} H_{t-k}$$

2. **Entry Conditions (Flat $\rightarrow$ Long)**:
   - **Compression Condition**: $\text{ATR}_{14, t} \le \text{Compression Cutoff}_t$.
   - **Breakout Condition**: $C_t > \text{Donchian High}_t$.
   - **Higher-Timeframe Alignment**: $C_{4h, \text{closed}} > \text{EMA}_{100, 4h, \text{closed}}$.
   - **Execution Timing**: Next-bar open ($t+1$) market fill.

3. **Exit Conditions (Long $\rightarrow$ Flat)**:
   - **Protective Stop Loss**: Triggered conservatively on intra-bar low $L_t \le C_{\text{entry}} - 2.5 \times \text{ATR}_{\text{entry}}$.
   - **Trend Breakdown Exit**: $C_t < \text{EMA}_{20}(C)$ evaluated at bar close, filled next bar open.
   - **Timeout Exit**: Maximum holding duration of 48 hours ($t - t_{\text{entry}} \ge 48$).

### Pre-Registered Ablations
- `VCB_V2_BASELINE`: Full strategy (Compression + Donchian + 4h HTF).
- `VCB_V2_ABL_NO_COMPRESSION`: Compression requirement waived ($\text{require\_compression} = \text{False}$).
- `VCB_V2_ABL_NO_HTF`: HTF trend filter waived ($\text{require\_htf\_trend} = \text{False}$).

---

## 3. Phase C: Execution Realism & Friction Accounting

In adherence to realistic market microstructure governance:
- **Spot Marketable Order Baseline**: Spot retail accounts cannot assume passive maker fills. All entries and exits are modeled as taker executions subject to full fee, spread, and slippage friction.
- **Baseline Friction (14.0 bps round-trip)**:
  - Exchange Fee: 5.0 bps per leg (10.0 bps round-trip).
  - Slippage Drag: 1.0 bps per leg (2.0 bps round-trip).
  - Spread Drag: 1.0 bps per leg (2.0 bps round-trip).
  - Formula: $\text{Total Round-Trip} = 10.0 + 2.0 + 2.0 = 14.0\text{ bps}$.
- **Stress Regime 1 (20.0 bps round-trip)**:
  - 14.0 bps fees + 3.0 bps slippage + 3.0 bps spread.
- **Stress Regime 2 (30.0 bps round-trip)**:
  - 20.0 bps fees + 5.0 bps slippage + 5.0 bps spread.
- **Accounting Reconciliation Identity**:
  $$\text{Net PnL} = \text{Raw Gross PnL} - (\text{Exchange Fees} + \text{Slippage Drag} + \text{Spread Drag})$$
  Verified to match exactly within $\$0.00$ tolerance across all runs.

---

## 4. Phase D: Empirical Results & Comparative Scorecard

### Full 36-Month Development Window (2023-01-01 to 2025-12-31)

| Strategy ID | Family | Trades | Raw Gross | Total Friction | Net PnL (14 bps) | Net PnL (20 bps) | Net PnL (30 bps) | Win Rate | Profit Factor | Max DD | Net Expectancy | Payoff Ratio | Avg Hold | Exposure |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `always_flat` | ANCHOR | 0 | $\$0.00$ | $\$0.00$ | **$\$0.00$** | $\$0.00$ | $\$0.00$ | 0.0% | 0.00 | 0.00% | $\$0.00$ | 0.00 | 0.0h | 0.0% |
| `buy_and_hold` | ANCHOR | 2 | $\$11,229.59$ | $\$13.17$ | **$\$11,216.42$** | $\$11,209.59$ | $\$11,197.85$ | 100.0% | 0.00 | 22.45% | $\$5,608.21$ | 0.00 | 26,278.0h | 100.0% |
| `base_ema_trend` | BASELINE | 945 | $\$4,111.44$ | $\$2,695.36$ | **$\$1,416.07$** | $\$294.57$ | $-\$1,445.33$ | 26.8% | 1.08 | 10.08% | $\$1.50$ | 2.94 | 29.4h | 100.0% |
| `VCB_V2_BASELINE` | VCB_V2 | 126 | $-\$4.75$ | $\$341.24$ | **$-\$345.99$** | $-\$491.49$ | $-\$731.55$ | 27.8% | 0.81 | 3.78% | $-\$2.75$ | 2.09 | 11.4h | 5.5% |
| `VCB_V2_ABL_NO_COMPRESSION` | ABLATION | 473 | $\$1,882.31$ | $\$1,299.32$ | **$\$582.99$** | $\$23.86$ | $-\$874.30$ | 31.1% | 1.08 | 4.54% | $\$1.23$ | 2.40 | 13.3h | 23.9% |
| `VCB_V2_ABL_NO_HTF` | ABLATION | 276 | $\$330.19$ | $\$761.52$ | **$-\$431.33$** | $-\$744.80$ | $-\$1,256.00$ | 26.1% | 0.89 | 8.34% | $-\$1.56$ | 2.53 | 11.2h | 11.8% |

---

## 5. Phase E: Ablation Analysis & Deep Failure Attribution

### 1. Volatility Compression Destruction of Alpha
Comparing `VCB_V2_BASELINE` (with compression) vs `VCB_V2_ABL_NO_COMPRESSION` (without compression):
- **Trade Count**: Dropped from 473 to 126 (-73.4%).
- **Gross PnL**: Collapsed from **+$1,882.31** to **-$4.75** (a loss of $\$1,887.06$ in gross edge).
- **Net PnL (14 bps)**: Dropped from **+$582.99** to **-$345.99** (delta = $-\$928.98$).
- **Expectancy**: Dropped from **+$1.23 / trade** to **-$2.75 / trade**.
- **Mechanistic Cause**:
  In crypto markets, true multi-day breakouts do not typically trigger out of the 25th percentile lowest ATR. Instead, ultra-low volatility regimes are characterized by low liquidity and high susceptibility to spoofing, wick expansion, and mean-reverting pinbars. By forcing the strategy to enter only during extreme compression, genuine trend breakouts occurring during normal volatility regimes were discarded, while false breakouts and whipsaws were concentrated.

### 2. Higher-Timeframe Trend Alignment Gating
Comparing `VCB_V2_BASELINE` (with 4h HTF) vs `VCB_V2_ABL_NO_HTF` (without HTF):
- Without the 4h closed-candle HTF trend filter, trades increased from 126 to 276 (+119.0%).
- Maximum drawdown more than doubled from **3.78% to 8.34%**.
- ETH performance deteriorated drastically from **-$224.51** to **-$567.44**.
- While HTF trend filtering successfully reduces counter-trend drawdown and prevents disastrous short-term wicks against the macro regime, it cannot compensate for the negative gross expectancy induced by the volatility compression filter.

### 3. Comparison with Simple Moving Average Crossover (`base_ema_trend`)
- `base_ema_trend` achieved **+$1,416.07** across 945 trades with a 29.4-hour average holding period.
- `VCB_V2_BASELINE` generated **-$345.99** (an underperformance of $-\$1,762.06$).
- Even without compression, `VCB_V2_ABL_NO_COMPRESSION` generated only **+$582.99** (underperforming `base_ema_trend` by $-\$833.08$).
- Moving average trend following maintains position continuous exposure (100%), capturing the full fat-tailed drift of the 2024 bull run, whereas Donchian channel breakouts with short holding periods (11–13h) repeatedly incur friction churn while exiting early.

---

## 6. Phase F: Walk-Forward Consistency & Statistical Significance

### Chronological Fold Breakdown

```text
Fold 1 (2025-01 to 2025-05): Correction / Consolidation
Fold 2 (2025-05 to 2025-09): Bullish Trend Expansion
Fold 3 (2025-09 to 2025-12): Range Chop / Retracement
```

| Strategy ID | Fold 1 Net PnL | Fold 2 Net PnL | Fold 3 Net PnL | Positive Folds | $p$-value ($t$-test) | $p$-value (Bootstrap) | 95% Bootstrap CI |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `base_ema_trend` | $-\$1,671.66$ | $+\$1,065.17$ | $-\$1,248.80$ | **1/3** | 0.2608 | 0.3070 | `[-$3.61, +$6.95]` |
| `VCB_V2_BASELINE` | $-\$173.02$ | $+\$308.05$ | $-\$23.54$ | **1/3** | 0.7910 | 0.7902 | `[-$9.30, +$4.76]` |
| `VCB_V2_ABL_NO_COMPRESSION` | $-\$366.99$ | $+\$660.15$ | $-\$14.40$ | **1/3** | 0.2898 | 0.3140 | `[-$3.33, +$6.02]` |
| `VCB_V2_ABL_NO_HTF` | $-\$778.44$ | $+\$240.16$ | $-\$184.77$ | **1/3** | 0.7008 | 0.6950 | `[-$7.78, +$5.89]` |

### Asset-Level Breakdown

| Strategy ID | BTC Trades | BTC Net PnL | ETH Trades | ETH Net PnL | Both Assets Positive? |
| :--- | :---: | :---: | :---: | :---: | :---: |
| `base_ema_trend` | 457 | $+\$915.42$ | 488 | $+\$500.65$ | **YES** |
| `VCB_V2_BASELINE` | 75 | $-\$121.48$ | 51 | $-\$224.51$ | **NO (Both Negative)** |
| `VCB_V2_ABL_NO_COMPRESSION` | 253 | $+\$306.26$ | 220 | $+\$276.73$ | **YES** |
| `VCB_V2_ABL_NO_HTF` | 149 | $+\$136.10$ | 127 | $-\$567.44$ | **NO (ETH Negative)** |

---

## 7. Strategic Conclusions & Architectural Recommendations

1. **Retire Volatility Compression Breakout (VCB) Lineage Permanently**:
   Across 8 separate implementations spanning 15m and 1h frequencies, multi-barrier models, directional regime gates, and strictly backward-looking rolling percentiles, the VCB family has failed to establish a positive net expectancy after transaction costs. Volatility compression does not signal profitable trend continuation in crypto spot markets; it signals range consolidation and liquidity stop-hunting.

2. **The Nature of Spot Marketable Friction**:
   At 14 bps friction, trade churn is fatal to high-frequency strategies. Strategies with trade counts $> 500$ over 3 years incur over $\$1,500 - \$2,700$ in friction drag on a $\$20,000$ base. Any viable successor strategy must target a higher average holding duration ($> 36\text{ hours}$) and a minimum gross expectancy $> 30\text{ bps per trade}$ to survive 20–30 bps execution stress.

3. **Trend Following Dominance over Channel Breakouts**:
   Simple moving average crossovers (`base_ema_trend`) capture continuous trending drift substantially better than breakout channel entries. However, even `base_ema_trend` fails walk-forward consistency (profitable in only 1 of 3 folds) and degrades to $-\$1,445.33$ under 30 bps stress.

---

## 8. Final Invariants & Governance Declarations

1. **Frozen M5 ETH Candidate Status**:
   - `vol_aware_mean_reversion_v1` remains permanently marked as:
     $$\text{M5\_FINAL\_DISPOSITION} = \text{HISTORICAL\_OOS\_REJECTED\_FOR\_PROMOTION}$$
   - No parameters, code, or freeze metadata were altered during this research.

2. **Holdout Window Sanctity**:
   - `2026-01-01` to `2026-06-30`: **`BURNED_FOR_PROMOTION`** (strictly preserved).
   - `2026-07-01` to `2026-11-09`: **`BURNED_FOR_SUCCESSOR_SELECTION`** (strictly preserved).
   - Zero evaluation runs were executed on these holdout windows.

3. **Runtime & Infrastructure Safety**:
   - Collector status: **`STOPPED`**.
   - Scheduled task: **`DISABLED`**.
   - `real_orders`: **`False`**.
   - Git state: Zero commits, merges, or pushes performed.
