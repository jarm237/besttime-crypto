# M4-ML1 — Counterfactual Economic Attribution & ML2 Payoff Feasibility

## Executive Summary & Required States

This authoritative document delivers the mathematical reconciliation of trade-level attribution versus portfolio simulation in **M4-ML1**, audits walk-forward integrity and dataset coverage, provides in-depth predictive diagnostics, and evaluates the empirical feasibility of an **ML2 Cost-Aware Payoff Model**.

```text
========================================================================================================
METRIC / VARIABLE                        BASELINE RUNNER     ML-FILTERED RUNNER     DELTA / ATTRIBUTION
========================================================================================================
Total Out-of-Fold Trades (2025)                      320                    304              -16 trades
Full 2025 Validation Net PnL (14 bps)        -$1,855.28             -$1,842.68             +$12.61 USD
--------------------------------------------------------------------------------------------------------
DIRECT REJECTED TRADES (16 trades)            +$9.43                $0.00                  -$9.43 USD
DYNAMIC SIZING & CASH COMPOUNDING (280 tr)    -$1,864.71             -$1,842.68             +$22.03 USD
--------------------------------------------------------------------------------------------------------
RECONCILED SUM                               -$1,855.28 - $9.43 + $22.03 = -$1,842.68       RESIDUAL: 0.0000
========================================================================================================
```

### Formal Research Declarations

```text
ML1_TRADE_MATCHING                  = 304_MATCHED_16_REJECTED_0_NEW_280_RESIZED
ML1_COUNTERFACTUAL_PNL_BRIDGE       = RECONCILED_EXACT_ZERO_RESIDUAL
ML1_POSITION_STATE_ATTRIBUTION      = CASH_COMPOUNDING_AND_FOLD_BOUNDARY_CONFIRMED
ML1_TRAIN_LABEL_MATURITY            = STRICTLY_ENFORCED_OUTCOME_PURGED
ML1_WALK_FORWARD_LEAKAGE            = AUDITED_ZERO_LOOKAHEAD
ML1_PROBABILITY_CALIBRATION         = FAILED_NEGATIVE_ECONOMIC_CORRELATION
ML1_PAYOFF_DIAGNOSTICS              = SEVERE_FAT_TAIL_TRIMMING_CONFIRMED

ML1_FINAL_DISPOSITION               = ML1_REJECTED_OR_INCONCLUSIVE
ML2_PAYOFF_INFORMATION_FEASIBILITY  = EXPLORATORY_SUPPORTED
ML2_NEXT_EXPERIMENT_DECISION        = PROPOSE_BOUNDED_CONTINUOUS_PAYOFF_REGRESSION

M5_FROZEN_CANDIDATE                 = HISTORICAL_OOS_REJECTED_FOR_PROMOTION
PROSPECTIVE_COLLECTOR               = STOPPED
REAL_TRADING                        = DISABLED
```

---

## 1. Phase A — Reconcile Trade-Level Counterfactuals (The +$109.90 Paradox Resolved)

### 1. The Paradox Defined
In initial post-pilot reporting, an apparent contradiction emerged between two reporting layers:
1. **Trade-Level Static Dataset (314 validation opportunities)**:
   - ML rejected 11 trades: 8 losers ($-\$78.29$) and 3 winners ($+\$175.58$).
   - Net PnL of rejected trades was **+$97.29 USD**.
   - Naive subtraction implied a portfolio penalty of **-$97.29 USD**.
2. **Portfolio Backtest Runner (320 validation trades)**:
   - Baseline Net PnL was **-$1,855.28 USD**.
   - ML-Filtered Net PnL was **-$1,842.68 USD**.
   - Observed portfolio improvement was **+$12.61 USD**.
   - Apparent unexplained divergence: `+$12.61 - (-$97.29) = +$109.90 USD`.

### 2. Root Cause Audit & Lineage Classification
Every trade was matched across execution engines. The investigation proved that the divergence is not a code defect, but reflects **two distinct, valid execution realities**:

