# Scientific & Economic Verdict — Track B1 Regime-Conditioned Capital Allocation

## 1. Executive Verdict
**FINAL_ECONOMIC_VERDICT:** `B1_NO_INCREMENTAL_VALUE`  
**VS_TRACK_A:** `MIXED`  
**VS_50_50:** `MIXED`  
**VS_CONSTANT_EXPOSURE:** `MIXED`

---

## 2. Key Economic Findings Across Horizons

### 2.1 Validation Horizon (2024 — Strong Bull Market)
- **Track B1 Conditional:** Net CAGR **+72.65%**, MaxDD **-33.11%**, Calmar **2.19**, Avg Exposure **79.6%**
- **Track A v1 (Frozen):** Net CAGR **+78.05%**, MaxDD **-30.69%**, Calmar **2.54**, Avg Exposure **76.5%**
- **Constant-Mult Track A:** Net CAGR **+78.18%**, MaxDD **-30.88%**, Calmar **2.53**, Avg Exposure **77.0%**
- **Observation:** In the strong uptrend of 2024, Track B1's risk gating scaled down exposure during brief volatility surges, trailing Track A's unconstrained trend capture by -5.40% in CAGR.

### 2.2 Reused Historical Test Horizon (2025–2026 — Correction / Sideways)
- **Track B1 Conditional:** Net CAGR **-15.07%**, MaxDD **-38.64%**, Calmar **-0.39**, Avg Exposure **58.6%**
- **Track A v1 (Frozen):** Net CAGR **-19.49%**, MaxDD **-42.08%**, Calmar **-0.46**, Avg Exposure **54.6%**
- **Constant-Mult Track A:** Net CAGR **-19.36%**, MaxDD **-41.91%**, Calmar **-0.46**, Avg Exposure **54.9%**
- **Observation:** During the correction period, Track B1 reduced drawdown (-38.64% vs -42.08%) and softened losses (-15.07% vs -19.49%).

### 2.3 Full Historical Horizon (2022–2026 — Complete Cycle)
- **Track B1 Conditional:** Net CAGR **+11.64%** (PnL: $+7,119.38), MaxDD **-38.64%**, Calmar **0.30**, Fees: $1,641.52
- **Constant-Mult Track A:** Net CAGR **+9.42%** (PnL: $+5,516.82), MaxDD **-41.91%**, Calmar **0.22**, Fees: $1,044.80
- **Track A v1 (Frozen):** Net CAGR **+9.28%** (PnL: $+5,419.98), MaxDD **-42.08%**, Calmar **0.22**, Fees: $1,047.28
- **BTC 50/50 Rebalanced:** Net CAGR **+6.59%** (PnL: $+3,655.62), MaxDD **-41.04%**, Calmar **0.16**

---

## 3. In-Depth Economic Trade-Off Decomposition
1. **Sacrificed Upside vs Avoided Downside:**
   - In 2024 (bull market), Track B1 surrendered $541.90 in dollar profit compared to Track A v1 (++72.65% vs ++78.05%) due to premature risk gating.
   - In 2025–2026 (bear market), Track B1 avoided $703.22 in losses (-15.07% vs -19.49%).
   - Over the full cycle (2022–2026), Track B1 achieved higher cumulative dollar PnL ($+7,119.38 vs $+5,419.98), but required 230 trades and $1,641.52 in transaction friction (vs 63 trades and $1,047.28 for Track A v1).
2. **Validation Decision Protocol:**
   - Under the pre-registered validation protocol (Section 9), the model selection must be decided on the Validation window (2024) prior to considering retrospective tests.
   - On Validation (2024), Track B1 achieved Calmar **2.19** (inferior to Track A v1's **2.54** and Constant-Mult Track A's **2.53**) and higher Max Drawdown (**-33.11%** vs **-30.69%**).
   - Because Track B1 failed to demonstrate risk-adjusted superiority on the registered validation horizon, it fails the threshold for incremental promotion.
3. **Dynamic Timing vs Constant Multiplier:**
   - On the full cycle, the constant multiplier benchmark ($M=1.0177$) achieved Net CAGR **+9.42%** (63 trades) vs B1's **+11.64%** (230 trades).
   - The increased churn (+167 trades, +$596 in fees) was not supported by clean risk-adjusted dominance on out-of-sample validation.

---

## 4. Final Scientific Synthesis & Protocol Termination
- **Conclusion:** Track B1 exhibited regime sensitivity, softening the 2025–2026 bear drawdown (-38.64% vs -42.08%), but underperformed Track A v1 on the pre-registered Validation window (Calmar 2.19 vs 2.54). Under strict pre-registration rules, the model cannot be awarded incremental status.
- **Decision:** In accordance with research protocol constraints, no model tuning loop, B2 pilot, or Neural v2 will be opened. Track A v1 remains the primary frozen benchmark.
