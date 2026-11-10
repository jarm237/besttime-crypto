# M4-ML2 — Cost-Aware Payoff Regression & Risk-Constrained Sizing Pilot

**Milestone:** M4-ML2 Research Pilot  
**Authoritative Plan Reference:** `docs/SYSTEM_IMPLEMENTATION_PLAN.md`  
**Execution Timestamp:** 2026-11-10T16:11:37Z  
**Branch:** `research/m2-historical-sources-pilot`  
**Research Designation:** `ADAPTIVE_DEVELOPMENT_RESEARCH`

---

## Required States Block

```text
M4_ML2_DISPOSITION          = ML2_REJECTED
M5_FROZEN_ETH_STATUS        = HISTORICAL_OOS_REJECTED_FOR_PROMOTION
PROSPECTIVE_COLLECTOR       = STOPPED
SCHEDULED_TASK              = DISABLED
REAL_TRADING                = DISABLED
BURNED_WINDOWS              = 2026-H1 (2026-01-01 to 2026-06-30), 2026-H2 (2026-07-01 to 2026-11-09)
```

---

## 1. Executive Summary

The **M4-ML2 Research Pilot** evaluated whether continuous payoff regression paired with risk-constrained position sizing can improve the net economics of the underlying `base_ema_trend` strategy and outperform the binary classification filter tested in M4-ML1.

Prior to modeling, **Phase A** successfully reconciled all trade-level accounting discrepancies from M4-ML1 with a **0.0000 USD mathematical residual**, proved that compounding impacts occurred **100% intra-fold**, and verified that the single missing candle in 3 years (`2023-03-24 13:00 UTC`) was an exchange-wide Binance outage rather than data corruption.

In **Phase B & C**, scale-independent normalized payoff targets in basis points ($\text{bps} = \frac{\text{net\_pnl}}{\text{invested\_notional}} \times 10,000$) were modeled across 3 expanding walk-forward folds using **Ridge** ($L_2$ regularized) and **Huber** (robust loss) regressors. Huber regressor demonstrated significant and consistent positive rank correlation with realized returns ($\rho = 0.25 - 0.37$, $p < 0.001$) by resisting outlier distortion from rare $+2,000$ bps trend winners that broke Ridge ($L_2$) fitting.

In **Phase D & E**, position sizing backtests across 14 bps, 20 bps, and 30 bps friction models showed that Huber risk-reducing sizing ($w \in [0.25, 1.00]$) achieved significant gross loss avoidance on chop trades ($+\$1,058.34$), improving net portfolio PnL by **$+\$665.45$** over baseline. However, scaling down overextended trades also downweighted early breakout winners ($-\$392.89$), and the strategy remained deeply unprofitable overall ($-\$1,189.84$ at 14 bps; $-\$2,053.79$ at 30 bps; positive in only 1 of 3 validation folds).

Per formal stop rules, because continuous payoff regression failed to achieve positive net economic expectancy after friction, **M4-ML2 is formally REJECTED (`ML2_REJECTED`)**.

---

## 2. Phase A — Final Accounting Reconciliation & Population Identity

### 2.1 Canonical Population Identity
A core discrepancy identified at the conclusion of M4-ML1 was the difference between the **Static Feature Dataset** ($N=314$ validation opportunities) and the **Fold Runner Simulation** ($N=320$ baseline opportunities).

- **Root Cause Verified:** The static dataset was created by replaying the entire 36-month development window (2023–2025) as a continuous backtest and then slicing trades whose `signal_time` fell within each fold's validation window. Because continuous replay allows open positions to traverse fold boundaries, fewer entry opportunities were triggered near boundary edges. In contrast, the fold runner backtest strictly simulates each fold independently, resetting open inventory to flat at `val_start`. This allowed the fold runner to take **6 additional boundary crossover entries** at the start of validation periods:
  - Fold 1: $115$ runner trades vs $113$ static trades ($+2$).
  - Fold 2: $107$ runner trades vs $103$ static trades ($+4$).
  - Fold 3: $98$ runner trades vs $98$ static trades ($+0$).
