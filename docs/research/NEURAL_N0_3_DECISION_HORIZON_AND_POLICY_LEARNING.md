# NEURAL N0.3 — Neural Decision Horizon & Economic Policy Learning Report

**Date**: 2026-11-11  
**Workspace**: `D:\Workspaces\besttime-crypto`  
**Package**: `neural_trading/`  
**Authoritative Plan**: `docs/SYSTEM_IMPLEMENTATION_PLAN.md`  
**Execution Context**: Greenfield Unified Neural Trading System (Unconstrained Research)

---

## 1. Executive Summary & Authoritative Status Block

Phase N0.3 addressed the core structural questions arising from Phases N0.1 and N0.2:
1. **Material Correctness & Auditing**:
   - Clarified the actual train bar count: 2023–2024 development set contains **17,496 hourly bars**. Where the previously reported 14,544 came from was not reconstructed.
   - Audited the hard-risk barrier on HOLD: Fixed the vulnerability where voluntary HOLD actions previously bypassed concentration and minimum cash limits. Drifted weights that violate the 35% concentration cap or 5% minimum cash reserve now trigger a tracked **`risk_forced_rebalance`**.
   - Verified that the portfolio state vector explicitly models **6 components**: Index 0 is Cash, Indices 1–5 are `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`, `DOGEUSDT`.
   - Verified cost accounting: 14 bps round-trip is strictly 7 bps per executed buy/sell leg.
2. **Cadence & Starting-Phase Sensitivity Audit**:
   - Re-evaluated the retrospective finding from N0.2 where a 12h rebalancing schedule produced +$2,424.75 net PnL.
   - Evaluated all 12 starting UTC offsets (00:00 to 11:00 UTC): Net PnL ranged from **-$1,460.82 to +$1,948.32** (mean: +$602.62, std: $1,303.07). Offsets starting at 02:00, 03:00, and 04:00 UTC produced large losses (-$1,400+), while offsets starting at 00:00, 07:00, and 09:00 UTC yielded positive returns.
   - Showed that arbitrary fixed clock cadences are **phase-sensitive and brittle**, so the 12h result cannot be read as persistent timing alpha. The cause of the phase dependence was not established.
3. **Stateful Policy Collapse Root Cause**:
   - Demonstrated that the 99.53% hold rate of N0.2's `StatefulCostAwarePolicy` was not learned economic timing, but an artifact of **gate regularization collapse**.
   - With `lambda_churn = 0.50` and `lambda_turnover = 0.80`, 82.1% of validation bars produced gate probabilities $g_t < 0.05$ (median $g_t = 0.00566$). The optimizer zeroed out penalties by forcing $g_t \to 0$. In evaluation, the hard cutoff ($g \ge 0.50$) left the portfolio permanently trapped in 87.7% risky assets in a bear market. *(Caveat added in N1: the gate statistics came from a shorter 6-epoch re-training of the same architecture and loss, not from the exact N0.2 weights. That re-trained model crossed the 0.50 threshold on 98 bars, compared with 41 rebalances in N0.2. The mechanism is supported; the exact figures belong to the diagnostic model.)*
4. **Horizon-Aware Policy (N0.3) & Bounded Experiment**:
   - Designed `HorizonAwarePolicy` and `HorizonDifferentiableLoss`, decoupling 1-hour causal market observation from multi-hour execution cadence with exact training/evaluation parity (no soft-gate relaxation).
   - In the 2025 adaptive development evaluation (8,711 bars; 2025 had already been used in N0–N0.2, so it is not pristine OOS), the Horizon-Aware policy reduced annualized turnover to **38.9x** (paying $490.70 in friction) and executed 3 risk-forced rebalances.
   - Net PnL was **-$3,603.64** at 14 bps RT, outperforming the collapsed N0.2 Stateful Policy (+$1,904.57 improvement) but underperforming its matched-cash benchmark (-$3,117.14) by **-$486.50**. Decomposition (corrected in N1): gross excess -$6.10, incremental friction $480.40.
   - Scientific Verdict: **`NEURAL_POLICY_NEGATIVE_NET_VALUE`**.

