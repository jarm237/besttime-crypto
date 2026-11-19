# S5-P0 Pre-Execution Contract Erratum & Technical Addendum

- **Document Version:** 1.0.0
- **Status:** `FROZEN_ADDENDUM`
- **Repository:** `https://github.com/jarm237/besttime-crypto`
- **Branch:** `research/s5-p0-economic-opportunity`
- **Governing Pre-Registration Commit:** `b894fc53de0e2b50720828c1ab72d2d774d5fcbb`
- **Date (UTC):** 2026-11-19
- **Scope:** Technical clarifications, accounting invariants, and gate definitions locked prior to 2022–2023 replay execution.

---

## 1. Motivation & Scope

This document serves as an authoritative, binding technical addendum to the frozen pre-registration specification (`research/s5_economic_opportunity/s5_p0_executable_preregistration.md`).

To preserve the epistemic integrity of the research process, the v1.0 pre-registration remains unmodified in its original committed form. This erratum formalizes six technical and accounting corrections identified during pre-execution code auditing to guarantee that the subsequent economic replay is mathematically conserved, free of candle-timestamp leakage, and evaluated against unambiguous quantitative gates.

---

## 2. Technical Addenda & Contract Corrections

### A1. Fee-Aware Portfolio Accounting & Capital Conservation Invariant

#### Defect in Simplified Pre-Fee Allocation
In naive portfolio accounting, target notionals are calculated from pre-fee equity: $N_i^{\text{target}} = w_i \cdot V_{\text{pre}}$, and fees are deducted from cash post-hoc: $C_{\text{post}} = C_{\text{pre}} - \sum \Delta N_i - \text{Fee}$. When a portfolio transitions into a $100\%$ crypto target (e.g. $w_{\text{BTC}} = 1.0, w_{\text{cash}} = 0.0$), this causes cash to become negative ($-c \cdot V_{\text{pre}}$) or requires borrowing, violating the long-only cash conservation invariant.

#### Corrected Fixed-Point Post-Fee Formulation
To ensure non-negative cash balances, non-negative token holdings, and exact capital conservation without leverage or credit, target notionals must be derived from the unique **post-fee equity** $V_{\text{post}}$.

Given:
- Pre-trade total equity: $V_{\text{pre}} = C_{\text{pre}} + \sum_{i=1}^4 h_{i,\text{current}} \cdot P_{i,\text{exec}}$
- Pre-trade current asset notionals: $N_i = h_{i,\text{current}} \cdot P_{i,\text{exec}}$
- Target weights: $\mathbf{w} = [w_1, w_2, w_3, w_4]^T$, $w_{\text{cash}} = 1 - \sum_{i=1}^4 w_i \ge 0$
- Proportional one-way fee rate: $c$ (e.g. $0.0012$ for 12 bps)

The post-fee equity $V_{\text{post}}$ is the unique root of the continuous, piecewise-linear, strictly increasing function:

$$f(V) = V + c \sum_{i=1}^4 |w_i V - N_i| - V_{\text{pre}} = 0$$

#### Analytical Properties & Solution
Because $c \ge 0$ and $w_i \ge 0$, the derivative almost everywhere is:

$$f'(V) = 1 + c \sum_{i=1}^4 w_i \operatorname{sgn}(w_i V - N_i) \ge 1 - c(1 - w_{\text{cash}}) > 0 \quad (\text{for } c < 1)$$

Thus $f(V) = 0$ possesses an exact, unique solution $V_{\text{post}} \in [\frac{V_{\text{pre}}}{1 + 2c}, V_{\text{pre}}]$.

Upon finding $V_{\text{post}}$:
1. Target asset notionals:
   $$N_i^{\text{target}} = w_i \cdot V_{\text{post}}$$
2. Physical token units after execution:
   $$h_{i,\text{post}} = \frac{N_i^{\text{target}}}{P_{i,\text{exec}}} = \frac{w_i \cdot V_{\text{post}}}{P_{i,\text{exec}}} \ge 0$$
3. Realized transaction fee:
   $$\text{Fee} = c \sum_{i=1}^4 |N_i^{\text{target}} - N_i| = V_{\text{pre}} - V_{\text{post}}$$
4. Cash balance after execution:
   $$C_{\text{post}} = w_{\text{cash}} \cdot V_{\text{post}} \ge 0$$

