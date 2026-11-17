# R10 Unified Neural Objective & Seed-Stability Experiment Report

**Clean Aligned Horizon**: 2022-01-16 00:00 UTC to 2026-11-16 19:00 UTC (42,379 hourly bars, 253 weekly decisions)  
**Selected Model**: Seed 202 (`r10_selected_model.pt`) | Calibrated Downside Risk Budget: 0.0282/week (20.3% ann)  
**Execution & Accounting**: Next-open execution (`open[t_dec]`) | Mark-to-market (`close[t]`) | Base: 12.0 bps | Stress: 25.0 bps  

---

## 1. Executive Scientific Verdict

### Final Verdict: **`R10_UNIFIED_NEURAL_INCREMENTAL_VALUE_NOT_SUPPORTED`**

> [!IMPORTANT]
> **Definitive Findings on the 5 Core Questions**:
> 1. **Did the new objective prevent cash-shelter collapse without an exposure floor?**: **YES**. Under the risk-budgeted objective, the selected model achieved an average cash weight of **12.1%** (risky crypto exposure: **87.9%**), compared to 94.6% cash in R8. The model actively deployed capital into crypto without requiring any artificial exposure constraint.
> 2. **Did exposure dynamically scale across regimes?**: **NO**. The model swung to the opposite extreme: rather than dynamically toggling cash between bull and bear regimes, it remained persistently high-beta (~88% crypto). While this captured **+94.21%** in the 2024 bull market, it suffered a **-63.02%** loss in 2022.
> 3. **Did R10 improve Validation economics?**: **YES on Validation 2024, but NOT across the full cycle**. On Validation 2024, R10 delivered **+94.21%** (vs R8's +9.58% and Static 50/50's +52.54%). However, across the full horizon it lost **-6.09%** (vs Static 50/50 **+43.02%** and Vol Target 25% **+58.22%**), and suffered **-44.37%** in Reused Holdout (2025–2026).
> 4. **Did the objective stabilize results across seeds?**: **YES**. Seed cash allocation range was drastically compressed from 74.7% down to **11.8%** (standard deviation dropped from 32.0% to 4.9%). Full-horizon return range fell from 180.3% down to **9.7%**.
> 5. **Cash Timing Falsification Verdict**: Against 500 temporal permutations of weekly cash allocations, R8's cash timing achieved empirical p-value **p = 0.0000** (percentile rank **100.0%**), and **p = 0.0000** against circular shifts. This confirms that R8's cash timing statistically outperformed random cash permutations on historical data, but R10 reveals that single-simplex networks struggle to simultaneously optimize dynamic cash timing and cross-sectional selection.

---

## 2. Phase B: Cash Timing Falsification Analysis

To determine whether R8's cash timing (+37.43% net) was genuine predictive skill or an artifact of exposure and macro regime, we tested the frozen cash schedule against two null distributions:

### Falsification Test Results (500 Permutations & 252 Circular Shifts)

| Metric | Original R8 Policy | Shuffled Permutation Null (Mean ± Std) | 95% Permutation CI | Empirical p-value | Circular Shift p-value |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Net Return** | **+37.46%** | +3.54% ± 8.52% | [-13.45%, +21.73%] | **p = 0.0000** (Rank: 100.0%) | **p = 0.0000** |
| **Sharpe Ratio** | **0.884** | 0.168 ± 0.315 | [-0.464, 0.794] | **p = 0.0120** (Rank: 98.8%) | **p = 0.0119** |

> [!NOTE]
> **Statistical Falsification Takeaway**: With empirical p-values of **0.0000** (temporal permutations) and **0.0000** (circular shifts), the R8 cash timing schedule statistically rejected the null hypothesis of uninformative exposure timing ($p < 0.05$). However, because R8's cash allocation averaged 94.6% throughout, this statistical advantage was primarily driven by sitting out the massive 2022 aggregate bear market rather than weekly micro-timing.

---

## 3. Phase C: Objective Diagnosis & Mathematical Root Causes

We evaluated four competing hypotheses for R8's failure:

1. **Hypothesis A — Loss Function Defense Over-Prioritization**: **CONFIRMED**.
   - At initialization, the downside semi-deviation gradient norm was **0.0364**, while the net return gradient norm was **0.00178** (a **20.44x disparity**).
   - Backpropagation prioritized suppressing downside variance over seeking positive returns.

2. **Hypothesis B — Validation Selection Distorted by Downside Ratio**: **CONFIRMED**.
   - R8 selected Seed 202 because its validation criterion was `val_net / val_down`.
   - Seed 202 achieved only +9.58% in Validation, but had near-zero downside (`val_down = 0.0020`), yielding an inflated Sortino score of 0.9112.
   - Meanwhile, Seed 42 achieved **+80.87%** in Validation, but was rejected because its crypto exposure generated `val_down = 0.026` (score 0.4303).