```text
================================================================================
PHASE N0.3 AUTHORITATIVE STATUS BLOCK
================================================================================
N0_3_DATA_PROVENANCE              = VERIFIED_LOCAL_BINANCE_SPOT_1H_SHA256
N0_3_TRAINING_WINDOW_CORRECTNESS  = CONFIRMED_17496_BARS_DEVELOPMENT_WINDOW
N0_3_COST_ACCOUNTING              = STRICT_7BPS_PER_LEG_14BPS_ROUND_TRIP
N0_3_HARD_RISK_ON_HOLD            = ENFORCED_OUTSIDE_MODEL_RISK_FORCED_ACTIVE
N0_3_SOFT_HARD_GATE_PARITY        = RESOLVED_ZERO_DISPARITY_HORIZON_FORMULATION

N0_3_12H_24H_SCHEDULE_DIAGNOSTIC  = PHASE_SENSITIVE_RANGE_MINUS_1460_TO_PLUS_1948
N0_3_TIMING_VALUE                 = NEGATIVE_EXCESS_TIMING_VS_MATCHED_BENCHMARK
N0_3_GATE_COLLAPSE_DIAGNOSTIC     = PROVEN_PENALTY_INDUCED_GATE_SUPPRESSION
N0_3_PORTFOLIO_EXPOSURE_CONTROL   = LEARNED_CASH_ALLOCATION_AVERAGED_26_PERCENT
N0_3_NET_ECONOMIC_VALUE           = NEGATIVE_486_USD_EXCESS_PnL_AFTER_FRICTION

N0_3_MODEL_DISPOSITION            = REJECTED_FOR_PRODUCTION_CANDIDACY
N1_RESEARCH_DIRECTION             = STRUCTURAL_DERIVATIVES_REGIME_CONDITIONING
PROSPECTIVE_COLLECTOR             = STOPPED
REAL_TRADING                      = DISABLED
================================================================================
```

---

## 2. Phase A — Material Correctness Audits

### A1. Training Window Bar Count
- An audit of `MultiAssetDataPipeline.build_aligned_dataset()` confirmed:
  - Total aligned dataset: **26,255 hourly bars**
  - Train set (`2023-01-02 23:00` to `2024-12-31 23:00`): **17,496 bars**
  - Causal purge window (`2025-01-01 00:00` to `2025-01-02 23:00`): **48 bars**
  - Validation set (`2025-01-03 00:00` to `2025-12-31 22:00`): **8,711 bars**
- The "14,544" figure in the N0 text does not match the current pipeline. Where it came from was not reconstructed, and an earlier version of this report gave an explanation ("obsolete relic") that was a guess. The N0.2 and N0.3 training runs in this repository used all 17,496 bars; this was verified by re-running the split.

### A2. Portfolio Simplex Vector
- Verified that the portfolio state is a 6-dimensional simplex $\Delta^5$:
  - Index 0: **Cash** (deterministic $1.0$ price relative, zero risk)
  - Index 1: `BTCUSDT`
  - Index 2: `ETHUSDT`
  - Index 3: `SOLUSDT`
  - Index 4: `BNBUSDT`
  - Index 5: `DOGEUSDT`

### A3. Hard-Risk Enforcement on Voluntary HOLD
- Previously, an explicit `is_hold_seq` flag bypassed barrier checks, which could theoretically allow an asset whose price surged to exceed the 35% concentration cap indefinitely.
- **Audited and Fixed**: `NeuralPortfolioSimulator.simulate()` now inspects drifted weights on every bar. If cash drops below `min_cash_pct` (5%) or any asset exceeds `max_asset_pct` (35%), the barrier intervenes, projects the portfolio back to compliance, logs an executed trade, and increments `risk_forced_rebalance_count`.

