# S3-P0.1 — Pre-Registered Research Blueprint: Portfolio-Aware Cost-Aware Unified Neural Allocation with Learned Inaction

**Repository:** `https://github.com/jarm237/besttime-crypto`
**Research Workstream:** S3 — Unified Multi-Asset Neural Allocation
**Phase:** P0.1 — Bounded Research Design Correction (Causal MVO, Exact Accounting, Temporal Neural Architecture & Scientific Gates)
**Target Research Branch:** `research/s3-portfolio-aware-allocation-blueprint`
**Starting Baseline Checkpoint:** `916877a9b79c5a6a9944513f2a92f156a938cef2`
**Prior Verified Release Checkpoint:** `2c658fe031fa7b3366fe1aa4b044eeeff3fb3bcb` (S2-A Release)
**Author:** Principal Quantitative Researcher & Financial Simulation Architect
**Status:** SPECIFIED_REVIEWED (Pre-registered design specification only; strictly NO neural training, NO backtesting, NO code implementation in P0/P0.1)

---

## 1. Research Objective & Falsifiable Hypotheses

### 1.1. Core Objective
The strategic objective of `besttime-crypto` is to design, validate, and evaluate **ONE unified multi-asset neural trading policy** capable of learning joint cross-asset capital allocation across crypto assets (`BTC`, `ETH`, `SOL`, `BNB`) and cash (`USDT`), explicitly accounting for spot trading frictions and internal portfolio state.

This blueprint establishes a pre-registered, falsifiable research specification addressing the empirical failure modes documented in prior in-repo studies:
- **S2-A Churn Failure:** Static and momentum heuristics (D/E/F) produced catastrophic execution churn (\$11,382.36 in base trading fees, 250x annual turnover) because decision rules lacked state-aware transaction cost anticipation.
- **N0.2 Paralysis Trap:** An hourly stateful neural policy collapsed into an extreme inaction trap (99.53% HOLD rate, -\$5,508.21 net PnL, -27.54% return) because a naive turnover loss penalty punished trading without rewarding necessary capital reallocation.
- **Unified Neural Pilot Cash Trap:** A weekly stateless MLP allocated an average of 89.4% to cash to minimize variance, completely missing the 2024 bull run (+12.07% vs BTC +120.31%).

### 1.2. Falsifiable Hypotheses
> **Central S3 Hypothesis:** A single portfolio-aware neural allocation policy, conditioned on multi-horizon temporal market dynamics and decision-observable portfolio state, trained through a causally valid net-of-cost portfolio transition with an explicit learned inaction gate, can exploit nonlinear market–portfolio interactions and produce incremental economic value beyond passive benchmarks and a cost-aware convex optimization baseline.

To ensure strict falsifiability and prevent post-hoc rationalization, this central hypothesis is partitioned into three testable sub-hypotheses:

* **H1 (Economic Inaction):** The policy learns to trigger the exact HOLD state ($g_t = 0$) when the expected forward economic edge of rebalancing does not exceed transaction frictions, avoiding both high-frequency churn and extreme paralysis.
* **H2 (Portfolio State Responsiveness):** Conditioned on identical market state $M_t$, the policy produces measurably distinct target allocations, trade gates, or executed rebalancing when initialized with distinct portfolio states $H_t$ (e.g., 100% Cash vs 50/50 BTC/Cash vs 25% Equal-Weight).
* **H3 (Nonlinear Incremental Economic Value):** The neural policy produces positive net-of-cost excess returns and a higher Sharpe ratio relative to both passive controls and a rebalancing-matched, cost-aware convex optimizer (MVO-L1) under 12 bps base and 30 bps stress transaction costs.

*Scientific Boundary:* S3-P0.1 establishes design novelty and causal specifications only. It does **not** assert that neural alpha exists or that the proposed mechanisms are guaranteed to outperform classical baselines.

---

## 2. Previous Neural Research & Novelty Comparison

### 2.1. Empirical Evidence from Prior In-Repo Neural Studies
1. **N0.2 Stateful Cost-Aware Policy (`data/historical/quality_reports/neural_trading_n0_2_pilot_results.json`):**
   - Evaluated over 8,711 hourly decisions across 5 assets (BTC, ETH, SOL, BNB, DOGE).
   - Achieved a 99.53% HOLD rate and reduced turnover from 129.1x to 11.4x, saving \$1,569.70 in nominal friction.
   - However, net return was **-27.54%** (underperformed matched cash by -\$1,792.41, net PnL -\$5,508.21), receiving verdict `NEURAL_POLICY_NEGATIVE_NET_VALUE`. The model learned paralysis rather than timely rebalancing.
2. **First Unified Neural Pilot (`research/unified_neural_discovery/unified_neural_pilot_report.md`):**
   - Weekly decision cadence on 4 assets (BTC, ETH, SOL, BNB) + cash.
   - Stateless MLP with a dedicated cash head.
   - Reused holdout (2025–2026) return was -0.52%, while Validation 2024 return was **+12.07%** (severely lagging BTC +120.31%) due to excessive risk aversion (average cash allocation: **89.4%**).