#### A. Trade Population & Boundary Trade Count (314 vs 320 trades)
- **Static Dataset (314 trades)** was extracted from a single contiguous 36-month backtest (`2023-01-01` to `2025-12-31`), where position state carried continuously across fold boundaries.
- **Fold Backtest Runner (320 trades)** evaluated each fold independently in `ExperimentRunner` starting from cash $\$20,000$ and zero positions at `val_start`.
- Because each fold started fresh with flat inventory, the strategy was able to execute initial crossover signals at the fold boundary that were blocked in the continuous run by positions held through the purge gap. This generated 6 additional trades at the boundary (10 new boundary trades vs 4 shifted trades).

#### B. Dynamic Cash Compounding & Sizing Effect
- In `ExperimentRunner`, sizing is dynamic: `allocation_pct = 0.10` of `current_cash`.
- In Fold 1 (a sharp market drawdown where Baseline lost $-\$1,671.66$), the ML-filtered portfolio preserved more cash early in the period.
- Entering Fold 2 (a powerful trending bull market where Baseline earned $+\$1,065.17$), the ML portfolio began with higher cash reserves, leading to systematically larger position sizes ($+\$50$ to $+\$120$ notional per trade) on the large trend winners.
- Across the 280 matched trades whose notional differed due to capital compounding, the net sizing impact added **+$22.03 USD**.

#### C. Runner Trade Rejection Attribution
Inside the actual fold simulations:
- Exactly **16 trades** were rejected by ML (13 losers = $-\$194.04$, 3 winners = $+\$203.47$).
- The actual net PnL of rejected trades in the runner was **+$9.43 USD** (not $+\$97.29$).
- Removing them incurred a direct loss of **-$9.43 USD**.

### 3. The Exact Mathematical Bridge

$$\begin{aligned}
\text{Baseline Runner Net PnL} & = -\$1,855.28 \\
\text{Direct Impact of 16 Rejected Trades } (-\text{PnL}_{\text{rej}}) & = -\$9.43 \\
\text{New ML Trades Impact } (0\text{ trades}) & = +\$0.00 \\
\text{Dynamic Sizing \& Cash Compounding Impact } (280\text{ trades}) & = +\$22.03 \\
\hline
\mathbf{\text{Reconciled ML Runner Net PnL}} & = \mathbf{-\$1,842.68} \\
\mathbf{\text{Actual ML Runner Net PnL}} & = \mathbf{-\$1,842.68} \\
\mathbf{\text{Residual}} & = \mathbf{0.0000}
\end{aligned}$$

The $\$109.90$ difference is fully accounted for:
$$\Delta_{\text{boundary trades}} (\$97.29 - \$9.43 = +\$87.86) + \Delta_{\text{compounding sizing}} (+\$22.03) = +\$109.89 \approx +\$109.90\text{ USD}$$

---

## 2. Phase B — Walk-Forward Integrity & Dataset Coverage

### 1. Dataset Coverage Audit (The 26,303 vs 26,304 Bar Explanation)
- Expected hours from `2023-01-01 00:00:00Z` to `2025-12-31 23:00:00Z`:
  - 2023: 365 days $\times$ 24 = 8,760 hours
  - 2024: 366 days $\times$ 24 = 8,784 hours (leap year)
  - 2025: 365 days $\times$ 24 = 8,760 hours
  - Total expected: **26,304 hours**.
- The dataset contains **26,303 hours** per asset.
- **Root Cause Verified**: Exactly one hour is missing in both BTCUSDT and ETHUSDT: **`2023-03-24 13:00 UTC`**.
- This missing hour corresponds to a **documented Binance exchange-wide emergency maintenance outage** on March 24, 2023 (temporary suspension of spot trading due to a trailing stop matching engine bug). Binance produced zero public trade ticks and zero 1h candle records during this outage.
- This is an authentic historical market reality, not a pipeline or data corruption defect.

