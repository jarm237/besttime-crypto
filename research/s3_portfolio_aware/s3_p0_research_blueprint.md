# S3-P0 — Pre-Registered Research Blueprint: Portfolio-Aware Cost-Aware Unified Neural Allocation with Learned Inaction

**Repository:** `https://github.com/jarm237/besttime-crypto`
**Research Workstream:** S3 — Unified Multi-Asset Neural Allocation
**Phase:** P0 — Pre-Registered Theoretical Blueprint & Falsifiable Hypothesis
**Target Research Branch:** `research/s3-portfolio-aware-allocation-blueprint`
**Starting Checkpoint:** `d52425050b73399aa71df1f139f05a82f7ffdf9f`
**Author:** Principal Quantitative Researcher & Financial Simulation Architect
**Status:** BLUEPRINT ONLY (Strictly NO neural training, NO backtesting, NO code implementation in P0)

---

## 1. Research Objective & Falsifiable Hypotheses

### 1.1. Core Objective
The long-term mission of `besttime-crypto` is to establish **ONE unified multi-asset neural trading policy** capable of directly learning how to allocate capital across crypto assets (`BTC`, `ETH`, `SOL`, `BNB`) and cash (`USDT`), optimizing net economic performance after realistic spot trading costs.

S3-P0 defines an independent, falsifiable research hypothesis that directly addresses the empirical failure modes identified in prior research:
- **S2-A failure:** Static heuristics (D/E/F) generated catastrophic turnover ($11,382.36 base fees, 250x turnover) due to high-frequency momentum churn without cost-awareness.
- **N0.2 failure:** Stateful neural policy collapsed into an extreme inaction trap (99.53% HOLD rate, -$5,508.21 net PnL) because a naive turnover penalty penalized trading without rewarding timely portfolio restructuring.
- **Unified Pilot failure:** Stateless MLP hid in 89.4% cash to minimize variance, completely missing the 2024 bull run (+12.07% vs BTC +120.31%).

### 1.2. Falsifiable Hypotheses
> **Central S3 Hypothesis:** A single portfolio-aware neural allocation policy, trained through a causally valid net-of-cost portfolio transition with an explicit learned inaction gate, can exploit nonlinear market–portfolio interactions and produce incremental economic value beyond passive allocations and a cost-aware convex optimization baseline.

To prevent broad, unfalsifiable claims, this central hypothesis is partitioned into three independent, testable sub-hypotheses:

* **H1 (Economic Inaction):** The policy learns to trigger the exact HOLD state ($g_t = 0$) when the expected forward return of rebalancing is lower than the round-trip transaction friction, achieving a rebalance frequency significantly lower than daily churn while avoiding the 99.5% paralysis of N0.2.
* **H2 (Portfolio State Awareness):** Conditioned on the identical market feature state $M_t$, the policy generates measurably distinct target allocations when initialized with different portfolio states $H_t$ (e.g., 100% Cash vs 50/50 BTC/Cash vs 25% EW).
* **H3 (Nonlinear Incremental Value):** The neural policy produces positive net-of-cost excess returns and higher Sharpe ratio relative to a rebalancing-matched, cost-aware convex optimizer (MVO-L1) under both 12 bps base and 30 bps stress transaction costs.

---

## 2. Previous Neural Research & Novelty Comparison

### 2.1. Empirical Evidence from Prior In-Repo Neural Studies
1. **N0.2 Stateful Cost-Aware Policy (`data/historical/quality_reports/neural_trading_n0_2_pilot_results.json`):**
   - 8,711 hourly decisions across 5 assets (BTC, ETH, SOL, BNB, DOGE).
   - Achieved 99.53% HOLD rate and reduced turnover from 129.1x to 11.4x, saving $1,569.70 in friction.
   - However, net return was **-27.54%** (underperformed matched cash by -$1,792.41), resulting in `NEURAL_POLICY_NEGATIVE_NET_VALUE`. The model learned paralysis rather than intelligent timing.
2. **First Unified Neural Pilot (`research/unified_neural_discovery/unified_neural_pilot_report.md`):**
   - Weekly decision cadence on 4 assets (BTC, ETH, SOL, BNB) + cash.
   - Stateless MLP with a dedicated cash head.
   - Reused holdout (2025–2026) return was -0.52%, but Validation 2024 return was only **+12.07%** (lagging BTC +120.31%) due to excessive risk aversion (average cash: **89.4%**).