3. **S2-A Heuristic Opportunity Screen (`research/s2a_cross_asset/s2a_source_fidelity_closure.md`):**
   - Daily and weekly rebalancing without transaction cost awareness.
   - Static rules D/E/F suffered 250x turnover and \$11,382.36 in fees, proving that non-cost-aware rebalancing destroys crypto portfolio value.

### 2.2. Mechanical Novelty Matrix

| Dimension | N0.2 (Hourly Stateful) | Previous Unified Pilot (Weekly MLP) | S3-P0.1 Proposed Blueprint | Material Novelty Classification |
| :--- | :--- | :--- | :--- | :--- |
| **Model Input** | Hourly OHLCV + raw holdings [5 assets] | 8 summary market features [4 assets] | True temporal sequence $[B, T, N, F_{market}]$ + scale-invariant portfolio state $[B, F_{portfolio}]$ | Design Novelty: Temporal sequence + normalized state |
| **Portfolio Awareness** | Raw dollar holdings & cash fed into RNN | NONE (stateless market input only) | Explicit normalized portfolio state: $w_t^{obs}$, drift $\delta_t$, friction ratio $\rho_t$ | Design Novelty: Scale-invariant state representation |
| **Action Space** | Continuous target weights with deadband | Continuous $(N+1)$ simplex vector | Factored action space: target proposal $w_t^{prop} \in \Delta^{N+1}$ + discrete trade gate $g_t \in \{0, 1\}$ | Design Novelty: Factored continuous/discrete policy |
| **Exact HOLD** | Heuristic deadband (99.53% hold) | NONE (rebalanced every weekly step) | Exact executable HOLD: $g_t = 0 \implies \text{orders} = 0, \text{notional} = \$0, \text{fees} = \$0, q_{i,t+1} = q_{i,t}$ | Specification Novelty: Rigorous zero-friction freeze |
| **Cost Objective** | Linear turnover penalty in loss | Linear turnover penalty ($\lambda_{TO} = 0.002$) | Self-financing net log return $g_t^{net} = \log(V_{t+1}^{post}/V_t^{post})$ via fixed-point accounting | Methodological Novelty: Exact cost deduction in simulation |
| **Downside Objective** | Quadratic return variance penalty | Negative Sortino ratio on total trajectory | Dual downside: absolute downside $\mathcal{D}_{abs}$ + active relative downside $\mathcal{D}_{act}$ | Untested Hypothesis: Policy-dependent rally penalty |
| **Execution Lag** | Hourly instantaneous (0-lag) | Weekly instantaneous (0-lag) | Daily cadence with 1-hour operational lag: Decision 00:05 UTC, Execution 01:00 UTC Open | Causal Novelty: Realistic operational buffer |
| **Convex Benchmark** | None (Matched Cash, 100% Cash, B&H) | None (BTC B&H, CARM canonical) | Causal Cost-Aware MVO-L1 with decision-observable weights | Benchmark Novelty: Information-parity convex control |
| **Cadence** | 1 Hour (high churn risk) | 168 Hours (slow response) | 24 Hours (daily rebalancing decision) | Alignment with daily macro liquidity cycles |

*Distinction:* All novelty in S3-P0.1 is classified as **DESIGN NOVELTY**. Economic superiority remains entirely unproven until empirical evaluation.

---

## 3. Research Universe, Temporal Data & Strict PIT Contract

### 3.1. Asset Universe
- **Trading Assets ($N=4$):** `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT` (Binance Spot).
- **Cash Asset:** `USDT` (annualized risk-free return = 0.0%, borrow rate = 0.0%).
- **Trading Mandate:** Long-only spot assets, zero unbacked leverage, zero naked shorting.
- **Initial Portfolio Capital:** \$10,000.00.

### 3.2. Strict Causal Timeline & Execution Lag
To eliminate zero-latency lookahead, S3 enforces an explicit **1-hour operational buffer**:

```text
[Day t 00:00 - 23:00 UTC] -> Hourly trading bars accumulate
[Day t 23:00 - 00:00 UTC] -> Final hourly candle of Day t completes
[Day t+1 00:00:00 UTC]   -> Candle closes; market day t is formally complete
[Day t+1 00:00 - 00:05 UTC] -> Data ingestion & calendar-aligned feature generation
[Day t+1 00:05:00 UTC]   -> DECISION TIMESTAMP (t_dec = 00:05:00 UTC)
                            Observable state: M_t (features up to 00:00:00 UTC)
                            Portfolio state: w_t^obs (valued at 00:00:00 Close)
                            Policy emits: (w_t^prop, g_t)
[Day t+1 00:05 - 01:00 UTC] -> Order staging, pre-trade risk checks, network buffer
[Day t+1 01:00:00 UTC]   -> EXECUTION TIMESTAMP (t_exec = 01:00:00 UTC)
                            Pre-trade state: w_t^exec (valued at 01:00:00 Open)
                            Orders execute at 01:00:00 Open price P_t^exec
[Day t+1 01:00 - 23:59 UTC] -> Hourly mark-to-market valuation
```