### A4. Cost Contract Verification
- Strictly codified:
  $$\text{cost\_per\_leg} = 5.0\text{ bps (fee)} + 1.0\text{ bps (slip)} + 1.0\text{ bps (half-spread)} = 7.0\text{ bps} \quad (0.0007)$$
  $$\text{cost\_round\_trip} = 14.0\text{ bps} \quad (0.0014)$$
- Stress scenario: 10 bps fee, 2 bps slip, 2 bps half-spread = 14.0 bps/leg = 28.0 bps round-trip ($0.0028$).

---

## 3. Phase B — Audit of 12h/24h Cadence & Starting-Phase Sensitivity

In N0.2, running a frozen N0.1 TCN on an arbitrary 12-hour cadence at 00:00 UTC yielded +$2,424.75.
To determine if this was genuine timing alpha or an overfitted artifact of starting at midnight UTC, we evaluated all 12 starting offsets (00:00 to 11:00 UTC) across the full 8,711 bars of 2025.

### Results Across All 12 Starting UTC Hours:

| Offset | Start UTC Hour | Net PnL ($) | Return (%) | Sharpe | MaxDD (%) | Friction ($) | Trades | Turnover | Avg Cash |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| 0 | 00:00 | +$1,521.77 | +7.61% | +0.43 | 18.33% | $1,215.41 | 3,560 | 86.1x | 83.0% |
| 1 | 01:00 | +$1,383.35 | +6.92% | +0.41 | 16.35% | $1,222.20 | 3,563 | 86.4x | 83.0% |
| **2** | **02:00** | **-$1,405.24** | **-7.03%** | **-0.20** | **17.79%** | **$1,101.16** | **3,576** | **83.9x** | **82.6%** |
| **3** | **03:00** | **-$1,460.82** | **-7.30%** | **-0.21** | **14.96%** | **$1,143.64** | **3,570** | **85.9x** | **82.1%** |
| **4** | **04:00** | **-$1,315.92** | **-6.58%** | **-0.15** | **16.38%** | **$1,196.39** | **3,589** | **88.6x** | **81.4%** |
| 5 | 05:00 | -$45.92 | -0.23% | +0.12 | 17.04% | $1,246.84 | 3,581 | 89.0x | 81.6% |
| 6 | 06:00 | +$1,201.99 | +6.01% | +0.36 | 16.79% | $1,298.78 | 3,575 | 89.7x | 81.8% |
| 7 | 07:00 | +$1,948.32 | +9.74% | +0.51 | 16.87% | $1,285.57 | 3,567 | 89.3x | 81.9% |
| 8 | 08:00 | +$1,071.09 | +5.36% | +0.34 | 18.48% | $1,199.29 | 3,573 | 86.8x | 82.1% |
| 9 | 09:00 | +$1,904.23 | +9.52% | +0.50 | 16.20% | $1,213.10 | 3,581 | 84.2x | 82.4% |
| 10 | 10:00 | +$1,196.07 | +5.98% | +0.37 | 16.41% | $1,170.42 | 3,579 | 82.9x | 82.7% |
| 11 | 11:00 | +$1,232.52 | +6.16% | +0.37 | 18.41% | $1,200.97 | 3,570 | 84.7x | 83.1% |

### Key Diagnostic Findings:
- **Severe Phase Disparity**: A shift of merely 2 hours in the rebalancing clock turned a +$1,521 gain into a -$1,405 loss (a **$2,927 swing**!).
- **Session-alignment explanation (unverified)**: An earlier version of this report attributed the phase dependence to crypto trading-session opens. That was a conjecture; no session-level analysis was performed. The only supported finding is that results depend strongly on the starting hour.
- **Model-identity caveat**: The cadence diagnostic **retrained** the N0.1 TCN (seed 42) rather than loading frozen weights. At offset 0 it produced +\$1,521.77, not the +\$2,424.75 reported in N0.2, which shows run-to-run nondeterminism on CPU. That nondeterminism adds variance on top of the phase sensitivity.
- **Scientific Conclusion**: Fixed clock schedules create illusory, brittle alpha depending on arbitrary hour choice. Cadence cannot simply be fixed by picking 00:00 UTC.