### 2.2. Mechanical Novelty Matrix

| Dimension | N0.2 (Hourly Stateful) | Previous Unified Pilot (Weekly MLP) | Proposed S3 Blueprint | Material Difference |
| :--- | :--- | :--- | :--- | :--- |
| **Model Input** | Hourly OHLCV + raw holdings [5 assets] | 8 summary market features [4 assets] | Multi-scale temporal market features + scale-invariant portfolio state | Scale-invariant portfolio state (weights, drift, cost ratio) |
| **Portfolio Awareness** | Raw dollar holdings & cash fed into RNN | NONE (stateless market input only) | Explicit normalized portfolio state: $W_t^{obs}$, drift $\delta_t$, cost ratio $c_t / \hat{\sigma}$ | True state-dependence without capital scale distortion |
| **Action Space** | Continuous target weights with deadband | Continuous $(N+1)$ simplex vector | Factored: continuous target proposal $w_t \in \Delta^N$ + discrete execution gate $g_t \in \{0, 1\}$ | Explicit learned binary decision to trade vs freeze |
| **Exact HOLD** | Implicit via heuristic deadband (99.53% hold) | NONE (rebalanced every weekly step) | Exact executable HOLD: $g_t = 0 \implies \Delta q_{i,t} = 0$, $TC_t = \$0$ | Zero executed orders, zero fees, holdings units frozen |
| **Cost Objective** | Linear turnover penalty $\lambda \sum \|\Delta w\|$ | Turnover penalty $\lambda_{TO} = 0.002$ | Net-of-cost log growth $g_t^{net} = \log(V_{t+1}^{net} / V_t^{net})$ | Costs deducted in environment transition; no artificial double-penalty |
| **Downside Objective** | Quadratic return variance penalty | Negative Sortino ratio on total trajectory | Dual downside: absolute downside $\mathcal{D}_{abs}$ + active relative downside $\mathcal{D}_{act}$ | Asymmetric active downside penalizes holding cash during market rallies |
| **Execution Timing** | Hourly instantaneous (zero-latency) | Weekly open execution (zero-latency) | Daily cadence with conservative 1-hour execution buffer | Decision at 00:05 UTC, execution at 01:00 UTC Open |
| **Baselines** | Matched Cash, 100% Cash, B&H | BTC B&H, CARM canonical | Cash, BTC B&H, EW4 B&H, Static 50/50, Cost-Aware MVO-L1 | First comparison against convex cost-aware optimizer |
| **Cadence** | 1 Hour (high churn risk) | 168 Hours (too slow for crypto shifts) | 24 Hours (daily rebalancing decision) | Aligned with daily macro liquidity cycles |

---

## 3. Research Universe, Temporal Data & Strict PIT Contract

### 3.1. Asset Universe
- **Trading Assets (N=4):** `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT` (Binance Spot).
- **Cash Asset:** `USDT` (annualized risk-free return = 0.0%, borrow rate = 0.0%).
- **Trading Mandate:** Long-only, spot assets, zero unbacked leverage, zero naked shorting.
- **Initial Portfolio Capital:** `$10,000.00`.

### 3.2. Strict Causal Timeline & Execution Lag
To eliminate the idealized zero-latency assumptions present in S2-A, S3 establishes a strictly enforced **1-hour operational buffer**:

```text
[Day t 00:00 - 23:00 UTC] -> Hourly trading data accumulates
[Day t 23:00 - 00:00 UTC] -> Final hourly candle of Day t
[Day t+1 00:00:00 UTC]   -> Candle closes; market day t is formally complete
[Day t+1 00:00 - 00:05 UTC] -> Data ingestion & calendar-aligned feature generation
[Day t+1 00:05:00 UTC]   -> DECISION TIMESTAMP (s_t^decision observed; w_t, g_t emitted)
[Day t+1 00:05 - 01:00 UTC] -> Order staging & pre-trade risk validation
[Day t+1 01:00:00 UTC]   -> EXECUTION TIMESTAMP (Orders fill at 01:00:00 Open price)
[Day t+1 01:00 - 23:59 UTC] -> Hourly MTM portfolio valuation
```