### 2. Walk-Forward Eligibility Verification
- **Training Label Maturation**: Strictly enforced. In `purged_walk_forward_trainer.py`, trade inclusion requires `exit_time <= t_train_end`. Trades entered before cutoff but still active at cutoff are completely purged.
- **Embargo Enforcement**: A 24-hour buffer (`purge_gap_hours = 24`) separates training cutoffs from validation windows, preventing serial correlation leakage.
- **Threshold Selection Invariance**: $\theta^*$ is selected exclusively via 3-fold inner cross-validation on the training fold; outer validation data is strictly held out.
- **Preprocessing Isolation**: `StandardScaler` is fitted solely on training fold features and applied downstream.
- **Zero-Lookahead Feature Alignment**: All 13 input features are computed at signal candle close $t$, strictly preceding order execution at $t+1$ open.

---

## 3. Phase C — ML1 Predictive Diagnostics

### 1. Predicted Probability Distribution & Calibration Failure
- **Sample**: 314 out-of-fold validation opportunities across 2025.
- **Predicted Probability Stats**: Mean = 0.2900, Median = 0.2707, Min = 0.1808, Max = 0.7417.
- **Brier Score Audit**:
  - Model Brier Score: **0.2016**
  - Constant Baseline Brier Score (fitted on train win rate 26.77%): **0.1915**
  - **Brier Skill Score (BSS)**: **-0.0529**
  - A negative Brier Skill Score confirms that the Logistic Regression model performed **worse than a naive constant guess**.

### 2. Calibration by Probability Bin

| Probability Bin | Trade Count | Mean Predicted Prob | Realized Win Rate | Mean Net PnL (USD) | Total Net PnL (USD) |
| :---: | :---: | :---: | :---: | :---: | :---: |
| `[0.15, 0.20]` | 11 | 0.1907 | **27.3%** | **+$8.84** | **+$97.29** |
| `(0.20, 0.25]` | 104 | 0.2276 | 23.1% | -$4.41 | -$458.73 |
| `(0.25, 0.30]` | 90 | 0.2730 | 31.1% | +$8.86 | +$797.23 |
| `(0.30, 0.35]` | 61 | 0.3230 | 26.2% | -$18.22 | -$1,111.61 |
| `(0.35, 1.00]` | 48 | 0.4380 | **20.8%** | **-$20.65** | **-$991.30** |

### 3. Net Payoff by Prediction Quantiles

| Quantile | Trades | Realized Win Rate | Mean Net PnL | Total Net PnL | Max Trade Win |
| :---: | :---: | :---: | :---: | :---: | :---: |
| **Q1 (Lowest Prob)** | 80 | 21.2% | **+$0.16** | **+$12.65** | +$285.89 |
| **Q2** | 77 | 24.7% | -$8.92 | -$687.10 | +$320.02 |
| **Q3** | 78 | 37.2% | +$11.75 | +$916.54 | +$635.16 |
| **Q4 (Highest Prob)** | 79 | 20.3% | **-$24.17** | **-$1,909.21** | +$374.69 |

### 4. Negative Economic Correlation & Fat-Tail Trimming
- **Statistical Correlation**:
  - Pearson $r(\hat{p}, \text{Net PnL}) = \mathbf{-0.1537}$ ($p = 0.0064$).
  - Spearman rank correlation $\rho = \mathbf{-0.2268}$ ($p = 0.0000$).
- **The Core Economic Mechanism**:
  In trend following, moving average crossovers accompanied by large short-term surges, high volume, and high RSI occur at **exhaustion points** (parabolic climaxes). The classifier identified strong momentum and assigned high win probability ($\hat{p} > 0.35$), but these trades entered at the peak and suffered severe mean-reverting losses (-$1,909.21).
  Conversely, quiet, low-volatility crossovers with modest initial momentum were assigned low win probability ($\hat{p} < 0.20$), yet these quiet entries had room to develop into 50-hour multi-hundred-dollar trend winners (e.g. +$126.71, +$55.90, +$47.30). Filtering them out trimmed the most profitable tail of the distribution.

