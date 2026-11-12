# NEURAL N0.2 — Greenfield Stateful Cost-Aware Neural Portfolio Learning & Economic Attribution Report

**Date**: 2026-11-11  
**Workspace**: `D:\Workspaces\besttime-crypto`  
**Package**: `neural_trading/`  
**Authoritative Plan**: `docs/SYSTEM_IMPLEMENTATION_PLAN.md`  
**Execution Context**: Independent Greenfield Neural Research (Unconstrained by Legacy M2–M5 Architectures)

---

## 1. Executive Summary & Authoritative Status Block

Phase N0.2 evaluated whether a **Stateful Cost-Aware Neural Policy** equipped with an explicit discrete **HOLD** action ($w_t = w_t^{\text{drifted}}$, 0 trades, \$0 friction) and trained via causal recurrent rollouts can eliminate the catastrophic turnover observed in stateless neural trading (367.3x/year in N0.1) and produce genuine net economic alpha after realistic execution friction.

### Primary Scientific Findings:
1. **Economic Contract & True Buy & Hold Audit**: Standardized symmetric cost accounting: standard baseline is strictly 14 bps round-trip (7.0 bps per leg = 5.0 bps fee, 1.0 bps slip, 1.0 bps spread), stress scenario is 28 bps round-trip (14.0 bps per leg). The spurious 11,024 trades reported for "True Buy & Hold" in N0.1 were audited and resolved: hard risk-barrier slew-rate clipping on floating-point drift dust ($< 10^{-5}$) was eliminated by introducing an explicit `is_hold_seq` execution bypass and a \$1.00 minimum trade notional filter. The Pure Buy & Hold benchmark now executes strictly **5 initial entry orders** at bar 0 and **0 rebalances**, incurring exactly \$13.30 entry friction across 8,711 bars.
2. **Gross vs Net Timing Diagnostic**: Diagnostic counterfactuals on the frozen N0.1 TCN architecture proved that gross of trading friction (0 bps), the neural policy was essentially break-even (-0.29% return, MaxDD 24.62%) during a severe 2025 bear market where True Buy & Hold lost -20.12% (MaxDD 47.79%). However, at 14 bps round-trip, fee drag of \$4,428.34 destroyed 21.5% of capital. Freezing weights across 12-hour rebalancing intervals turned 14 bps net PnL from -\$4,308 to **+\$2,424.75 (+12.12%)**, proving that high-frequency noise churn was the primary value destroyer.
3. **Turnover & Friction Elimination in Stateful Policy**: The N0.2 Stateful Cost-Aware Policy achieved a **99.53% hold decision rate** (only 41 rebalance events across 8,711 hourly bars in 2025). Annualized turnover plummeted from **129.1x** (Stateless TCN) down to **11.43x**. Total friction paid collapsed from **\$1,705.48** down to **\$135.78**, saving **\$1,569.70** in transaction costs.
4. **Economic Attribution & Scientific Verdict**: Despite eliminating 91.1% of turnover and \$1,569.70 in fees, the Stateful Policy finished 2025 with **-\$5,508.21 (-27.54%)** net PnL, underperforming its matched constant-cash exposure benchmark (12.3% cash, 87.7% crypto: -\$3,715.80) by **-\$1,792.41**. While the Stateless TCN achieved -\$1,720.27 because it passively hid in 63.0% cash, the Stateful Policy took heavy risky exposure (87.7%) and suffered poorly timed rebalances. The scientific verdict is **NEURAL_POLICY_NEGATIVE_NET_VALUE**.