- **Canonical Decision:** The **Fold Runner Population ($N=320$ baseline trades, $N=304$ ML-filtered trades)** is established as the authoritative canonical population for all M4 portfolio simulations because it strictly enforces zero cross-fold position leakage and exact execution realism.

### 2.2 Sizing Compounding Scope Attribution
We audited whether the $\$22.03$ sizing impact observed between static trade attribution ($+\$9.43$) and runner simulation ($+\$12.61$) was caused by cross-fold capital carryover or intra-fold compounding:
- In `ExperimentRunner` and `PurgedWalkForwardTrainer`, `initial_capital` is initialized to exactly $\$20,000.00$ at the start of every fold.
- No profits, losses, or margin balances are transferred across fold boundaries.
- Therefore, the $\$22.03$ compounding benefit occurred **100% intra-fold**, caused purely by dynamic $10\%$ cash sizing preserving marginal capital after ML avoided losing trades within the same fold.

### 2.3 Mathematical Bridge Decomposition
The trade-by-trade audit between Baseline Runner ($N=320$) and ML1 Runner ($N=304$) yielded an exact reconciliation:
$$\text{Baseline Runner Net PnL } (-\$1,855.2863) - \text{PnL of 16 Rejected Trades } (+\$9.4348) + \text{Matched Sizing Compounding } (+\$22.0396) = \text{ML Runner Net PnL } (-\$1,842.6815)$$
$$\text{Mathematical Residual} = \mathbf{0.0000\text{ USD}}$$

### 2.4 Binance Outage Audit (26,303 vs 26,304 Candles)
A 1-bar discrepancy (26,303 bars instead of expected 26,304 across 1,096 days) was traced across both BTCUSDT and ETHUSDT:
- Exact missing timestamp: `2023-03-24 13:00:00 UTC`.
- Historical audit: Binance officially halted all Spot trading from 11:38 UTC to ~14:00 UTC on March 24, 2023 due to a matching engine bug on a trailing stop order. Zero trades were matched exchange-wide during bar 13:00 UTC.
- Verdict: Valid historical market hiatus; zero pipeline or parquet data corruption.

---

## 3. Phase B — Dataset Manifest & Normalized Target Definition

### 3.1 Scale-Independent Target Definition
To prevent position size or nominal price variations from distorting regression losses, the target is defined as normalized return in basis points:
$$\text{target\_net\_return\_bps}_i = \left( \frac{\text{realized\_net\_pnl}_i}{\text{invested\_notional}_i} \right) \times 10,000$$

### 3.2 Dataset Distribution Summary
- **Manifest ID:** `m4_ml2_payoff_dataset_v1`
- **Content Hash:** `0e04fa9407db4c6ace3ab3dbe3beceb2d290afc3ed9176bb55cc05bee9d339ca`
- **Universe:** BTCUSDT, ETHUSDT (Spot 1h, 2023-01-01 to 2025-12-31)
- **Total Trades:** 945
- **Return Distribution:**
  - Mean: $+8.39\text{ bps}$
  - Median: $-72.47\text{ bps}$
  - Std Dev: $356.04\text{ bps}$
  - Min: $-851.42\text{ bps}$
  - Max: $+3,341.03\text{ bps}$
  - 25th Percentile: $-138.77\text{ bps}$
  - 75th Percentile: $+23.75\text{ bps}$
- **Feature Set:** 13 PIT backward-looking features (returns over 6h, 12h, 24h, 48h; ATR-14 pct; 24h realized vol; EMA fast/slow pct & spread; RSI-14; volume ratio; 4h HTF trend alignment; BTC macro return). Zero post-signal lookahead.

---

## 4. Phase C — Regressor Diagnostics & Tail Tradeoff

Training was conducted under strict expanding walk-forward splits with inner-CV $\alpha$ selection on train folds. Unclosed trades at train cutoff were strictly purged.