---

## 4. Phase D — ML2 Payoff Feasibility Diagnostics

### 1. Feature Correlations with Realized Net Payoff (Full 945-Trade Development Universe)

| Feature Name | Pearson $r$ | Pearson $p$ | Spearman $\rho$ | Spearman $p$ | BTC Spearman $\rho$ | ETH Spearman $\rho$ | Consistent Sign across Assets? | Consistent across 2023, 2024, 2025? |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `return_6h` | **-0.1098** | 0.0007 | **-0.2620** | $0.0000$ | -0.2055 | -0.3050 | **YES** | **YES (-0.27, -0.16, -0.34)** |
| `ema_fast_pct` | **-0.1115** | 0.0006 | **-0.2607** | $0.0000$ | -0.2151 | -0.2958 | **YES** | **YES (-0.27, -0.16, -0.33)** |
| `ema_slow_pct` | **-0.1111** | 0.0006 | **-0.2600** | $0.0000$ | -0.2144 | -0.2958 | **YES** | **YES (-0.27, -0.16, -0.32)** |
| `atr_14_pct` | -0.0560 | 0.0854 | **-0.1970** | $0.0000$ | -0.1515 | -0.2231 | **YES** | **YES (-0.13, -0.14, -0.26)** |
| `return_12h` | -0.1005 | 0.0020 | **-0.1953** | $0.0000$ | -0.1621 | -0.2185 | **YES** | **YES (-0.22, -0.17, -0.19)** |
| `realized_vol_24h` | -0.0809 | 0.0128 | **-0.1867** | $0.0000$ | -0.1343 | -0.2193 | **YES** | **YES (-0.15, -0.11, -0.25)** |
| `ema_spread_pct` | -0.0839 | 0.0099 | **-0.1809** | $0.0000$ | -0.1397 | -0.2178 | **YES** | **YES (-0.23, -0.12, -0.18)** |
| `return_24h` | -0.0809 | 0.0129 | **-0.1676** | $0.0000$ | -0.1587 | -0.1712 | **YES** | **YES (-0.12, -0.12, -0.24)** |
| `btc_macro_return_24h` | -0.0580 | 0.0748 | **-0.1374** | $0.0000$ | -0.1587 | -0.1210 | **YES** | **YES (-0.09, -0.13, -0.17)** |
| `rsi_14` | -0.0658 | 0.0433 | **-0.1226** | $0.0002$ | -0.1019 | -0.1384 | **YES** | **YES (-0.14, -0.10, -0.13)** |
| `volume_ratio_24h` | -0.0115 | 0.7242 | -0.0693 | 0.0332 | -0.0659 | -0.0729 | **YES** | NO (-0.21, +0.03, -0.07) |
| `return_48h` | +0.0369 | 0.2566 | +0.0085 | 0.7938 | -0.0200 | +0.0321 | NO | NO (-0.17, +0.09, +0.07) |
| `htf_4h_trend_alignment` | +0.0460 | 0.1574 | +0.0067 | 0.8360 | +0.0368 | -0.0339 | NO | NO (-0.07, +0.04, +0.03) |

### 2. Payoff Asymmetry & Extreme Tail Concentration
- **Wins**: 253 trades, Mean Win = **+$79.29 USD**, Max Win = **+$638.69 USD**.
- **Losses**: 692 trades, Mean Loss = **-$26.94 USD**, Max Loss = **-$163.43 USD**.
- **Payoff Ratio**: **2.94 : 1**.
- **Extreme Concentration**:
  - Full strategy 3-year net profit: **+$1,416.07 USD**.
  - **Top 1% of trades (9 trades)** sum to **+$4,019.88 USD** (**284%** of strategy net profit).
  - **Top 5% of trades (47 trades)** sum to **+$11,305.09 USD** (**798%** of strategy net profit).