*Causal Invariants:*
1. $t_{feature\_cutoff} \le t_{decision} < t_{execution} \le t_{valuation}$.
2. The policy has **zero access** to the 00:00–01:00 UTC hourly bar or the 01:00:00 Open execution price at decision time ($t_{decision} = \text{00:05:00 UTC}$).
3. Execution prices are strictly out-of-sample relative to the decision state.

### 3.3. True Calendar Timestamp Alignment
Unlike S2-A, which used row offsets (`.shift(168)`), S3 mandates **true UTC timestamp lookbacks**:
- All multi-hour returns ($\Delta t = 24\text{h}, 72\text{h}, 168\text{h}, 720\text{h}$) must align with calendar timestamps $t - \Delta t$.
- In the event of exchange halts (such as 2023-03-24 13:00 UTC), missing hours must be masked with explicit `availability_mask = 0`, rather than shifting across calendar boundaries.

---

## 4. Market & Portfolio State Representation

### 4.1. Decision-Observable Market State ($M_t$)
Features are extracted over closed 1h bars up to 00:00:00 UTC of Day $t+1$:
1. **Multi-Horizon Returns:** $R_{i, \tau}(t) = P_{i}(t) / P_{i}(t - \tau) - 1$ for $\tau \in \{24\text{h}, 72\text{h}, 168\text{h}, 720\text{h}\}$.
2. **Realized Volatility:** $\sigma_{i, \tau}(t)$ computed on log returns over 168h and 720h (annualized).
3. **Cross-Sectional Dispersion:** $\sigma_{disp, 168h}(t) = \text{std}_i(R_{i, 168h}(t))$.
4. **Market Breadth:** $\text{Breadth}_{SMA168}(t) = \frac{1}{N}\sum_i \mathbb{I}(P_{i}(t) > \text{SMA}_{168}(P_i))$.
5. **Cross-Asset Correlation:** Mean rolling 168h correlation of 24h returns across all pairs.
6. **Data Availability Mask:** Binary flags indicating valid data feeds per asset.

### 4.2. Scale-Invariant Portfolio State ($H_t$)
To prevent the neural network from overfitting to nominal account sizes, the portfolio state is encoded in stationary, scale-invariant coordinates:
1. **Current Observed Asset Weights:** $W_t^{obs} = [w_{BTC}, w_{ETH}, w_{SOL}, w_{BNB}] \in [0, 1]^N$.
2. **Current Observed Cash Weight:** $w_{cash, t} = 1.0 - \sum_i w_i \in [0, 1]$.
3. **Internal Portfolio Drift:** $\delta_t = \max_i |w_{i, t}^{obs} - w_{i, t-1}^{target}|$.
4. **Normalized Unrealized PnL:** $\text{uPnL}_i(t) = (P_{i}(t) - \bar{P}_{i}^{entry}) / \bar{P}_{i}^{entry}$ (clipped to $[-1.0, +2.0]$).
5. **Effective Friction Ratio:** $\rho_t = c_t / \bar{\sigma}_{market, 168h}$ (ratio of transaction fee to expected volatility).

---

## 5. Unified Neural Architecture

```text
[Market Features M_t]        [Portfolio State H_t]
  (Shape: [N, F_mkt])           (Shape: [F_port])
          │                             │
          ▼                             ▼
   Asset Encoder                  State Encoder
    (Shared MLP)                   (Linear+GELU)
          │                             │
          └──────────────┬──────────────┘
                         ▼
             Cross-Asset Attention Layer
          (Permutation-Equivariant Interaction)
                         │
                         ▼
             Shared Latent Vector z_t
               (Dimension: d_model)
                         │
         ┌───────────────┴───────────────┐
         ▼                               ▼
  Allocation Head                   Inaction Gate
(Joint Softmax over N+1)       (Binary Gating Network)
         │                               │
         ▼                               ▼
Target Weights w_t ∈ Δ^N          Gate Probability π_gate ∈ [0, 1]
 [w_BTC, w_ETH, w_SOL, w_BNB, w_USDT]  g_t = I(π_gate > 0.5) (Eval)
```