---

## 4. Phase C — Root-Cause Investigation of Stateful Policy Collapse

In Phase N0.2, `StatefulCostAwarePolicy` exhibited a 99.53% hold decision rate and underperformed matched cash by -$1,792.41.
Our investigation uncovered:

### C1. Gate Probability Collapse
Across all 8,711 steps in 2025:
- **Median Gate Probability**: $0.00566$ (0.57%)
- **75th Percentile**: $0.02688$ (2.69%)
- **Bars with $g_t < 0.05$**: **7,151 / 8,711 (82.1%)**
- **Bars with $g_t \ge 0.50$**: **98 / 8,711 (1.13%)**

### C2. Penalty-Driven Gradient Collapse
During training rollouts ($L=64$):
$$\mathcal{L} = -\text{Sharpe} + \lambda_{\text{churn}} \cdot \bar{g} + \lambda_{\text{turnover}} \cdot \bar{\tau} + \lambda_{\text{downside}} \cdot \text{SemiVar}$$
- The loss function penalized non-zero gate values with $\lambda_{\text{churn}} = 0.50$ and $\lambda_{\text{turnover}} = 0.80$.
- Because the network had soft relaxation in training:
  $$w_t^{\text{eff}} = (1 - g_t) \cdot w_t^{\text{drifted}} + g_t \cdot w_t^{\text{cand}}$$
  The optimizer discovered that driving $g_t \to 0$ instantly eliminated both the churn penalty and the turnover penalty with zero friction cost.
- Consequently, the model never learned that the HOLD action had economic value; it was simply pushed into a permanent HOLD state by regularization pressure.
- At evaluation time, applying a hard threshold $g_t \ge 0.50$ produced a massive train/evaluation disparity. The model remained stuck in its initial allocations, carrying 87.7% crypto exposure through a bear market.

---

## 5. Phase D & E — Horizon-Aware Policy Design (N0.3)

To resolve the root causes identified in Phases A–C, we designed the **`HorizonAwarePolicy`** (`neural_trading/models/horizon_policy.py`) and **`HorizonDifferentiableLoss`** (`neural_trading/objectives/horizon_loss.py`):

1. **Decoupled Observation vs Execution**:
   - Market observation frequency: 1 hour (48-bar lookback, 4 return channels: 1h, 4h, 12h, 24h).
   - Portfolio execution cadence: $H = 12$ hours.
   - Rebalance filter: Only executed if candidate turnover exceeds a 5% deadband ($\Delta w \ge 0.05$).
2. **Explicit Cash Allocation in Action Space**:
   - Index 0 represents Cash, with a learnable preference logit $\theta_{\text{cash}}$.
   - When market return forecasts are negative or volatile, the policy allocates directly to Cash.
3. **Exact Training/Evaluation Parity**:
   - No soft-gating relaxation.
   - The model is trained directly on compound $H$-hour price relatives:
     $$y_{t \to t+H, i} = \prod_{\tau=0}^{H-1} y_{t+\tau, i}$$
   - The loss evaluates the exact net Sharpe over the holding horizon after deducting friction:
     $$\mathcal{L} = -\text{Sharpe}(R_{t \to t+H}^{\text{net}}) + \lambda_{\text{downside}} \cdot \text{SemiVariance} + \lambda_{\text{turnover}} \cdot \bar{\tau}$$
   - No artificial churn penalty. The model is free to rebalance whenever the expected horizon return exceeds the transaction friction.

---

## 6. Phase F — Bounded Experiment & Scorecards

### Baseline Scenario (14 bps Round-Trip Cost)

Decision steps: 8,711 hourly bars (2025-01-03 to 2025-12-31). Initial capital: \$20,000.00.