| Metric | Fold 1 (Val 2025-01–04) | Fold 2 (Val 2025-05–08) | Fold 3 (Val 2025-09–12) |
| :--- | :---: | :---: | :---: |
| **Train / Val Sample Size** | 629 / 113 | 743 / 103 | 845 / 98 |
| **Ridge Selected $\alpha$** | 500.0 | 500.0 | 500.0 |
| **Ridge Spearman $\rho$** | 0.0620 | 0.2137 | 0.1853 |
| **Ridge MAE / RMSE (bps)** | 197.1 / 253.5 | 254.2 / 493.2 | 225.0 / 294.4 |
| **Ridge Top Decile Realized** | -172.8 bps | +156.8 bps | -84.3 bps |
| **Ridge Bot Decile Realized** | -119.4 bps | -169.6 bps | -97.2 bps |
| **Huber Selected $\alpha$** | 10.0 | 10.0 | 10.0 |
| **Huber Spearman $\rho$** | **0.3662** | **0.2503** | **0.2741** |
| **Huber MAE / RMSE (bps)** | **150.0 / 220.2** | **226.3 / 512.5** | **179.0 / 283.7** |
| **Huber Top Decile Realized** | -17.1 bps | -15.1 bps | -116.8 bps |
| **Huber Bot Decile Realized** | **-322.8 bps** | **-153.5 bps** | +35.9 bps |