*Causal Invariants:*
1. $t_{feature\_cutoff} \le t_{decision} < t_{execution} \le t_{valuation}$.
2. Neither the neural policy nor the MVO-L1 baseline has access to the 00:00–01:00 UTC hourly bar or the 01:00:00 Open execution price at decision time ($t_{decision} = \text{00:05:00 UTC}$).
3. Execution prices are strictly out-of-sample relative to the decision state.

### 3.3. True Calendar Timestamp Alignment
- All multi-hour returns ($\Delta t \in \{24\text{h}, 72\text{h}, 168\text{h}, 720\text{h}\}$) must align with calendar timestamps $t - \Delta t$.
- In the event of exchange halts (e.g., Binance halt on 2023-03-24 13:00 UTC), missing hours must be masked with explicit `availability_mask = 0`, rather than shifting row indices across calendar time.

---

## 4. Market & Portfolio State Representation

### 4.1. Separation of Observable and Execution States

#### A. Decision-Observable Portfolio State ($H_t^{obs}$ at $t_{dec} = \text{00:05 UTC}$)
At decision time $t_{dec}$, the agent observes its portfolio valued at the latest closed hourly bar price ($P_{i,t}^{obs} = \text{Close price of 23:00--00:00 UTC bar}$):
\[
V_t^{obs} = C_{t^-} + \sum_{j=1}^N q_{j,t^-} P_{j,t}^{obs}
\]
\[
w_{i,t}^{obs} = \frac{q_{i,t^-} P_{i,t}^{obs}}{V_t^{obs}}, \quad w_{cash,t}^{obs} = \frac{C_{t^-}}{V_t^{obs}} = 1.0 - \sum_{i=1}^N w_{i,t}^{obs}
\]
Where $q_{i,t^-}$ and $C_{t^-}$ are physical holdings carried over from prior steps.

#### B. Execution Pre-Trade State ($\tilde{w}_t^{exec}$ at $t_{exec} = \text{01:00 UTC}$)
At execution time $t_{exec}$, before orders execute, the portfolio value has drifted to:
\[
A_{i,t} = q_{i,t^-} P_{i,t}^{exec}
\]
\[
V_t^{pre} = C_{t^-} + \sum_{i=1}^N A_{i,t}
\]
\[
\tilde{w}_{i,t}^{exec} = \frac{A_{i,t}}{V_t^{pre}}, \quad \tilde{w}_{cash,t}^{exec} = \frac{C_{t^-}}{V_t^{pre}}
\]
*Fundamental Principle:* $\tilde{w}_t^{exec}$ is an execution-time realization. It must **never** be used inside the decision-time optimization objective of either the neural policy or the MVO-L1 baseline.

### 4.2. Scale-Invariant Portfolio State Vector ($H_t$)
To ensure generalization across arbitrary account equity sizes, $H_t \in \mathbb{R}^{F_{portfolio}}$ contains only scale-invariant metrics:
1. **Decision-Observable Asset Weights:** $w_{assets,t}^{obs} = [w_{BTC,t}^{obs}, w_{ETH,t}^{obs}, w_{SOL,t}^{obs}, w_{BNB,t}^{obs}] \in [0, 1]^N$.
2. **Decision-Observable Cash Weight:** $w_{cash,t}^{obs} \in [0, 1]$.
3. **Internal Portfolio Drift:** $\delta_t = \max_i |w_{i,t}^{obs} - w_{i,t-1}^{target}|$.
4. **Normalized Unrealized PnL:** $\text{uPnL}_i(t) = \text{clip}\left(\frac{P_{i,t}^{obs} - \bar{P}_{i}^{entry}}{\bar{P}_{i}^{entry}}, -1.0, 2.0\right)$.
5. **Effective Friction Ratio:** $\rho_t = c_t / \bar{\sigma}_{168h}$ (ratio of transaction fee to rolling market volatility).

---

## 5. Actual Temporal Neural Architecture

### 5.1. Temporal Modeling Principle
A stateless MLP on summary features cannot learn temporal dependencies or multi-step price formation. S3 establishes a **true temporal representation** over an observation sequence of closed hourly bars.

### 5.2. Explicit Tensor Contract
```text
Batch dimension:                   B
Temporal lookback sequence:        T (e.g., T = 168 hours = 7 calendar days)
Number of trading assets:          N = 4
Market features per asset:         F_market (e.g., returns, vol, volume ratio, mask)
Portfolio state dimension:         F_portfolio (scale-invariant state from Section 4.2)
```