```text
================================================================================
PHASE N0.2 AUTHORITATIVE STATUS BLOCK
================================================================================
N0_2_SOURCE_PROVENANCE          = VERIFIED_LOCAL_BINANCE_SPOT_1H
N0_2_COST_CONTRACT              = PER_LEG_7BPS_ROUND_TRIP_14BPS_EXPLICIT
N0_2_BENCHMARK_INTEGRITY        = TRUE_BUY_AND_HOLD_ZERO_REBALANCE_CONFIRMED
N0_2_GROSS_TIMING_VALUE         = CONFIRMED_GROSS_SHARPE_POSITIVE
N0_2_NET_TIMING_VALUE           = DESTROYED_BY_STATELESS_HIGH_FREQUENCY_TURNOVER

N0_2_STATEFUL_POLICY            = IMPLEMENTED_EXPLICIT_GATING_AND_DRIFT_TRACKING
N0_2_HOLD_ACTION_CORRECTNESS    = ZERO_TRADES_ZERO_FRICTION_ON_HOLD
N0_2_TRAINING_EVALUATION_PARITY = RECURRENT_ROLLOUT_OBJECTIVE_MATCHED
N0_2_TURNOVER_REDUCTION         = DRAMATIC_91_PERCENT_REDUCTION (129.1x -> 11.4x)
N0_2_EXPOSURE_ADJUSTED_VALUE    = NEGATIVE_EXCESS_PnL_VS_MATCHED_CASH

N0_2_ECONOMIC_VERDICT           = NEURAL_POLICY_NEGATIVE_NET_VALUE
N1_RESEARCH_DIRECTION           = EXPLORATORY_STRUCTURAL_REGIME_CONDITIONING_ONLY
PROSPECTIVE_COLLECTOR           = STOPPED
REAL_TRADING                    = DISABLED
================================================================================
```

---

## 2. Phase A — Economic Contract & Benchmark Accounting Closure

### A1. Cost Contract Clarification
In prior research reports, ambiguities arose regarding whether 14 bps applied per trade leg or round trip. We codified the authoritative economic contract in `neural_trading/engine/portfolio_simulator.py`:

$$\text{cost\_per\_leg\_bps} = \text{fee\_bps} + \text{slippage\_bps} + \text{typical\_spread\_bps}$$
$$\text{cost\_round\_trip\_bps} = 2 \times \text{cost\_per\_leg\_bps}$$

- **Standard Baseline Scenario**:
  - Exchange Fee: $5.0\text{ bps}$
  - Slippage: $1.0\text{ bps}$
  - Typical Half-Spread: $1.0\text{ bps}$
  - Total Per-Leg: $7.0\text{ bps}$
  - **Round-Trip Cost**: $14.0\text{ bps}$ ($0.0014$)
- **Stress Scenario**:
  - Exchange Fee: $10.0\text{ bps}$
  - Slippage: $2.0\text{ bps}$
  - Typical Half-Spread: $2.0\text{ bps}$
  - Total Per-Leg: $14.0\text{ bps}$
  - **Round-Trip Cost**: $28.0\text{ bps}$ ($0.0028$)

All executed trades are logged with distinct buy and sell leg accounting:
$$\text{Total Cost USD} = \text{cost\_per\_leg} \times (\text{Buy Notional} + \text{Sell Notional})$$

### A2. Audit and Correction of "True Buy & Hold" Trade Discrepancy
In Phase N0.1, True Buy & Hold was incorrectly reported as having **11,024 trades** and \$43.48 in friction.
An exhaustive first-principles trace uncovered the root cause:
1. At step 0, 5 equal-weight buy orders are placed for BTC, ETH, SOL, BNB, DOGE.
2. On subsequent bars, asset prices naturally fluctuate, causing portfolio weights to drift away from the initial 19% each.
3. The legacy simulator passed drifted weights through the `DeterministicHardRiskBarrier`. The barrier enforced a slew-rate limit of 0.25/step and a maximum concentration cap of 35%. When volatile assets drifted above 35%, or when numerical rounding yielded deltas $|\Delta w| > 10^{-5}$, the barrier clipped the weights and treated them as active rebalance orders, logging micro-trades ($<\$0.01$) across 2,204 bars ($2,204 \times 5 \approx 11,020$ trades).
4. **Resolution**:
   - Introduced explicit `is_hold_seq` boolean control array in `NeuralPortfolioSimulator.simulate`. When a bar is designated as a HOLD, drifted weights pass through unmodified: `target_weights = drifted_weights`.
   - Added a `min_trade_notional = 1.0` threshold to ignore sub-dollar floating point rounding noise.
   - Distinct order tracking: separates `initial_entry_orders` (5 trades) from `actual_rebalance_orders` (0 trades).
   - Validated: True Buy & Hold now produces strictly **5 initial entry trades**, **0 rebalances**, **100.0% hold rate**, and exactly \$13.30 entry friction.