| Strategy / Baseline | Net PnL ($) | Total Return | Ann. Sharpe | Max DD | Ann. Turnover | Friction ($) | Trades | Hold Rate | Risk Forced |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **100% Cash** | \$0.00 | 0.00% | 0.00 | 0.00% | 0.0x | \$0.00 | 0 | 100.0% | 0 |
| **True Buy & Hold** | -\$4,023.98 | -20.12% | -0.11 | 47.79% | 1.0x | \$13.30 | 5 | 100.0% | 0 |
| **Hourly EW Rebalance** | -\$4,451.41 | -22.26% | -0.12 | 49.10% | 21.7x | \$276.62 | 39,283 | 0.0% | 0 |
| **Matched Cash (26.4%)** | -\$3,117.14 | -15.59% | -0.19 | 37.86% | 0.7x | \$10.30 | 5 | 100.0% | 0 |
| **Stateless TCN (N0.1)** | -\$1,720.27 | -8.60% | -0.16 | 26.79% | 129.1x | \$1,705.48 | 41,031 | 0.0% | 0 |
| **Stateful Policy (N0.2)** | -\$5,508.21 | -27.54% | -0.20 | 48.26% | 11.4x | \$135.78 | 205 | 99.5% | 0 |
| **Horizon-Aware (N0.3)** | **-\$3,603.64** | **-18.02%** | **-0.18** | **41.02%** | **38.9x** | **\$490.70** | **2,516** | **94.2%** | **3** |

### Stress Scenario (28 bps Round-Trip Cost)

| Strategy / Baseline | Net PnL ($) | Total Return | Ann. Sharpe | Max DD | Ann. Turnover | Friction ($) | Trades | Hold Rate | Risk Forced |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Matched Cash (26.4%)** | -\$3,125.84 | -15.63% | -0.19 | 37.86% | 0.7x | \$20.60 | 5 | 100.0% | 0 |
| **Horizon-Aware (N0.3)** | **-\$4,041.89** | **-20.21%** | **-0.23** | **41.42%** | **38.9x** | **\$967.91** | **2,516** | **94.2%** | **3** |

---

## 7. Economic Attribution & Value Decomposition

```text
================================================================================
PHASE N0.3 ECONOMIC ATTRIBUTION AUDIT (CORRECTED IN N1 PHASE A)
================================================================================
Neural gross PnL       = -3112.94
Passive gross PnL      = -3106.84
Gross excess           = -6.10

Neural friction        = 490.70
Passive friction       = 10.30
Incremental friction   = 480.40

Net excess             = -486.50
--------------------------------------------------------------------------------
Horizon-Aware Net PnL (14 bps RT)          : -3603.64
Matched Cash Benchmark Net PnL (14 bps RT) : -3117.14
Annualized Turnover                        : 38.9x (Trades: 2,516)
Hold Decision Rate                         : 94.2%
Risk-Forced Rebalance Count                : 3
Average Cash Allocation                    : 26.4% (Risky Exposure: 73.6%)
Net Improvement vs N0.2 Stateful Policy    : +1904.57
Net Delta vs N0.1 Stateless TCN            : -1883.37
Disposition                                : REJECTED_FOR_PRODUCTION_CANDIDACY
================================================================================
```

### Analysis:
1. **Turnover & Architecture Health**:
   - The Horizon-Aware policy operated healthily: it held on 94.2% of hourly bars, rebalancing only when due and outside the 5% deadband.
   - Turnover was controlled at **38.9x/year**, paying \$490.70 in total friction (compared to \$1,705.48 for Stateless TCN).
   - During severe market drift, the external hard-risk barrier intervened **3 times** to re-establish required minimum cash reserves.
2. **Comparison with N0.2**:
   - The Horizon-Aware policy improved over the collapsed N0.2 Stateful policy by **+\$1,904.57** (from -\$5,508.21 to -\$3,603.64). By actively holding 26.4% cash and rebalancing dynamically, it avoided the catastrophic drawdown of N0.2.