**Input Tensors:**
- `market_sequence`: $[B, T, N, F_{market}]$ (strictly causally available up to 00:00:00 UTC).
- `portfolio_state`: $[B, F_{portfolio}]$ (decision-observable state $H_t^{obs}$ at 00:05:00 UTC).

**Output Tensors:**
- `proposed_weights`: $[B, N + 1]$ (continuous allocation proposal $w_t^{prop} \in \Delta^{N+1}$).
- `trade_gate_logit`: $[B, 1]$ (logit for binary trade authorization gate $g_t \in \{0, 1\}$).

### 5.3. Primary Architecture Specification
```text
Market Sequence [B, T, N, F_market]
                │
                ▼
  Shared Temporal Encoder (per asset)
   (Lightweight GRU or 1D Conv across T)
   Output: [B, N, d_temporal]
                │
                ▼
  Cross-Asset Relational Layer
   (Permutation-Equivariant Multi-Head Self-Attention)
   Output: [B, N, d_cross]
                │
                ├─────────────────────────────────────────┐
                ▼                                         ▼
   Cross-Asset Latent Vector                Portfolio State [B, F_portfolio]
      z_market ∈ R^{d_model}                              │
                │                                         │
                └───────────────────┬─────────────────────┘
                                    ▼
                          Joint State Vector
                         z_joint ∈ R^{2*d_model}
                                    │
                    ┌───────────────┴───────────────┐
                    ▼                               ▼
             Allocation Head                  Inaction Gate Head
         Linear + Joint Softmax               Linear + Sigmoid
                    │                               │
                    ▼                               ▼
       w_t^prop ∈ Δ^{N+1}                    π_gate ∈ [0, 1]
   [BTC, ETH, SOL, BNB, Cash]              g_t = I(π_gate > 0.5)
```

1. **Shared Temporal Encoder:** A single shared GRU (hidden size $d_{temporal} = 32$) processes the $T$-step sequence for each asset independently, sharing parameters across all $N$ assets to ensure parameter efficiency and prevent asset-specific overfitting.
2. **Cross-Asset Relational Layer:** A 2-head self-attention layer processes the $N=4$ asset representations, allowing dynamic modeling of cross-sectional momentum, lead-lag relationships, and relative valuations.
3. **State Fusion:** The cross-sectional market embedding is pooled and concatenated with the scale-invariant portfolio state $[B, F_{portfolio}]$, forming a joint latent representation $z_{joint}$.
4. **Dual Output Heads:**
   - *Allocation Head:* Emits an unconstrained logit vector of dimension $N+1$, converted via Softmax into a valid simplex allocation $w_t^{prop} \in \Delta^{N+1}$ where $\sum_{i=1}^N w_{i,t}^{prop} + w_{cash,t}^{prop} = 1.0$.
   - *Inaction Gate Head:* Emits a single scalar logit, converted via Sigmoid into trade authorization probability $\pi_{gate} \in [0, 1]$. In evaluation, $g_t = \mathbb{I}(\pi_{gate} > 0.5)$.

### 5.4. Parameter Budget
- Proposed design constraint: $\le 25,000$ total trainable parameters.
- Sized strictly for small-sample stability on ~700 daily Train decisions (2022–2023).
- Classified as `PROPOSED_CAPACITY_BUDGET`, not empirically validated optimal capacity. Architecture search on reused splits is strictly prohibited.

---

## 6. Exact Executable HOLD & Action Space Semantics

### 6.1. Factored Action Space
The policy network emits a single factored tuple $(w_t^{prop}, g_t)$ from a **single unified neural network**. No separate independent models are permitted.

### 6.2. Exact HOLD Semantics ($g_t = 0$)
When the learned inaction gate evaluates to $g_t = 0$:
```text
orders_submitted        = 0
executed_traded_notional = $0.00
transaction_fees_paid   = $0.00

asset_quantities_after  = asset_quantities_before (q_{i,t} = q_{i,t^-})
cash_balance_after      = cash_balance_before     (C_t = C_{t^-})
```
- Physical asset quantities remain strictly frozen.
- Asset weights and portfolio equity evolve passively through price movements.
- Zero execution slippage, zero broker commission, zero exchange friction.

### 6.3. Trade Execution Semantics ($g_t = 1$)
When $g_t = 1$, the policy submits proposed target weights $w_t^{prop}$ to the execution module:
- Orders are generated to rebalance holdings toward $w_t^{prop}$ at execution prices $P_{i,t}^{exec}$.
- If the required trade for asset $i$ does not exceed the exchange minimum notional (e.g., \$10.00 on Binance Spot), no order is submitted for that asset (`NO_EXECUTION_DUE_TO_MIN_NOTIONAL`).
- A gate value $g_t = 1$ authorizes trading; it does not force execution if economically negligible.