### 5.1. Model Capacity & Parameter Budget
- **Model Family:** Lightweight Cross-Asset Self-Attention with dual heads.
- **Hidden Dimension ($d_{model}$):** 64.
- **Attention Heads:** 2 (capturing pairwise momentum vs relative valuation).
- **Total Parameter Budget:** $\le 25,000$ parameters (strictly sized for small-sample stability on ~700 Train daily decisions).

---

## 6. Exact Executable HOLD & Action Space Semantics

### 6.1. Factored Action Space
The policy emits a joint tuple $(w_t^{prop}, g_t)$:
- $w_t^{prop} \in \Delta^N$: Continuous proposed target weight vector ($w_i \ge 0, \sum_{i=1}^N w_i + w_{cash} = 1.0$).
- $g_t \in \{0, 1\}$: Binary trade authorization gate.

### 6.2. Exact Operational Semantics
1. **Case $g_t = 0$ (Learned Inaction / HOLD):**
   - **Order Count:** Exactly 0 orders submitted.
   - **Executed Traded Notional:** Exactly `$0.00`.
   - **Transaction Fee:** Exactly `$0.00`.
   - **Asset Quantities:** $q_{i, t+1} = q_{i, t}$ (physical units held remain frozen).
   - **Cash Balance:** $C_{t+1} = C_t$.
   - **Weights:** Passive drift allowed; weights evolve according to price changes without rebalancing friction.
2. **Case $g_t = 1$ (Trade Execution):**
   - Rebalance orders generated to shift from pre-trade holdings to $w_t^{prop}$ at execution price $P_{i, t}^{exec}$.
   - Transaction fee deducted from available cash.

### 6.3. Gate Trainability
During training, $g_t$ is relaxed using the **Gumbel-Sigmoid / Straight-Through Estimator (STE)**:
- Forward pass uses discrete thresholding $\mathbb{I}(\pi_{gate} > 0.5)$.
- Backward pass flows continuous gradients through $\sigma(\text{logit} / \tau)$.
- Temperature $\tau$ is annealed from 1.0 to 0.2 during training.

---

## 7. Self-Financing Net-of-Cost Portfolio Transition

All simulations and policy updates strictly enforce self-financing conservation:

### 7.1. Valuation at Decision Time ($t_{dec} = \text{00:05 UTC}$)
\[
V_{t}^{dec} = C_{t^-} + \sum_{i=1}^N q_{i, t^-} P_{i, t}^{dec}
\]

### 7.2. Valuation & Execution at Execution Time ($t_{exec} = \text{01:00 UTC}$)
\[
V_{t}^{pre} = C_{t^-} + \sum_{i=1}^N q_{i, t^-} P_{i, t}^{exec}
\]
Pre-trade asset weights:
\[
\tilde{w}_{i, t}^{exec} = \frac{q_{i, t^-} P_{i, t}^{exec}}{V_{t}^{pre}}
\]

If $g_t = 0$:
\[
q_{i, t} = q_{i, t^-}, \quad C_t = C_{t^-}, \quad TC_t = 0.0
\]

If $g_t = 1$:
\[
\Delta w_{i, t} = |w_{i, t}^{target} - \tilde{w}_{i, t}^{exec}|
\]
\[
N_t = V_{t}^{pre} \sum_{i=1}^N \Delta w_{i, t}
\]
\[
TC_t = c_t N_t
\]
Post-fee equity:
\[
V_{t}^{post} = V_{t}^{pre} - TC_t
\]
New physical holdings:
\[
q_{i, t} = \frac{V_{t}^{post} w_{i, t}^{target}}{P_{i, t}^{exec}}
\]
\[
C_t = V_{t}^{post} w_{cash, t}^{target}
\]

*Prohibition:* Fees are directly deducted from equity in the transition function. The loss function must **not** penalize fees a second time.

---

## 8. Training Objective & Cash-Trap Prevention

### 8.1. Mathematical Limitation of Benchmark Subtraction
A common error in quantitative ML is assuming that subtracting benchmark return $\mathbb{E}[g_t^{policy} - g_t^{bench}]$ prevents cash-trapping. Since $g_t^{bench}$ is policy-independent:
\[
\nabla_\theta \mathbb{E}[g_t^{bench}] = 0
\]
Simple benchmark subtraction does not alter the optimal gradient trajectory or discourage hiding in cash.