### 4.1 Ridge vs Huber Tail Tradeoff Analysis
1. **Ridge Failure via Squared Loss ($L_2$):** Ridge minimizes mean squared error, making it hyper-sensitive to extreme $+1,000$ to $+3,300$ bps trend winners. In Fold 1, Ridge overfit these rare right-tail events, resulting in an inverted decile ranking (top decile returned $-172.8$ bps, worse than bottom decile's $-119.4$ bps) and poor correlation ($\rho = 0.062$).
2. **Huber Robustness via Hybrid Loss ($L_1 / L_2$):** Huber loss applies an absolute penalty to large residuals ($|r| > 1.35$), neutralizing the distorting leverage of extreme trend winners. Consequently, Huber achieved consistent positive rank correlation across all folds ($\rho = 0.25 - 0.37$).
3. **The Overextension Effect:** Across all folds, Huber assigned heavy negative weights to short-term momentum and volatility features (`return_6h`: $-4.1$ to $-7.8$, `ema_fast_pct`: $-3.0$ to $-6.1$, `btc_macro_return_24h`: $-3.9$ to $-4.5$). When an EMA crossover occurs after a large rapid surge, the trade is statistically overextended, leading to mean-reversion chop and severe losses. Huber successfully identified these high-risk entries (bottom decile in Fold 1 realized $-322.8$ bps).

---

## 5. Phase D & E — Economic Backtest Scorecard & Counterfactual Attribution

### 5.1 Comparative Economic Scorecard (2025 Validation, 320 Opportunities)

| Strategy Configuration | Sizing Policy | Mean Weight | Net PnL (14 bps) | Net PnL (20 bps) | Net PnL (30 bps) | Profit Factor | Positive Folds | Total Trades |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **`base_ema_trend`** | Fixed ($w=1.0$) | 1.000 | $-\$1,855.29$ | $-\$2,206.68$ | $-\$2,787.45$ | -1.49 | 1 / 3 | 320 |
| **`ema_trend_ml1_filtered`** | Binary Filter | 1.000 | $-\$1,842.68$ | $-\$2,177.07$ | $-\$2,729.93$ | -1.59 | 1 / 3 | 304 |
| **`ema_trend_ml2_ridge`** | Risk-Reducing | 0.996 | $-\$1,843.10$ | $-\$2,193.43$ | $-\$2,772.44$ | -1.48 | 1 / 3 | 320 |
| **`ema_trend_ml2_huber`** | Risk-Reducing | 0.909 | **$-\$1,189.84$** | **$-\$1,515.38$** | **$-\$2,053.79$** | **-0.82** | 1 / 3 | 320 |
| **`ema_trend_ml2_huber_asym`** | Asymmetric | 0.920 | $-\$1,182.16$ | $-\$1,511.30$ | $-\$2,055.60$ | -0.79 | 1 / 3 | 320 |

### 5.2 Counterfactual Attribution Breakdown (Huber vs Baseline)
By matching each of the 320 validation trades between Huber and Baseline under identical execution timings:
- **Loss Avoidance Delta (on losing trades):** **$+\$1,058.34$**  
  Huber successfully downweighted chop losses and false breakouts, scaling losing trades down toward $w \approx 0.25 - 0.70$.
- **Win Reduction Delta (on winning trades):** **$-\$392.89$**  
  Because breakout winners often exhibit rapid initial price momentum before entry, Huber downweighted several valid trends, reducing total gross winner profits.
- **Net Sizing Delta:** **$+\$665.45$** ($p = 0.0012$, bootstrap 95% CI: $[+\$265.13, +\$1,118.12]$).

### 5.3 Right-Tail Winner Retention Audit
We audited whether Huber sizing compromised the top 10 largest winners of the Baseline strategy:
- **Retention Rate:** **10 / 10 (100%)** of top winners were taken. Zero top winners were filtered out.
- **Full Allocation:** 6 out of 10 largest winners received maximum size ($w = 1.00$).
- **Marginal Downweighting:** 4 out of 10 received slight downweighting ($w \in [0.80, 0.99]$) because early momentum triggered mild overextension scores (e.g. trade on 2025-07-15 received $w = 0.80$, capturing $+\$283.77$ vs $\$352.58$).

---

## 6. Phase F — Stop Rules & Final Disposition

### 6.1 Evaluation Against Stop Rules
1. **Economic Viability Gate:** Huber sizing improved net return by $+\$665.45$, but aggregate net PnL remained **$-\$1,189.84$** at 14 bps and degraded monotonically to **$-\$2,053.79$** at 30 bps. **FAILED.**
2. **Consistency Across Folds:** Huber achieved positive net PnL in only **1 of 3 folds** (Fold 1: $-\$1,235.91$, Fold 2: $+\$1,080.64$, Fold 3: $-\$1,034.57$). **FAILED.**
3. **Statistical Promotion Standards:** The strategy fails to demonstrate an economic edge independent of broad market beta.

### 6.2 Final Disposition Verdict

```text
M4_ML2_DISPOSITION = ML2_REJECTED
```

**Disposition Reason:**  
While Huber robust payoff regression successfully captures trade-level overextension ($\rho \approx 0.27$, $p < 0.001$) and generates statistically significant loss reduction on false breakouts ($+\$1,058.34$, $p=0.0012$), continuous sizing cannot manufacture an economic edge from an underlying rule-based engine whose baseline expectancy is deeply negative ($-\$1,855.29$). Downweighting overextended trades inevitably shaves right-tail breakout profits ($-\$392.89$), leaving the overall system severely negative after transaction costs across all walk-forward validation periods.

---

## 7. Governance, Invariants & Next Steps

1. **Frozen M5 Candidate Status:**  
   `vol_aware_mean_reversion_v1` remains permanently marked:
   ```text
   HISTORICAL_OOS_REJECTED_FOR_PROMOTION
   ```
   Its configuration (`data/candidate_freezes/vol_aware_mean_reversion_v1_freeze.json`) has remained strictly immutable.
2. **Burned Windows Status:**  
   Both 2026 historical holdout windows (`2026-01-01` to `2026-06-30` and `2026-07-01` to `2026-11-09`) remain burned and strictly unaccessed for research or model selection.
3. **Runtime Invariants:**  
   - `real_orders = False`.
   - Prospective collector is `STOPPED`.
   - Windows Scheduled Task `BesttimeCryptoCollector` is `DISABLED`.
   - Zero git commits, pushes, merges, or rebases executed.
4. **Research Conclusion & Recommendation:**  
   Neither rule-based filtering (M4-VCB, HTF, OI), binary classification (M4-ML1), nor continuous payoff regression (M4-ML2) can rescue simple moving average crossover trend following on 1h Spot crypto against realistic 14–30 bps frictions. Further research in M4 must transition toward genuine cross-sectional market microstructure signals (e.g., funding rate arbitrage, cross-exchange basis spreads, order book imbalance) rather than continuing single-asset trend overlays.