### 6.4. Formal Distinction of Operational Concepts
To prevent conflation in scientific reporting, five distinct operational states are formalized:
1. `TARGET_UNCHANGED`: $w_t^{prop} \approx w_{t-1}^{prop}$ within a numerical epsilon.
2. `EXACT_HOLD`: $g_t = 0 \implies \text{orders} = 0, \text{traded\_notional} = \$0, \text{fees} = \$0$.
3. `NO_EXECUTION_DUE_TO_MIN_NOTIONAL`: $g_t = 1$, but required trade notional $|V'w_i - A_i| < \text{min\_notional}$.
4. `DRIFT_RESTORATION`: $w_t^{prop} \approx w_{t-1}^{target}$, rebalancing passive price drift back to previous targets.
5. `SIGNAL_DRIVEN_REALLOCATION`: $w_t^{prop}$ materially changes target allocation weights.

### 6.5. Gate Gradient Estimation (STE)
During training, the discrete threshold $g_t \in \{0, 1\}$ is trained using the **Gumbel-Sigmoid Straight-Through Estimator (STE)**:
- Forward pass: Discrete binary decision $g_t = \mathbb{I}(\pi_{gate} > 0.5)$.
- Backward pass: Gradient computed through continuous relaxation $\sigma(\text{logit}/\tau)$.
- Temperature $\tau$ is annealed from 1.0 to 0.2 across training epochs.
- *Methodological Caveat:* STE is an approximation with biased or high-variance gradients. It provides no theoretical convergence guarantee and does not guarantee economic superiority.

---

## 7. Self-Financing Net-of-Cost Portfolio Transition

### 7.1. Exact Self-Consistent Transaction Fee Equation
Approximating transaction costs based on pre-fee equity creates accounting discrepancies, because fees directly reduce the capital available for post-trade allocation. S3 mandates the **exact self-consistent fixed-point transaction fee equation**.

Let:
- $A_{i,t} = q_{i,t^-} P_{i,t}^{exec}$ (pre-trade value of asset $i$ at execution price).
- $V_t^{pre} = C_{t^-} + \sum_{i=1}^N A_{i,t}$ (pre-trade total portfolio equity).
- $TC_t$ be the total transaction fee paid.
- $V_t^{post} = V_t^{pre} - TC_t$ (post-trade portfolio equity).
- $w_i = w_{i,t}^{prop}$ (target weight for asset $i$).

The actual traded notional for asset $i$ is $|V_t^{post} w_i - A_{i,t}| = |(V_t^{pre} - TC_t)w_i - A_{i,t}|$.
Therefore, the total transaction fee must satisfy:
\[
\boxed{TC_t = c_t \sum_{i=1}^N \left| (V_t^{pre} - TC_t) w_i - A_{i,t} \right|}
\]
Where $c_t$ is the proportional fee rate.

*Convergence Guarantee:* Because $c_t \sum_{i=1}^N w_i \le c_t < 1$ (with $c_t \in [0.0012, 0.0030]$), the right-hand side is a strict contraction mapping with Lipschitz constant $L \le c_t \ll 1$. A standard fixed-point iteration:
\[
TC^{(k+1)} = c_t \sum_{i=1}^N \left| (V_t^{pre} - TC^{(k)}) w_i - A_{i,t} \right|
\]
initialized at $TC^{(0)} = c_t \sum_i |V_t^{pre} w_i - A_{i,t}|$ converges to machine precision within 3–4 iterations.

### 7.2. Illustrative Execution Pseudocode
```python
def execute_portfolio_transition(
    cash_before: float,
    q_before: np.ndarray,          # shape: [N]
    execution_prices: np.ndarray,  # shape: [N]
    target_weights: np.ndarray,    # shape: [N + 1], sum == 1.0 (last element is cash)
    action_gate: int,              # 0 or 1
    fee_rate: float,               # e.g., 0.0012 (12 bps)
    min_notional: float = 10.0,
    tol: float = 1e-8,
    max_iter: int = 10,
) -> tuple[float, np.ndarray, float, float]:
    """Exact self-consistent portfolio transition."""
    A_before = q_before * execution_prices
    V_pre = cash_before + float(np.sum(A_before))

    if action_gate == 0:
        # EXACT HOLD: Zero orders, zero fees, holdings frozen
        return cash_before, q_before.copy(), 0.0, 0.0

    target_asset_w = target_weights[:len(q_before)]
    target_cash_w = target_weights[-1]

    # Fixed-point iteration for exact self-consistent fee
    fee = fee_rate * float(np.sum(np.abs(V_pre * target_asset_w - A_before)))
    for _ in range(max_iter):
        V_post = V_pre - fee
        traded_notional = float(np.sum(np.abs(V_post * target_asset_w - A_before)))
        new_fee = fee_rate * traded_notional
        if abs(new_fee - fee) < tol:
            fee = new_fee
            break
        fee = new_fee

    V_post = V_pre - fee
    assert V_post >= 0.0, "Portfolio equity cannot be negative"

    # Post-trade physical holdings
    q_after = (V_post * target_asset_w) / execution_prices
    cash_after = V_post * target_cash_w

    actual_traded_notional = float(np.sum(np.abs(q_after - q_before) * execution_prices))
    assert abs(fee - actual_traded_notional * fee_rate) < 1e-4, "Fee must equal fee_rate * actual traded notional"

    return cash_after, q_after, actual_traded_notional, fee
```