### 8.2. Dual Downside Regularized Objective
To prevent cash-trapping while penalizing excessive risk, S3 introduces an **Asymmetric Relative Downside Penalty**:

\[
J(\theta) = \frac{1}{T}\sum_{t=1}^T g_t^{net}(\theta) - \lambda_{abs} \mathcal{D}_{abs}(\theta) - \lambda_{act} \mathcal{D}_{act}(\theta)
\]

Where:
1. **Net Log Return:** $g_t^{net} = \log(V_{t+1}^{net} / V_t^{net})$.
2. **Absolute Downside Deviation:**
   \[
   \mathcal{D}_{abs} = \frac{1}{T}\sum_{t=1}^T \left[\max(0, -g_t^{net})\right]^2
   \]
3. **Active Relative Downside (The Anti-Cash-Trap Functional):**
   \[
   \mathcal{D}_{act} = \frac{1}{T}\sum_{t=1}^T \left[\max(0, g_t^{bench} - g_t^{net})\right]^2
   \]
   - When the market rallies and the policy sits in 100% Cash ($g_t^{net} \approx 0 < g_t^{bench}$), $\mathcal{D}_{act} > 0$, generating a steep gradient pulling the policy toward active market participation.
   - When the market crashes ($g_t^{bench} < 0$), holding cash generates $g_t^{net} \approx 0 > g_t^{bench}$, resulting in $\mathcal{D}_{act} = 0$ (cash is rewarded, not penalized).

### 8.3. Benchmark Selection for $\mathcal{D}_{act}$
- Benchmark $g_t^{bench}$ is defined as the **Equal-Weight 4-Asset Buy & Hold (Policy B)** return.
- Hyperparameters $\lambda_{abs}$ and $\lambda_{act}$ must be selected strictly within Train 2022–2023 (e.g., via cross-validation over 2022 vs 2023).

---

## 9. Classical & Convex Optimization Baselines

The neural policy must be compared against rigorous classical controls sharing the exact same universe, fee schedule, and 1-hour execution lag:

1. **100% Cash:** Baseline for risk-free capital preservation.
2. **BTC Buy & Hold:** Dominant single-asset market driver.
3. **Equal-Weight 4-Asset Buy & Hold:** Full crypto beta benchmark.
4. **Static 50/50 Equal-Weight:** Passive balanced benchmark (rebalanced monthly or at 2% buffer).
5. **Cost-Aware MVO-L1 (Convex Optimization Baseline):**
   At each daily decision step $t$, solve the convex quadratic program:
   \[
   \max_{w \in \Delta^N} \quad \hat{\mu}_t^\top w - \gamma w^\top \hat{\Sigma}_t w - c_t \|w - \tilde{w}_t^{exec}\|_1
   \]
   - $\hat{\mu}_t$: Causal rolling 168h historical mean return.
   - $\hat{\Sigma}_t$: Causal Ledoit-Wolf shrunk covariance matrix over rolling 720h.
   - $\gamma$: Risk aversion parameter calibrated strictly on Train (2022–2023).
   - $c_t$: Exact fee rate (12 bps / 30 bps).
   - Execution: Solved at 00:05 UTC, executed at 01:00 UTC Open.

*Requirement for S3 Success:* The neural policy must demonstrate incremental economic value beyond **both** Static 50/50 and MVO-L1. Beating heuristic policies (D/E/F) alone is insufficient.

---

## 10. Data Quarantine & Evaluation Protocol

```text
┌─────────────────────────────────┬────────────────────────────────┐
│   Train / Calibration Split     │    Diagnostic Reused Splits    │
│    (2022-01-01 - 2023-12-31)    │    (2024-01-01 - 2026-11-16)   │
├─────────────────────────────────┼────────────────────────────────┤
│ • Model weights training        │ • Validation 2024 (Reused)     │
│ • Hyperparameter tuning (λ)     │ • Reused Diagnostic 2025-2026  │
│ • Architecture decisions        │ • STRICT QUARANTINE:           │
│ • Loss function ablation        │   NO model selection           │
│ • MVO-L1 risk aversion γ        │   NO parameter tuning          │
│ • Train-only sanity checks      │   NO threshold adjustment      │
└─────────────────────────────────┴────────────────────────────────┘
```