3. **Hypothesis C — Optimization Instability / Seed Sensitivity**: **CONFIRMED**.
   - In R8, three seeds produced three radically different regimes: Seed 42 (19.9% cash), Seed 101 (77.8% cash), and Seed 202 (94.6% cash).

4. **Hypothesis D — Lack of Cross-Sectional Predictive Information**: **SUPPORTED**.
   - Counterfactual D vs E in R9 confirmed that without cash timing, neural asset selection lagged static BTC by -0.87%.

---

## 4. Multi-Seed Stability Comparison: R8 vs R10

| Model / Seed | Full Return | Sharpe | MaxDD | Mean Cash | Train Return | Val Return | Holdout Return |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **R8 Seed 42** | -2.57% | 0.252 | -60.34% | 19.9% | -11.40% | +80.87% | -40.07% |
| **R8 Seed 101** | +177.71% | 1.084 | -23.13% | 77.8% | +125.03% | +41.76% | -13.33% |
| **R8 Seed 202** | +37.43% | 0.884 | -8.51% | 94.6% | +25.12% | +9.58% | +0.16% |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **R10 Seed 42** | -2.45% | 0.253 | -60.34% | 19.9% | -11.31% | +80.97% | -40.09% |
| **R10 Seed 101** | -12.11% | 0.255 | -66.71% | 8.1% | -17.39% | +94.37% | -46.16% |
| **R10 Seed 202 ⭐ (Selected)** | -6.09% | 0.265 | -64.66% | 12.1% | -14.43% | +94.21% | -44.37% |

- **R8 Cash Weight Range**: 74.7% (Std: 32.0%)  
- **R10 Cash Weight Range**: 11.8% (Std: 4.9%)  
- **Cash Allocation Dispersion**: Reduced by **62.9 percentage points** under the risk-budgeted objective.

---

## 5. Comprehensive Economic Scorecard (Base 12 bps & Stress 25 bps)

| Strategy / Policy | Net Return (12 bps) | Sharpe | MaxDD | Mean Cash | 2022 | 2023 | 2024 | 2025 | Stress Net (25 bps) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **R10 Risk-Budgeted Neural (Seed 202)** | **-6.09%** | 0.265 | -64.66% | 12.1% | -63.0% | +132.2% | +94.2% | -16.8% | **-7.28%** |
| **Benchmark: 100% Cash** | **+0.00%** | 0.000 | 0.00% | 100.0% | +0.0% | +0.0% | +0.0% | +0.0% | **+0.00%** |
| **Benchmark: BTC Buy & Hold** | **+50.57%** | 0.420 | -67.38% | 0.0% | -61.6% | +155.8% | +120.3% | -7.2% | **+50.37%** |
| **Benchmark: Static 50/50 BTC/Cash** | **+43.02%** | 0.423 | -40.27% | 49.9% | -34.6% | +65.4% | +52.5% | -2.1% | **+42.36%** |
| **Benchmark: Static Exp-Matched R7 (58% BTC)** | **+47.24%** | 0.422 | -45.42% | 42.0% | -39.5% | +78.1% | +62.4% | -2.7% | **+46.56%** |
| **Benchmark: Vol Target 25% (5% Buffer)** | **+58.22%** | 0.482 | -42.54% | 40.0% | -37.6% | +95.6% | +58.5% | -1.2% | **+51.53%** |
| **Benchmark: Equal-Weight 8 Coins** | **-19.20%** | 0.259 | -70.41% | 0.0% | -68.8% | +153.5% | +103.4% | -20.5% | **-20.32%** |

---

## 6. Next Research Experiment Recommendation

> [!TIP]
> **Exactly ONE Evidence-Backed Experiment**: **R11 Two-Stage Hierarchical Policy Decoupling**
> - **Empirical Basis**: Joint simplex allocation forces a single softmax across both market exposure (cash) and relative asset weights, creating destructive optimization interference between macro timing and micro selection.
> - **Prescription**: Decouple into two orthogonal heads with independent objectives:
>   1. **Head 1 (Macro Exposure)**: Predicts continuous market exposure $E(t) \in [0, 1]$ using rolling market volatility and regime features.
>   2. **Head 2 (Micro Cross-Section)**: Predicts cross-sectional relative weights $q_i(t) \in \Delta^{N-1}$ using relative momentum and dispersion.
>   Final portfolio: $w_i(t) = E(t) \cdot q_i(t)$ and $w_{\text{cash}}(t) = 1 - E(t)$.