#### Accounting Invariant Guarantees
- **Non-negative balances:** Cash balance $C_{\text{post}} \ge 0$ and all token holdings $h_{i,\text{post}} \ge 0$ at all times.
- **Initial entry fee:** When entering $100\%$ crypto from $100\%$ cash ($N_i = 0$), $V_{\text{post}} = \frac{V_{\text{pre}}}{1 + c}$, and $N^{\text{target}} = \frac{V_{\text{pre}}}{1 + c}$. The fee $c \cdot N^{\text{target}}$ is paid from cash, leaving exactly $C_{\text{post}} = 0$.
- **Sell-before-buy execution:** Liquidating overweight positions generates cash before purchasing underweight positions.
- **Zero money creation:** $V_{\text{post}} + \text{Fee} \equiv V_{\text{pre}}$ holds to floating-point precision ($< 10^{-12}$).

---

### A2. Causal Binance Candle Semantics & Timestamp Alignment

#### Binance Kline Timestamping Convention
Binance Spot 1h archive timestamps represent the **Open time of the candle**, not its close time:
- A candle timestamped `2023-01-01 00:00:00 UTC` begins at `00:00:00` and closes at `00:59:59.999 UTC`.
- Therefore, at the decision feature cutoff $t = \text{00:00:00 UTC}$, the candle timestamped `t 00:00:00` is **currently open and actively trading**. Using its Close price or High/Low at 00:00:00 UTC constitutes lookahead leakage.

#### Strict Causal Selection Rule
1. **Latest Available Closed Candle:** At feature cutoff $t \text{ 00:00 UTC}$, the most recent completed candle is the bar timestamped **$t - 1\text{ hour}$** (`23:00 UTC` of the previous calendar date).
2. **168-Hour Momentum Lookback:**
   The 168-hour trailing momentum is computed across the 168 strictly completed hourly bars:
   $$\text{Mom}_{i,t} = \ln\left(P_{i, t-1\text{h}}^{\text{close}}\right) - \ln\left(P_{i, t-169\text{h}}^{\text{close}}\right)$$
   where $P_{i, t-1\text{h}}^{\text{close}}$ is the Close price of the candle timestamped $t - 1\text{h}$ (closing at $t \text{ 00:00 UTC}$), and $P_{i, t-169\text{h}}^{\text{close}}$ is the Close price of the candle timestamped $t - 169\text{h}$ (closing at $t - 168\text{h} \text{ 00:00 UTC}$).
3. **Execution Price:** Target weight rebalancing at execution time $t \text{ 01:00 UTC}$ executes at the Open price of the candle timestamped **$t \text{ 01:00 UTC}$** (which is identical to the Close price of the candle timestamped $t \text{ 00:00 UTC}$). This guarantees a 1-hour real-time operational buffer between decision formation ($00:05$ UTC) and fill execution ($01:00$ UTC).

---

### A3. Quantitative Economic Gate Specification When BTC CAGR $\le 0$

#### Context of the 2022–2023 Development Population
During the 2022 bear market, Bitcoin declined from $\approx \$47,700$ to $\approx \$16,500$ ($-65.4\%$). Despite the 2023 recovery to $\approx \$42,000$, Bitcoin's annualized compound growth rate over the full two-year 2022–2023 development window is negative or marginally near zero ($\text{CAGR}_{\text{BTC}} \approx -6.2\%/\text{year}$).