1. **Data Status Transparency:**
   - 2024 and 2025–2026 data have been observed in S1, D0.1, and S2-A.
   - They are classified as **REUSED_DIAGNOSTIC**, not untouched out-of-sample data.
2. **Generalization Claim Policy:**
   - Performance on 2024–2026 can only refute a model (falsification diagnostic).
   - Definitive proof of neural generalization will require prospective out-of-sample forward collection.

---

## 11. Pre-Registered Go / No-Go Decision Gates

### 11.1. Phase P0 Exit (Blueprint Sign-Off)
- [x] Mechanical novelty over N0.2 and Unified Pilot established.
- [x] Strict 1-hour causal execution lag formalized.
- [x] Scale-invariant portfolio state defined.
- [x] Exact executable HOLD semantics formalized.
- [x] Dual downside objective with anti-cash-trap functional defined.
- [x] Cost-Aware MVO-L1 benchmark specified.
- [x] Reused data quarantine protocol declared.

### 11.2. Phase P1 Exit (Train-Only Sanity Gate — Future Phase)
Before any evaluation on 2024 data, P1 must satisfy all train-only technical gates on 2022–2023:
1. **Convergence Sanity:** Loss converges without NaN gradients; parameters remain finite.
2. **Exact Inaction Verification:** When $g_t = 0$, simulator asserts 0 executed orders, $0 traded volume, and $0 fee.
3. **Holding Rate Sanity:** Policy exhibits non-trivial rebalancing ($10\% \le \text{rebalance\_rate} \le 60\%$), avoiding both N0.2 paralysis (99.5% hold) and S2-A churn (50%+ daily rebalancing).
4. **State-Dependence Invariant:** Feeding different initial portfolio states ($H_t$) under identical market states produces statistically significant differences in action outputs ($\Delta w > 0.05$).
5. **No Lookahead Assertion:** Automated leak audit asserts zero access to $t+1$ bar or 01:00 execution prices.

### 11.3. Phase P2 Exit (Economic Evaluation Gate — Future Phase)
If authorized, P2 evaluation on Validation 2024 must satisfy:
1. **Beats Static 50/50:** Net return $R_{net}^{S3} > R_{net}^{\text{Static 50/50}}$ at 12 bps base.
2. **Beats Cost-Aware MVO-L1:** Demonstrates incremental Sharpe improvement over MVO-L1.
3. **Cost Resilience:** Net return remains positive and outperformance holds under 30 bps stress fee.
4. **Bootstrap Significance:** 95% paired bootstrap confidence interval for daily excess returns strictly excludes zero.

---

## 12. Open Risks & Explicit Technical Limitations

1. **Discrete Gating Gradients:** Training discrete gate $g_t$ via Gumbel-Sigmoid can suffer high variance or gradient bias if temperature annealing is uncalibrated.
2. **Sample Size Constraints:** 700 daily decision steps in Train (2022–2023) is a small sample for deep learning, requiring strict parameter regularization ($\le 25\text{k}$ params) and dropout.
3. **Execution Gap Risk:** In highly volatile regimes, the 55-minute gap between decision (00:05 UTC) and execution (01:00 UTC) may induce slippage relative to decision-time prices. This is intentional to ensure causal realism.

---

## 13. P1 Authorization Recommendation

```text
========================================================================================
S3_P0_STATUS               = BLUEPRINT_READY
S3_NOVELTY_AUDIT           = ESTABLISHED_DISTINCT_FROM_N02
S3_CAUSAL_CONTRACT         = VERIFIED_1H_EXECUTION_LAG
S3_P1_AUTHORIZATION        = READY_FOR_SEPARATE_APPROVAL
S3_P1_IMPLEMENTATION       = NOT_STARTED (Hard Stop Enforced)
========================================================================================
```

*Note:* `READY_FOR_SEPARATE_APPROVAL` indicates that the theoretical, mathematical, and execution contracts are fully pre-registered and ready for engineering review. It does **not** grant authorization to begin code implementation or model training in this task.