### 7.3. Exact Conservation Invariants
Every simulated transition must satisfy:
1. $V_t^{pre} \ge 0$.
2. $V_t^{post} = V_t^{pre} - TC_t$.
3. $\sum_{i=1}^N q_{i,t} P_{i,t}^{exec} + C_t = V_t^{post}$ (exact balance-sheet equality within precision $\epsilon = 10^{-6}$).
4. $C_t \ge 0$ (no negative cash balances).
5. $q_{i,t} \ge 0$ (no unbacked shorting or leverage).
6. $TC_t = c_t \times N_t^{actual}$ (fee equals fee rate times actual executed notional).
7. If $g_t = 0$: $\text{orders} = 0, N_t = 0.0, TC_t = 0.0$.

### 7.4. Cost Conventions & No Double Counting
- **Base Fee:** 12 bps ($c_t = 0.0012$).
- **Stress Fee:** 30 bps ($c_t = 0.0030$).
- *Scope of Friction:* These rates represent all-in research friction assumptions covering exchange commission, half-spread, and basic slippage.
- *Price Drift Distinction:* Price movement during the 55-minute operational window ($P_{i,t}^{obs} \to P_{i,t}^{exec}$) is market execution drift, **not** an additional fee.
- *Strict Prohibition of Double Counting:* Because $V_t^{post}$ directly subtracts $TC_t$, portfolio log returns $g_t^{net} = \log(V_{t+1}^{post}/V_t^{post})$ fully incorporate transaction costs. The training loss function must **not** penalize turnover a second time.

---

## 8. Training Objective & Cash-Trap Mitigation

### 8.1. Net-of-Cost Economic Objective
The policy is trained to maximize net-of-cost economic performance regularized by absolute and active downside risks:
\[
J(\theta) = \frac{1}{T}\sum_{t=1}^T g_t^{net}(\theta) - \lambda_{abs} \mathcal{D}_{abs}(\theta) - \lambda_{act} \mathcal{D}_{act}(\theta)
\]
Where:
1. **Net Log Return:** $g_t^{net} = \log(V_{t+1}^{post} / V_t^{post})$.
2. **Absolute Downside Penalty:**
   \[
   \mathcal{D}_{abs} = \frac{1}{T}\sum_{t=1}^T \left[\max(0, -g_t^{net})\right]^2
   \]
3. **Active Relative Downside Penalty:**
   \[
   \mathcal{D}_{act} = \frac{1}{T}\sum_{t=1}^T \left[\max(0, g_t^{bench} - g_t^{net})\right]^2
   \]

### 8.2. Active Downside: Scientific Characterization
*Theoretical Function:* Standard benchmark subtraction $\mathbb{E}[g_t^{policy} - g_t^{bench}]$ has zero gradient with respect to $g_t^{bench}$ ($\nabla_\theta \mathbb{E}[g_t^{bench}] = 0$). In contrast, $\mathcal{D}_{act}$ is policy-dependent:
- When the benchmark rallies and the policy sits in 100% Cash ($g_t^{bench} > g_t^{net} \approx 0$), $\mathcal{D}_{act} > 0$, generating a gradient penalizing inactivity during bull runs.
- When the benchmark crashes ($g_t^{bench} < 0$), holding cash yields $g_t^{net} \approx 0 > g_t^{bench}$, so $\mathcal{D}_{act} = 0$ (cash preservation is rewarded, not penalized).

*Scientific Classification:* The active downside functional is a **research hypothesis to mitigate cash-trapping**, NOT a mathematical guarantee of economic outperformance.
- It introduces a policy-dependent penalty for benchmark underperformance.
- It may discourage persistent cash allocation when the benchmark appreciates, but does not guarantee economic superiority and may induce benchmark-hugging or excess volatility during frothy rallies.
- Cash remains a valid, unconstrained allocation choice whenever market opportunities do not justify risk and trading friction.

### 8.3. Benchmark Selection for $\mathcal{D}_{act}$
- Benchmark $g_t^{bench}$ is pre-registered as the **Equal-Weight 4-Asset Buy & Hold (Policy B)** return.
- EW4 represents full broad crypto beta without single-asset dominance.
- Both policy and benchmark share the exact same causal evaluation timeline.
- Hyperparameters $\lambda_{abs}$ and $\lambda_{act}$ must be tuned strictly on Train (2022–2023).