#### Formal Fallback Gate Specification
When evaluating across a window where $\text{CAGR}_{\text{BTC}} \le 0$:
1. **Condition 1 (Growth Retention):** The pre-registered condition $\text{CAGR}_{\text{POLICY}} \ge 0.75 \times \text{CAGR}_{\text{BTC}}$ is mathematically uninformative (since 75% of a negative rate would reward worse performance). It is officially designated **`NOT_APPLICABLE`**.
2. **Active Fallback Gate Criteria:**
   A candidate policy qualifies for consideration if and only if it satisfies all of the following:
   - **(a) Absolute Capital Preservation or Substantial Outperformance:**
     $$V_T > V_0 \quad (\text{Net Positive Compounding}) \quad \mathbf{OR} \quad \text{CAGR}_{\text{POLICY}} - \text{CAGR}_{\text{BTC}} \ge +15.0\% / \text{year}$$
   - **(b) Drawdown Compression:**
     $$|\text{MaxDD}_{\text{POLICY}}| \le 0.65 \times |\text{MaxDD}_{\text{BTC}}|$$
     *(Peak-to-trough drawdown must not exceed 65% of Bitcoin's maximum drawdown over the same period).*
   - **(c) Risk-Adjusted Return Superiority:**
     $$\text{Calmar}_{\text{POLICY}} > \text{Calmar}_{\text{BTC}}$$
     *(Where Calmar is defined as $\text{CAGR} / |\text{MaxDD}|$, with $\text{MaxDD} > 0$.)*
   - **(d) Active Policy Qualification (No Free Pass for Cash):**
     Passive pure cash (`CASH_100`) achieves $V_T = V_0$ and $\text{MaxDD} = 0\%$, but cannot be an `ECONOMIC_OPPORTUNITY_CANDIDATE` for neural allocation because it provides zero crypto market participation ($g_t \equiv 0$). An eligible policy must have an average crypto exposure $\bar{g}_t \ge 0.15$ to be eligible for neural policy candidacy.

---

### A4. Consistent 20 bps Stress Gate Evaluation

The 20 bps sensitivity test evaluates whether the **primary economic objective** (drawdown-controlled compounding) remains resilient under adverse execution costs.
- The 20 bps stress test must **not** be secretly redefined into requiring higher terminal wealth than BTC Buy & Hold when the primary gate explicitly allows capturing 75% of BTC CAGR in exchange for a 35% reduction in drawdown.
- **Stress Gate Requirement:** A qualifying candidate policy must continue to satisfy conditions (b) and (c) (drawdown compression and Calmar superiority) and maintain positive terminal wealth ($V_T(20\text{ bps}) > V_0$) at $c = 20\text{ bps}$.
- Excess terminal wealth over BTC at 20 bps is reported as a descriptive diagnostic, not a disqualifying hurdle if the primary gate conditions hold.

---

### A5. Deduplication of Policy Aliases: `MOMENTUM_TOP2` vs. `CARM4_ADAPTATION`

In the 4-asset spot universe (`BTC`, `ETH`, `SOL`, `BNB`), the Cross-Asset Relative Momentum adaptation (`CARM4_ADAPTATION`) specifies ranking assets by 168h trailing momentum and selecting the Top-2 assets with equal weighting ($50\% / 50\%$) on a weekly Sunday schedule.

Because `MOMENTUM_TOP2` uses the identical indicator (168h log return), universe (4 assets), ranking rule (top 2), weighting ($50\% / 50\%$), and rebalancing cadence (weekly Sunday), both policies yield **bitwise identical target weights and execution paths**.

**Operational Rule:**
The replay engine will execute the strategy once under the canonical name `MOMENTUM_TOP2`, and scorecards will report:
`MOMENTUM_TOP2 (CARM4_ADAPTATION)`
These two designations must never be counted as two independent economic opportunities.

---

### A6. Historical Exposure Disclosures & Breakeven Solver Integrity

#### Historical Exposure Disclosure
The design of S5 was formulated after observing the results of the R5 historical replay experiments in parts of 2024–2026. Therefore, the parameter choices (168h lookback, 5% band, weekly Sunday cadence) cannot be claimed as pristine ex-ante hypotheses. They are exploratory baselines being tested on 2022–2023.

#### Breakeven Solver Robustness Protocol
The breakeven cost $c^*$ is defined by:
$$g(c) = \ln\left(\frac{V_T^{\text{POLICY}}(c)}{V_T^{\text{BENCHMARK}}(c)}\right) = 0$$

1. **Initial Edge Check:** If $g(0.0) \le 0.0$, the policy has no gross advantage over the benchmark even at zero cost. Immediately return `NO_POSITIVE_BREAKEVEN_EDGE` without searching.
2. **Boundary Crossing Check:** If $g(0.0) > 0.0$ and $g(100.0\text{ bps}) > 0.0$, the advantage persists beyond 100 bps/side. Return `NO_CROSSING_IN_RANGE` (edge $> 100\text{ bps}$).
3. **Monotonicity & Root Bracket:** When $g(0.0) > 0$ and $g(100.0\text{ bps}) < 0$, a root is bracketed in $[0, 100\text{ bps}]$. Bisection is conducted to a tolerance of $\le 0.1\text{ bps}$ ($0.00001$).
4. **Multiple Crossings:** If numerical sampling reveals non-monotonic behavior with multiple sign changes, report the lowest crossing cost and flag `MULTIPLE_CROSSINGS_DETECTED`.

---

## 3. Summary of Governed Invariants

```text
INVARIANT_1: V_post = V_pre - c * sum(|w_i * V_post - N_i|) solved exactly.
INVARIANT_2: Cash balance C_t >= 0 and token holdings h_{i,t} >= 0 for all t.
INVARIANT_3: Feature cutoff 00:00 UTC strictly accesses bars <= (t - 1h).
INVARIANT_4: Rebalance execution 01:00 UTC fills at 01:00 UTC candle open.
INVARIANT_5: When BTC CAGR <= 0, evaluate capital preservation & Calmar gain.
INVARIANT_6: MOMENTUM_TOP2 and CARM4_ADAPTATION treated as identical single policy.
INVARIANT_7: Breakeven solver fails closed if edge <= 0 at zero cost.
```
