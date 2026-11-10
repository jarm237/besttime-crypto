# M4 Successor Research Specification & Failure-Grounded Pre-Registration

**Document Reference:** `docs/research/M4_SUCCESSOR_RESEARCH_SPECIFICATION.md`  
**Execution Horizon:** 2026-11-10  
**Repository Working Directory:** `D:\Workspaces\besttime-crypto`  
**Governance Standard:** Pre-registered, bounded empirical search with strict multiple-testing controls.  

---

## 1. Context & Empirical Impetus

Milestone M5 one-shot out-of-sample evaluation of `vol_aware_mean_reversion_v1` on 132 days of independent holdout (`2026-07-01` to `2026-11-09`) confirmed:
- **Raw Price Alpha:** +$2.46 USD (+0.019% per trade).
- **Execution Friction (14 bps RT):** $18.15 USD ($1.40 per trade, or 0.140% per trade).
- **Net Economic Outcome:** **-$15.69 USD (PF: 0.80, Win Rate: 46.2%, Expectancy: -$1.21/trade)**.
- **Stop-Out Asymmetry:** 5 ATR stop-loss exits generated **-$75.57 USD** in losses, completely overwhelming the 8 mean-reversion wins (+**$59.87 USD**).

This demonstrates that naive mean-reversion on 1h Spot crypto possesses a positive raw gross price drift, but its magnitude is **approximately 1/7th of round-trip friction**. Any viable successor must either:
1. Filter entries by minimum expected excursion hurdle (cost-aware hurdle).
2. Segment regimes by higher-timeframe trend to eliminate knife-catching stop-outs.
3. Leverage genuine institutional open interest expansion rather than aggressive taker orderflow chasing.

---

## 2. Pre-Registered Hypotheses (Bounded Set)

| Hypothesis ID | Strategy Family | Core Mechanism | Pre-Registered Formal Hypothesis | Parameter Budget |
|---|---|---|---|---|
| **`H-S1`** | Cost-Aware Mean Reversion | Expected Move Hurdle | Entering RSI oversold dip ONLY when distance to middle Bollinger Band $\ge 40$ bps ($> 3\times$ round-trip friction) eliminates sub-friction noise trades and raises net expectancy. | $H \in \{30, 40, 50\}$ bps (3 variants) |
| **`H-S2`** | True Open Interest Trend | Institutional Capital Commitment | Entering EMA trend breakouts ONLY when 24h change in Open Interest ($\Delta OI_{24h} > 0$) and $OI > \text{SMA}_{5d}(OI)$ eliminates false breakouts without the whipsaw of taker orderflow. | Lookback $\in \{24h, 48h, 72h\}$ (3 variants) |
| **`H-S3`** | Macro Regime Trend-Filter | Directional Alignment | Entering 1h mean-reversion dips ONLY when 4h trend is bullish (4h price $> 4h$ EMA-200) eliminates catastrophic stop-outs during directional liquidation cascades. | 4h EMA $\in \{100, 150, 200\}$ (3 variants) |

> [!IMPORTANT]
> **Total Search Budget:** Exactly $3 \times 3 = 9$ discrete candidate evaluations across the development window. No automated grid search or machine learning parameter optimization is authorized.

---

## 3. Temporal Windows & Provenance Boundaries

To prevent lookahead bias and data snooping:

| Time Window | Date Span | Governance Status | Usage Rules |
|---|---|---|---|
| **Development Horizon** | `2023-01-01` $\to$ `2025-12-31` (36 mo) | **`RESEARCH_AUTHORIZED`** | 3 chronological walk-forward folds (24h purge gap). Model selection and hypothesis testing occur strictly here. |
| **H1/2026 Window** | `2026-01-01` $\to$ `2026-06-30` (6 mo) | **`BURNED_FOR_PROMOTION`** | Overlaps with M4 development Fold 3. Strictly off-limits for successor selection. |
| **H2/2026 Window** | `2026-07-01` $\to$ `2026-11-09` (4.5 mo) | **`BURNED_FOR_SUCCESSOR_SELECTION`** | Used in M5 one-shot evaluation. Strictly off-limits for successor tuning or validation. |
| **Prospective Shadow Horizon** | `2026-11-10` $\to$ Forward | **`PRISTINE_PROSPECTIVE_ONLY`** | Sole authorized venue for prospective shadow validation of any successor promoted from development. |

---

## 4. Cost Model & Mandatory Economic Gates

All successor evaluations must execute under identical, non-negotiable economic contracts:

### Execution & Cost Specifications
- **Execution Timing Policy:** `NEXT_BAR_OPEN` (signals at bar $t$ close $\to$ fills at bar $t+1$ open).
- **Same Candle Conflict Policy:** `CONSERVATIVE_SL_FIRST`.
- **Baseline Cost Model:** **14 bps round-trip** (Spot: 10 bps taker fee + 2 bps slippage + 2 bps spread).
- **Stress Cost Model:** **20 bps round-trip** (Spot: 14 bps taker fee + 3 bps slippage + 3 bps spread).
- **Position Sizing:** \$10,000 initial capital, 10% notional allocation (\$1,000 per trade), max 1 open position per symbol.

### Mandatory Development Gates (Must ALL Pass for Any Promotion)
1. **Aggregate Net PnL:** Net PnL $> \$0.00$ after 14 bps friction over the 3-year development window.
2. **Walk-Forward Consistency:** Positive Net PnL in **3 / 3 development folds**.
3. **Profit Factor:** Aggregate Profit Factor $\ge 1.30$.
4. **Sample Size:** Total resolved trades $\ge 30$ on development window.
5. **Drawdown Boundary:** Maximum Drawdown $\le 10.0\%$.
6. **Stress Resilience:** Positive Net PnL under 20 bps stress scenario.
7. **Multiple Testing Control:** Family-Wise Error Rate (FWER) controlled at $\alpha = 0.05$ via Holm-Bonferroni step-down adjustment.

---

## 5. Baselines for Comparison

Every successor evaluation must be benchmarked against:
1. `always_flat_v1`: Proves zero trades, zero drift, zero phantom fees.
2. `buy_and_hold_v1`: Passive asset return over identical time window (with explicit reporting of exposure time).
3. `price_only_unfiltered`: The base unfiltered rule (`ema_trend_12_26_v1` or `rsi_bollinger_mr_v1`) to isolate the exact incremental alpha contributed by the filter.