### 8.4. Pre-Registered Loss Ablation
To evaluate whether $\mathcal{D}_{act}$ genuinely aids economic performance, a single pre-registered ablation is locked:
1. **Primary Specification:** $J(\theta) = \mathbb{E}[g_t^{net}] - \lambda_{abs} \mathcal{D}_{abs} - \lambda_{act} \mathcal{D}_{act}$.
2. **Ablation Specification:** $J_{abl}(\theta) = \mathbb{E}[g_t^{net}] - \lambda_{abs} \mathcal{D}_{abs}$ (active downside disabled, $\lambda_{act} = 0$).

---

## 9. Classical & Convex Optimization Baselines

The neural policy must be evaluated against classical controls sharing the exact same asset universe, cash asset, 12/30 bps fee schedule, and 1-hour causal execution lag.

### 9.1. Passive & Heuristic Controls
1. **100% Cash:** Risk-free baseline capital preservation ($R_{net} = 0.0\%$).
2. **BTC Buy & Hold:** Dominant single-asset market driver.
3. **Equal-Weight 4-Asset Buy & Hold:** Unrebalanced 4-asset beta control.
4. **Static 50/50 Equal-Weight:** 50% Cash / 50% EW4, rebalanced on the first calendar day of each month at 01:00 UTC Open.
5. **Low-Frequency EW4 Rebalanced:** Rebalanced monthly to equal weights at 01:00 UTC Open.

### 9.2. Causal Cost-Aware MVO-L1 (Convex Optimization Control)
At each daily decision step $t$ ($t_{dec} = \text{00:05 UTC}$), solve the causal quadratic program:
\[
\boxed{w_t^* = \arg\max_{w \in \Delta^{N+1}} \left[ \hat{\mu}_t^\top w - \gamma w^\top \hat{\Sigma}_t w - \hat{c}_t \|w_{assets} - w_{assets,t}^{obs}\|_1 \right]}
\]
Where:
- $w \in \Delta^{N+1}$: simplex vector over 4 risky assets and cash. Cash carries zero expected excess return, zero variance, and zero transaction fee.
- $w_{assets,t}^{obs}$: Decision-observable risky asset weights valued at $P_{i,t}^{obs}$ (Close of 23:00--00:00 UTC candle). **Strictly zero lookahead to 01:00 execution prices.**
- $\hat{\mu}_t$: Causal mean return vector estimated over rolling 168 hours of closed hourly bars.
- $\hat{\Sigma}_t$: Causal covariance matrix with Ledoit-Wolf shrinkage estimated over rolling 720 hours of closed hourly bars.
- $\hat{c}_t$: Decision-time estimated proportional fee rate (12 bps / 30 bps).
- $\gamma$: Risk-aversion parameter calibrated strictly on Train (2022–2023).

*Information Parity:* The neural policy and MVO-L1 observe the exact same information set up to 00:00:00 UTC. Neither model has access to future data. Both models submit allocations executed at 01:00:00 UTC Open.

*Horizon & Unit Scaling Consistency:*
```text
RETURN_ESTIMATION_FREQUENCY      = HOURLY (aggregated to daily equivalent)
FORECAST_HORIZON                 = 24 HOURS (daily rebalance horizon)
COVARIANCE_ESTIMATION_FREQUENCY  = HOURLY (scaled to 24h covariance: Σ_daily = 24 * Σ_hourly)
ANNUALIZATION_OR_HORIZON_SCALING = All terms scaled to 24h daily variance/return units
```

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

1. **Reused Data Classification:** Data from 2024–2026 have been repeatedly examined in S1, D0.1, and S2-A. They are formally classified as **REUSED_DIAGNOSTIC**, not pristine out-of-sample data.
2. **Diagnostic Evaluation Role:** Reused split results serve exclusively to falsify hypotheses. Positive performance on reused splits cannot be cited as conclusive evidence of future out-of-sample generalization.
3. **Quarantine Enforcement:** No hyperparameter tuning, model checkpoint selection, or threshold calibration is permitted on data after 2023-12-31.

---

## 11. Pre-Registered Go / No-Go Decision Gates

### 11.1. Phase P0.1 Exit (Design Correction Sign-Off)
- [x] Causal MVO-L1 formulation corrected to use decision-observable weights $w_t^{obs}$.
- [x] Exact self-consistent fixed-point transaction fee equation specified.
- [x] True temporal sequence representation $[B, T, N, F_{market}]$ and encoder defined.
- [x] Exact executable HOLD semantics ($g_t = 0 \implies \text{orders}=0, \text{notional}=\$0, \text{fees}=\$0$) formalized.
- [x] Arbitrary numerical gates ($10\% \le \text{rebalance} \le 60\%$, $\Delta w > 0.05$) replaced with validity invariants and behavioral counterfactual tests.
- [x] Active downside functional reclassified as an untested anti-cash-trap hypothesis.
- [x] Status updated to `S3_P0_DOCUMENT = CORRECTED`, `S3_P1_AUTHORIZATION = READY_FOR_SEPARATE_APPROVAL`.