- This confirms why a binary win/loss classification objective fails: it penalizes any entry that has a 70% chance of a small loss, even if that same entry contains the right-tail possibility of a 20:1 payoff.

### 3. Empirical Verdict on ML2 Payoff Information
**`ML2_FEASIBILITY = EXPLORATORY_SUPPORTED`**

The features contain **statistically significant and robust negative predictive information regarding entry overextension**:
- Features capturing short-term extension (`return_6h`, `ema_fast_pct`, `atr_14_pct`, `realized_vol_24h`) have a Spearman rank correlation of $\rho \approx -0.20$ to $-0.26$ ($p < 10^{-8}$) with realized net return.
- This relationship is **directionally identical and statistically consistent across BTC and ETH**, and holds in every individual year (2023, 2024, 2025).
- Rather than trying to predict binary wins, an ML model can directly predict **expected continuous net payoff** $\hat{y} = \mathbb{E}[\text{Net PnL} \mid X]$.

---

## 5. Phase E — Proposal for Bounded ML2 Experiment

### Proposed Model Specification: Cost-Aware Continuous Payoff Regression (ML2)
1. **Target**: Continuous trade net PnL after friction:
   $$y_i = \text{trade\_net\_pnl\_14bps}_i$$
2. **Model**: L2-regularized Ridge Regression or Huber Loss Regression (robust to outlier tails):
   $$\min_{\beta} \sum_{i} \mathcal{L}_{\text{Huber}}(y_i - X_i \beta) + \lambda \|\beta\|_2^2$$
3. **Continuous Sizing / Volatility Targeting (No Binary Hard Filter)**:
   Instead of a binary accept/reject cliff that cuts off right-tail winners, map predicted expected payoff $\hat{y}_i$ into a **continuous position sizing scalar**:
   $$w_i = \text{clip}\left(1.0 + \gamma \cdot \frac{\hat{y}_i - \bar{y}}{\sigma_y}, 0.25, 1.75\right)$$
   - When $\hat{y}_i$ is low (overextended entry), position size is scaled down to 25% of baseline (reducing friction and drawdown).
   - When $\hat{y}_i$ is high (quiet, low-volatility base), position size is scaled up to 175%, maximizing exposure to large continuation trends.
   - Crucially, **all trades are taken**, preventing the accidental exclusion of rare fat-tailed winners.
4. **Validation**: Strictly Purged Walk-Forward across the same 3 development folds, evaluating 14, 20, and 30 bps friction models.
5. **Boundaries**: Strictly exploratory; zero promotion authority; zero interaction with burned 2026 windows.

---

## 6. Final Invariants & Governance Declarations

1. **Frozen M5 Candidate Integrity**:
   - Identity: `vol_aware_mean_reversion_v1` on `ETHUSDT` (1h spot).
   - File: [`data/candidate_freezes/vol_aware_mean_reversion_v1_freeze.json`](file:///d:/Workspaces/besttime-crypto/data/candidate_freezes/vol_aware_mean_reversion_v1_freeze.json).
   - Status remains permanently: `HISTORICAL_OOS_REJECTED_FOR_PROMOTION`.
   - Zero modifications performed.

2. **Holdout Sanctity**:
   - `2026-01-01` to `2026-06-30`: **`BURNED_FOR_PROMOTION`** (strictly preserved).
   - `2026-07-01` to `2026-11-09`: **`BURNED_FOR_SUCCESSOR_SELECTION`** (strictly preserved).
   - Neither window was accessed for feature exploration or diagnostic evaluation.

3. **Runtime & Infrastructure Safety**:
   - Live collector: **`STOPPED`**.
   - Scheduled task: **`DISABLED`**.
   - Real trading: **`real_orders = False`**.
   - Git hygiene: **Zero commits, merges, or pushes performed**.