3. **Comparison with Matched Cash (The Scientific Hurdle)** — *corrected in N1 Phase A*:

   | Component | Neural (N0.3) | Passive matched | Difference |
   | :--- | ---: | ---: | ---: |
   | Gross PnL (net PnL + friction) | -\$3,112.94 | -\$3,106.84 | **-\$6.10** |
   | Friction | \$490.70 | \$10.30 | **\$480.40** incremental |
   | Net PnL | -\$3,603.64 | -\$3,117.14 | **-\$486.50** |

   - The earlier text compared the neural *gross* PnL (-\$3,112.94) with the passive *net* PnL (-\$3,117.14) and reported a "+\$4.20" gross edge. That comparison mixed gross and net and was wrong. Gross-to-gross, the neural policy was **\$6.10 worse** than passive; incremental friction of \$480.40 accounts for the remaining gap: -\$6.10 − \$480.40 = -\$486.50.
   - Note on the benchmark: the matched benchmark was set to the policy's 26.4% average cash at entry, but because it drifts without rebalancing its realised average cash was 29.06%. The exposure match is therefore approximate.
4. **Verdict**: **`NEURAL_POLICY_NEGATIVE_NET_VALUE`**. Gross excess versus the exposure-matched passive portfolio was slightly negative (-\$6.10, statistically indistinguishable from zero on a single path), so the turnover added cost without measurable timing or selection value. Disposition remains `REJECTED_FOR_PRODUCTION_CANDIDACY`; N0.3 is closed and was not retrained.

---

## 8. Phase G — Data Expansion Decision & Root Cause Analysis

### The Empirical Reality of Spot Price History
Across Phases N0, N0.1, N0.2, and N0.3, four distinct neural paradigms were evaluated on identical canonical Binance Spot data:
1. *TCN-DPA Stateless Hourly*: Churned at 367x/year, losing \$4,428 in fees.
2. *GRU Stateless Hourly*: Churned similarly with higher drawdown.
3. *Stateful Gating Rollouts*: Suffered penalty-induced gate collapse, holding 88% crypto through a bear market.
4. *Horizon-Aware Cadence*: Controlled turnover to 38.9x, but showed no excess return over matched cash (-\$6.10 gross, -\$486.50 net; corrected in N1 Phase A).

### Root-Cause Assessment (bounded claim, revised in N1 Phase A):
The evidence supports a narrow conclusion only: **the specific input set used in N0–N0.3** (four trailing close-to-close return channels — 1h/4h/12h/24h — over a 48-hour lookback on five Binance Spot USDT pairs) **did not give these small neural policies any measurable gross timing or selection edge on the 2025 path** once exposure was matched. This does **not** show that Spot OHLCV data has no predictive value. Untested Spot-derived information includes traded volume, taker (aggressor) buy volume, trade counts, intrabar range/volatility structure, longer lookbacks, and cross-asset relative features. Evidence is also limited to one adaptive evaluation year (2025) that was reused across several research iterations, so it cannot rule out an edge in other regimes.

### Data Expansion Policy for Next Phase (N1):
To break out of the zero-alpha trap, any future neural exploration must transition to **Structural Context Inputs**:
1. **Perpetual Futures Derivatives Context**:
   - Funding rate differentials ($S_{\text{perp}} - S_{\text{spot}}$).
   - Aggregate open interest dynamics and liquidation heatmaps.
2. **Order-Book Liquidity & Cross-Venue Imbalances**:
   - Depth skew and trade flow toxicity.
3. **Macro / Economic Calendar Features**:
   - Point-in-time interest rate announcements and stablecoin supply flows.

*Rule of Invariance*: No legacy HMR-V4A features or unapproved heuristics may be repackaged into neural training. Any new data must be crawled independently from verifiable raw sources with immutable SHA-256 manifests.

---

## 9. Governance & Operational Constraints

- **Prospective Collector**: `STOPPED`
- **Real Trading**: `DISABLED` (`real_orders = False`)
- **Frozen M5 Candidate**: `vol_aware_mean_reversion_v1` remains permanently marked `HISTORICAL_OOS_REJECTED_FOR_PROMOTION`.
- **2026 Holdout Data**: Strict isolation maintained (unopened, unread, burned).
- **Git State**: Zero commits, pushes, or merges performed without explicit user instructions.