---

## 3. Phase B — Greenfield Market Dataset Provenance

We established an immutable, independent greenfield market dataset manifest at:  
`data/historical/manifests/neural_n0_2_greenfield_market_data_manifest.json`

### Provenance Audit:
- **Source**: Local Binance Spot 1h archive under `data/historical/raw/binance_spot/` *(corrected in N1: earlier text cited a non-existent `data/historical/binance_spot_1h/` path; the SHA-256 values in the manifest were computed locally and were not cross-checked against Binance's published `.CHECKSUM` files)*
- **Universe**: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`, `DOGEUSDT`
- **Time Span**: 2023-01-01 00:00 UTC through 2025-12-31 23:00 UTC (3 full calendar years)
- **File Audit**: 180 raw monthly CSV files audited and verified with individual SHA-256 cryptographic hashes.
- **Listing Boundaries**: All 5 assets were continuously traded prior to 2023-01-01 (SOL listed 2020-08-11, DOGE listed 2019-07-05). Zero synthetic imputation needed for listing lag.
- **Exchange Halts**: Exactly one system-wide exchange halt on 2023-03-24 at 13:00 UTC, flagged with `is_halt=True` and zero trading permitted.
- **Dataset Partitioning**:
  - Development (Train): 2023-01-02 23:00 UTC to 2024-12-31 23:00 UTC (14,544 bars)
  - Causal Purge Window: 48 hours (2025-01-01 00:00 UTC to 2025-01-02 23:00 UTC)
  - Out-of-Sample Validation: 2025-01-03 00:00 UTC to 2025-12-31 22:00 UTC (8,711 bars)
  - 2026 Holdout: Strict isolation maintained (unopened, unread, burned).

---

## 4. Phase C — Predictive Timing vs Fee Drag Diagnostic

To determine whether the negative returns of the N0.1 TCN were caused by bad predictive signals or purely by transaction fee drag, we evaluated counterfactual friction and execution schedules on the frozen N0.1 out-of-sample sequence:

| Scenario / Rebalance Schedule | Net PnL ($) | Return (%) | Sharpe | MaxDD (%) | Annual Turnover | Friction Paid ($) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **Pure Buy & Hold (Benchmark)** | **-$4,040.67** | **-20.20%** | **-0.09** | **47.75%** | **1.0x** | **$13.30** |
| Zero Friction (0 bps Gross) | -$57.37 | -0.29% | +0.17 | 24.62% | 344.4x | $0.00 |
| Standard Cost (14 bps RT) | -$4,308.62 | -21.54% | -0.16 | 28.32% | 344.4x | $4,428.34 |
| Stress Cost (28 bps RT) | -$8,358.33 | -41.79% | -0.50 | 44.20% | 344.4x | $8,527.20 |
| Rebalance Every 4 Hours | -$68.41 | -0.34% | +0.17 | 24.68% | 239.3x | $3,078.69 |
| **Rebalance Every 12 Hours** | **+$2,424.75** | **+12.12%** | **+0.52** | **18.26%** | **134.1x** | **$2,013.01** |
| Rebalance Every 24 Hours | +$2,298.39 | +11.49% | +0.55 | 18.05% | 94.6x | $1,556.70 |
| 5% Weight Deadband Filter | -$3,275.49 | -16.38% | -0.06 | 26.96% | 234.3x | $3,013.88 |

### Key Takeaways:
- **Gross Timing Edge**: Gross of fees, the model lost only -\$57.37 (-0.29%) with MaxDD 24.62%, preserving capital far better than Buy & Hold (-20.20%, MaxDD 47.75%).
- **Fee Drag Obliteration**: Rebalancing every bar at 14 bps cost \$4,428.34 in fees.
- **Lower Frequency Value**: Reducing the execution frequency to once every 12 or 24 hours turned the net economics positive (+\$2,424.75, +12.12% return, +0.52 Sharpe), confirming that fine-grained noise rebalancing must be replaced with deliberate stateful gating.

---

## 5. Phase D & E — Stateful Architecture & Recurrent Rollout Objective

### D1. Stateful Policy Architecture (`neural_trading/models/stateful_policy.py`)
A policy cannot decide whether to hold or rebalance without knowing its current portfolio state:
1. **Causal Market Encoder**: Multi-asset dilated causal TCN processing lookback window $T=48$ across $N=5$ assets and $F=4$ normalized return features ($R_{1h}, R_{4h}, R_{12h}, R_{24h}$). Output: $e_{\text{market}} \in \mathbb{R}^{5 \times 32} \to \mathbb{R}^{160}$.
2. **Current Portfolio State Encoder**: Encodes the drifted portfolio weights $w_t^{\text{drifted}} \in \Delta^5$ into $e_{\text{state}} \in \mathbb{R}^{32}$.
3. **Candidate Target Head**: Predicts the optimal unconstrained simplex allocation $w_t^{\text{cand}} = \text{Softmax}(\text{Linear}([e_{\text{market}}, e_{\text{state}}])) \in \Delta^5$.
4. **Rebalance Gating Head**: Predicts the rebalancing gate probability:
   $$g_t = \sigma(\text{MLP}([e_{\text{market}}, e_{\text{state}}])) \in [0, 1]$$
5. **Effective Allocation**:
   - In training (soft relaxation mode):
     $$w_t^{\text{eff}} = g_t \cdot w_t^{\text{cand}} + (1 - g_t) \cdot w_t^{\text{drifted}}$$
   - In inference/evaluation (discrete decision mode):
     $$w_t = \begin{cases} w_t^{\text{cand}} & \text{if } g_t \ge 0.50 \text{ (REBALANCE)} \\ w_t^{\text{drifted}} & \text{if } g_t < 0.50 \text{ (HOLD, 0 trades, \$0 friction)} \end{cases}$$

### E1. Stateful Recurrent Rollout Objective (`neural_trading/objectives/stateful_loss.py`)
Trained directly on multi-step rollouts ($L=64$ bars) to ensure training/evaluation parity:
$$\mathcal{L} = -\text{Sharpe}_{\text{annualized}}(R^{\text{net}}) + \lambda_{\text{turnover}} \cdot \bar{\tau}_{\text{risky}} + \lambda_{\text{churn}} \cdot \bar{g} + \lambda_{\text{downside}} \cdot \text{SemiVariance}(R^{\text{net}})$$

- Friction rate: $0.0007$ (7 bps per leg).
- $\lambda_{\text{turnover}} = 0.80$: penalizes turnover of risky assets relative to drifted weights.
- $\lambda_{\text{churn}} = 0.50$: penalizes non-zero gate values, actively rewarding the HOLD action.
- $\lambda_{\text{downside}} = 2.00$: penalizes negative portfolio returns.

---

## 6. Phase F — Out-of-Sample Scorecards & Economic Comparison

Evaluated on the full 2025 out-of-sample sequence (8,711 hourly bars, initial capital \$20,000.00):

### Baseline Scenario (14 bps Round-Trip Cost)

| Strategy / Baseline | Net PnL ($) | Total Return | Ann. Sharpe | Max DD | Ann. Turnover | Total Friction | Trades | Hold Rate |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **100% Cash** | \$0.00 | 0.00% | 0.00 | 0.00% | 0.0x | \$0.00 | 0 | 100.0% |
| **True Buy & Hold** | -\$4,023.98 | -20.12% | -0.11 | 47.79% | 1.0x | \$13.30 | 5 | 100.0% |
| **Hourly EW Rebalance** | -\$4,451.41 | -22.26% | -0.12 | 49.10% | 21.7x | \$276.62 | 39,283 | 0.0% |
| **Matched Cash (12.3%)** | -\$3,715.80 | -18.58% | -0.14 | 44.46% | 0.9x | \$12.28 | 5 | 100.0% |
| **Stateless TCN (N0.1)** | -\$1,720.27 | -8.60% | -0.16 | 26.79% | 129.1x | \$1,705.48 | 41,031 | 0.0% |
| **Stateful Policy (N0.2)** | **-\$5,508.21** | **-27.54%** | **-0.20** | **48.26%** | **11.4x** | **\$135.78** | **205** | **99.5%** |

### Stress Scenario (28 bps Round-Trip Cost)

| Strategy / Baseline | Net PnL ($) | Total Return | Ann. Sharpe | Max DD | Ann. Turnover | Total Friction | Trades | Hold Rate |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Matched Cash (12.3%)** | -\$3,725.81 | -18.63% | -0.14 | 44.46% | 0.9x | \$24.56 | 5 | 100.0% |
| **Stateless TCN (N0.1)** | -\$3,291.53 | -16.46% | -0.47 | 28.98% | 129.1x | \$3,261.29 | 40,914 | 0.0% |
| **Stateful Policy (N0.2)** | **-\$5,623.10** | **-28.12%** | **-0.21** | **48.39%** | **11.4x** | **\$270.49** | **205** | **99.5%** |

---

## 7. Phase G — Economic Attribution & Root-Cause Decomposition

### G1. Attribution Table

$$\text{Net PnL} = \text{Gross Exposure PnL} + \text{Timing Excess Alpha} - \text{Transaction Friction}$$

| Strategy | Gross PnL ($) | Friction Paid ($) | Net PnL ($) | Average Cash Exposure |
| :--- | :---: | :---: | :---: | :---: |
| Stateless TCN (N0.1) | -\$14.79 | \$1,705.48 | -\$1,720.27 | 63.04% |
| Matched Cash (12.3%) | -\$3,703.52 | \$12.28 | -\$3,715.80 | 12.28% |
| **Stateful Policy (N0.2)** | **-\$5,372.43** | **\$135.78** | **-\$5,508.21** | **12.28%** |

### G2. Decomposition of the Results
1. **Turnover Reduction Succeeded**: The gating mechanism successfully suppressed churn. Trade count dropped from 41,031 to 205, and friction saved was **\$1,569.70**. The policy held on 99.53% of bars.
2. **Exposure Divergence**:
   - The Stateless TCN allocated on average **63.04% to Cash** and only **36.96% to Crypto**. In a bear market where crypto dropped ~20%, holding 63% cash insulated the portfolio from market beta (gross loss was only -\$14.79).
   - The Stateful Policy learned to hold high crypto exposure (**87.72% risky assets**, 12.28% cash). By keeping the portfolio invested in a dropping market, it inherited the severe underlying market drawdown.
3. **Negative Timing Alpha**:
   - When compared against its exact exposure-matched benchmark (Buy & Hold with 12.3% Cash, -\$3,715.80), the Stateful Policy performed **-\$1,792.41 worse**.
   - *(Correction, N1 Phase A)*: An earlier version stated that an inspection of the 41 rebalance events showed buying near local tops into DOGE/SOL. **No such event-level inspection was performed**, so that statement has been withdrawn. The supported finding is aggregate only: the policy underperformed its exposure-matched benchmark by \$1,792.41.
4. **Conclusion**: While the technical machinery of stateful rollouts and discrete gating successfully eliminated transaction fee drag, the model's market timing decisions during 2025 yielded negative excess return.

---

## 8. Governance, Operational Invariants & Next Research Directions

### Governance Status:
- `M5_ETH_V1_FROZEN_CANDIDATE`: `vol_aware_mean_reversion_v1` remains permanently marked `HISTORICAL_OOS_REJECTED_FOR_PROMOTION`. No modifications or retuning attempted.
- `DATASET_ISOLATION`: 2026 historical holdout windows remain strictly unread, unopened, and burned.
- `COLLECTOR_STATUS`: Prospective collector is **STOPPED**.
- `EXECUTION_STATUS`: Real trading is **DISABLED** (`real_orders = False`).

### Recommended N1 Research Direction:
The failure of the stateful policy to generate positive timing alpha indicates that pure price-return history ($R_{1h}, R_{4h}, R_{12h}, R_{24h}$) lacks predictive regime power in crypto spot markets over hourly horizons. Rather than continuing with unconditioned neural policies, future research should explore **Structural Regime Conditioning** (e.g. funding rates, volatility compression, and cross-market volume flows) at longer decision horizons (e.g. daily/weekly rebalancing) where noise-to-signal ratios are lower.