### 11.2. Phase P1 Exit (Train-Only Sanity Gate — Future Phase)
Phase P1 is confined strictly to Train 2022–2023. It protects **technical and causal validity**, not proof of alpha:
1. **Mathematical Conservation Invariant:** In 100% of simulated steps, $V_t^{post} = V_t^{pre} - TC_t$, $C_t \ge 0$, and $q_{i,t} \ge 0$ within tolerance $\epsilon = 10^{-6}$.
2. **Exact Inaction Invariant:** In 100% of steps where $g_t = 0$, the simulator records exactly 0 executed orders, \$0.00 traded notional, and \$0.00 fees paid.
3. **No Lookahead Invariant:** Automated data-leak audit proves zero access to the 00:00–01:00 UTC bar or 01:00 execution prices at decision time.
4. **Behavioral Counterfactual Diagnostic:** Conditioned on identical market state $M_t$, evaluate policy outputs across distinct portfolio initializations:
   - Case A: 100% Cash ($w_{cash} = 1.0$)
   - Case B: 50% BTC / 50% Cash
   - Case C: 25% Equal-Weight across all 4 assets
   - Metric: Record proposed weights $w_t^{prop}$, action gate $g_t$, executed turnover, fees, and net return impact. Verify real portfolio-state responsiveness without imposing arbitrary hardcoded numerical cutoffs.
5. **Training Convergence:** Loss converges smoothly, gradients remain finite, and weights do not produce NaNs.
6. **Quantitative Diagnostics Reporting:** Rebalance rate, HOLD ratio, turnover, friction, and cash utilization are reported as descriptive quantitative diagnostics.

### 11.3. Phase P2 Exit (Economic Evaluation Gate — Future Phase)
If authorized, P2 evaluation on Validation 2024 must satisfy:
1. **Outperforms Static 50/50:** Net return $R_{net}^{S3} > R_{net}^{\text{Static 50/50}}$ at 12 bps base fee.
2. **Outperforms Cost-Aware MVO-L1:** Achieves higher net Sharpe ratio and positive excess return over MVO-L1.
3. **Cost Resilience:** Net excess return remains positive under 30 bps stress fee.
4. **Bootstrap Diagnostic:** 95% paired bootstrap confidence interval for daily excess returns is reported as an exploratory diagnostic (noting reused data limitations).

---

## 12. Open Risks & Explicit Technical Limitations

1. **Discrete Gating Gradients:** Training discrete gate $g_t$ via Gumbel-Sigmoid STE utilizes a biased gradient approximation that may exhibit high variance during temperature annealing.
2. **Small Sample Size:** Approximately 700 daily decision steps in Train (2022–2023) is a modest sample size for deep learning, demanding strong parameter regularization ($\le 25\text{k}$ parameters).
3. **Execution Gap Risk:** The 55-minute operational interval between decision (00:05 UTC) and execution (01:00 UTC) exposes orders to intra-hour price movement. This is intentional to ensure causal realism.
4. **Active Downside Regularization Risk:** Penalizing benchmark underperformance during market rallies may encourage benchmark-hugging or induce excessive risk-taking during speculative bubbles.
5. **Reused Data Constraint:** Evaluation splits (2024–2026) have been examined in prior cycles, limiting conclusions to exploratory falsification.

---

## 13. Pre-Registration Status & Authorization Recommendation

```text
========================================================================================
S3_P0_DOCUMENT                      = CORRECTED
S3_HYPOTHESIS                       = FALSIFIABLE
S3_CAUSAL_EXECUTION_SPEC             = SPECIFIED_NOT_IMPLEMENTED
S3_MVO_INFORMATION_SET               = CAUSALLY_SPECIFIED
S3_COST_ACCOUNTING_SPEC              = SELF_CONSISTENT_SPECIFIED
S3_TEMPORAL_ARCHITECTURE_SPEC        = DEFINED
S3_EXACT_HOLD_SPEC                   = DEFINED
S3_CASH_TRAP_MITIGATION              = HYPOTHESIS_UNTESTED
S3_NEURAL_ECONOMIC_INCREMENTAL_VALUE = NOT_ESTABLISHED

S3_P1_AUTHORIZATION                  = READY_FOR_SEPARATE_APPROVAL
S3_P1_IMPLEMENTATION                 = NOT_STARTED (Hard Stop Enforced)
S3_P2_EVALUATION                     = NOT_STARTED
PRODUCTION_PROMOTION                 = NOT_AUTHORIZED
========================================================================================
```

*Final Review Note:* `READY_FOR_SEPARATE_APPROVAL` certifies that all mathematical, causal, accounting, architectural, and evaluation specifications have been corrected, verified for internal consistency, and pre-registered. It does **not** grant authorization to begin code implementation, simulator changes, or model training in this task.
