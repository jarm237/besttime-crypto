# Unified Neural Pilot — Economic Falsification & Exposure-Matched Report

**Evaluation Horizon**: 2022-01-01 00:00 UTC to 2026-11-16 19:00 UTC (42,739 hourly bars, ~4.88 years)  
**Execution & Accounting Standards**: Next-bar open execution | Hourly close mark-to-market | 12.0 bps fee (stress test: 25.0 bps)  
**Purged Boundary Samples (Zero-Leakage Enforcement)**: 2 weekly decisions  
  - `2023-12-31 00:00 UTC`: Train label overflow: label_end (2024-01-07 00:00:00+00:00) > train_end (2023-12-31 23:59:59+00:00)
  - `2024-12-29 00:00 UTC`: Validation label overflow: label_end (2025-01-05 00:00:00+00:00) > val_end (2024-12-31 23:59:59+00:00)

---

## 1. Full-Horizon Comparative Scorecard (Neural vs Exposure-Matched Controls & Benchmarks)

| Strategy / Policy | Final Equity ($) | Net Return (%) | Max DD (%) | Ann. Sharpe | Ann. Sortino | Realized Cash (%) | 1-Way TO | Gross TO | Fees ($) | Traded Vol ($) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **UNIFIED_NEURAL_PILOT (Market-Only, Seed 42)** | $11,350.18 | **+13.50%** | -15.92% | 0.324 | 0.453 | 95.0% | 11.2 | 11.3 | $143.62 | $119,685.45 |
| **UNIFIED_NEURAL_PILOT (Market + Regime, Seed 42)** | $11,253.97 | **+12.54%** | -15.92% | 0.279 | 0.385 | 91.9% | 14.6 | 14.7 | $186.69 | $155,572.15 |
| **UNIFIED_NEURAL_PILOT (Cost Stress 25 bps)** | $11,184.82 | **+11.85%** | -15.92% | 0.290 | 0.406 | 95.0% | 11.2 | 11.3 | $297.00 | $118,799.12 |
| **ABLATION_NEURAL_CASH_ONLY (Neural Cash + EW Risky)** | $11,229.90 | **+12.30%** | -15.92% | 0.302 | 0.421 | 95.0% | 11.1 | 11.1 | $140.87 | $117,391.39 |
| **ABLATION_NEURAL_SELECTION_ONLY (Neural Selection + 85% Cash)** | $10,851.44 | **+8.51%** | -14.85% | 0.216 | 0.297 | 85.0% | 5.1 | 8.0 | $100.30 | $83,586.50 |
| **FALSIFICATION_RANDOM_NEURAL (Untrained Seed 42)** | $9,271.37 | **-7.29%** | -65.30% | 0.251 | 0.344 | 12.0% | 7.3 | 11.0 | $131.49 | $109,578.45 |
| **FALSIFICATION_SHUFFLED_SIGNAL (Train Shuffled Seed 42)** | $11,603.58 | **+16.04%** | -15.92% | 0.362 | 0.506 | 94.5% | 12.9 | 13.1 | $166.51 | $138,757.15 |
| **CONTROL_STATIC_85CASH_15EW (Weekly Rebal)** | $10,901.56 | **+9.02%** | -14.99% | 0.228 | 0.312 | 85.0% | 2.4 | 2.6 | $32.11 | $26,761.08 |
| **CONTROL_BTC_10_CASH_90_BnH (Static Buy&Hold)** | $10,404.06 | **+4.04%** | -12.50% | 0.160 | 0.224 | 87.9% | 0.1 | 0.1 | $1.20 | $1,000.00 |
| **CONTROL_BTC_10_CASH_90_REBAL (Weekly Rebal)** | $10,932.77 | **+9.33%** | -9.23% | 0.390 | 0.550 | 90.0% | 1.2 | 1.2 | $15.03 | $12,521.46 |
| **CONTROL_BTC_20_CASH_80_BnH (Static Buy&Hold)** | $10,808.02 | **+8.08%** | -21.78% | 0.192 | 0.269 | 76.9% | 0.2 | 0.2 | $2.40 | $2,000.00 |
| **CONTROL_BTC_20_CASH_80_REBAL (Weekly Rebal)** | $11,807.96 | **+18.08%** | -17.85% | 0.390 | 0.550 | 79.9% | 2.2 | 2.2 | $27.78 | $23,151.42 |
| **CONTROL_VOL_TARGETED_12PCT (Realized Vol Risk Parity)** | $11,088.28 | **+10.88%** | -30.55% | 0.207 | 0.282 | 71.9% | 14.7 | 14.9 | $190.52 | $158,763.50 |
| **BENCHMARK_POLICY_A (Market Cash Gating)** | $13,702.94 | **+37.03%** | -55.76% | 0.392 | 0.545 | 32.8% | 175.4 | 242.6 | $4,014.46 | $3,345,379.28 |
| **BENCHMARK_CARM_CANONICAL (Sunday 00 UTC, 0% Cash)** | $7,602.67 | **-23.97%** | -76.53% | 0.264 | 0.368 | 0.0% | 156.6 | 312.1 | $4,441.92 | $3,701,599.47 |
| **BENCHMARK_BTC_BUY_AND_HOLD (100% BTC)** | $14,036.21 | **+40.36%** | -67.38% | 0.386 | 0.544 | 0.0% | 1.0 | 1.0 | $12.00 | $10,000.00 |
| **BENCHMARK_CASH (100% Cash)** | $10,000.00 | **+0.00%** | 0.00% | 0.000 | 0.000 | 100.0% | 0.0 | 0.0 | $0.00 | $0.00 |

---

## 2. Chronological Splits Breakdown (Sub-Period Returns & Realized Cash Exposure)

| Strategy / Policy | Train (2022-2023) Ret / Cash | Val (2024) Ret / Cash | Reused Holdout (2025-2026) Ret / Cash |
| :--- | :--- | :--- | :--- |
| **UNIFIED_NEURAL_PILOT (Market-Only, Seed 42)** | +4.05% (94.0% C) | +6.81% (95.1% C) | +0.70% (95.9% C) |
| **UNIFIED_NEURAL_PILOT (Market + Regime, Seed 42)** | +5.00% (91.1% C) | +4.36% (91.8% C) | +1.22% (92.7% C) |
| **UNIFIED_NEURAL_PILOT (Cost Stress 25 bps)** | +3.44% (94.0% C) | +6.47% (95.1% C) | +0.26% (95.9% C) |
| **ABLATION_NEURAL_CASH_ONLY (Neural Cash + EW Risky)** | +3.00% (94.0% C) | +7.61% (95.1% C) | -0.11% (95.9% C) |
| **ABLATION_NEURAL_SELECTION_ONLY (Neural Selection + 85% Cash)** | +2.07% (85.0% C) | +12.16% (84.9% C) | -5.65% (85.0% C) |
| **FALSIFICATION_RANDOM_NEURAL (Untrained Seed 42)** | -16.09% (11.9% C) | +88.82% (12.1% C) | -43.17% (12.0% C) |
| **FALSIFICATION_SHUFFLED_SIGNAL (Train Shuffled Seed 42)** | +4.28% (93.3% C) | +7.63% (94.5% C) | +1.94% (95.7% C) |
| **CONTROL_STATIC_85CASH_15EW (Weekly Rebal)** | +1.79% (85.0% C) | +13.85% (84.9% C) | -6.37% (85.0% C) |
| **CONTROL_BTC_10_CASH_90_BnH (Static Buy&Hold)** | -0.95% (93.6% C) | +11.15% (86.4% C) | -5.77% (82.5% C) |
| **CONTROL_BTC_10_CASH_90_REBAL (Weekly Rebal)** | +2.18% (90.0% C) | +9.31% (89.9% C) | -2.33% (90.0% C) |
| **CONTROL_BTC_20_CASH_80_BnH (Static Buy&Hold)** | -1.89% (86.8% C) | +22.48% (74.0% C) | -10.55% (67.8% C) |
| **CONTROL_BTC_20_CASH_80_REBAL (Weekly Rebal)** | +3.70% (80.0% C) | +19.21% (79.8% C) | -4.90% (80.0% C) |
| **CONTROL_VOL_TARGETED_12PCT (Realized Vol Risk Parity)** | +6.26% (73.4% C) | +20.59% (74.5% C) | -14.06% (69.0% C) |
| **BENCHMARK_POLICY_A (Market Cash Gating)** | +25.23% (32.6% C) | +105.55% (27.5% C) | -48.30% (35.8% C) |
| **BENCHMARK_CARM_CANONICAL (Sunday 00 UTC, 0% Cash)** | +22.26% (0.0% C) | +102.78% (0.0% C) | -70.21% (0.0% C) |
| **BENCHMARK_BTC_BUY_AND_HOLD (100% BTC)** | -9.37% (0.0% C) | +120.31% (0.0% C) | -31.20% (0.0% C) |
| **BENCHMARK_CASH (100% Cash)** | +0.00% (100.0% C) | +0.00% (100.0% C) | +0.00% (100.0% C) |

---

## 3. Annual Performance & Exposure Breakdown

| Strategy / Policy | 2022 (Bear) | 2023 (Recovery) | 2024 (Bull) | 2025 (Bear) | 2026 (Chop) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **UNIFIED_NEURAL_PILOT (Market-Only, Seed 42)** | -3.9% (92%C) | +8.3% (96%C) | +6.8% (95%C) | +4.0% (96%C) | -3.2% (96%C) |
| **UNIFIED_NEURAL_PILOT (Market + Regime, Seed 42)** | -6.0% (89%C) | +11.8% (93%C) | +4.4% (92%C) | +4.7% (92%C) | -3.3% (93%C) |
| **ABLATION_NEURAL_CASH_ONLY (Neural Cash + EW Risky)** | -4.0% (92%C) | +7.3% (96%C) | +7.6% (95%C) | +3.2% (96%C) | -3.3% (96%C) |
| **ABLATION_NEURAL_SELECTION_ONLY (Neural Selection + 85% Cash)** | -13.5% (85%C) | +18.1% (85%C) | +12.2% (85%C) | -0.6% (85%C) | -5.2% (85%C) |
| **CONTROL_STATIC_85CASH_15EW (Weekly Rebal)** | -13.2% (85%C) | +17.4% (85%C) | +13.8% (85%C) | -1.3% (85%C) | -5.2% (85%C) |
| **CONTROL_BTC_10_CASH_90_BnH (Static Buy&Hold)** | -6.5% (94%C) | +6.0% (94%C) | +11.2% (86%C) | -1.3% (80%C) | -4.5% (85%C) |
| **CONTROL_VOL_TARGETED_12PCT (Realized Vol Risk Parity)** | -24.0% (78%C) | +40.0% (69%C) | +20.6% (74%C) | -1.0% (70%C) | -13.3% (68%C) |
| **BENCHMARK_BTC_BUY_AND_HOLD (100% BTC)** | -64.5% (0%C) | +155.8% (0%C) | +120.3% (0%C) | -7.2% (0%C) | -26.0% (0%C) |
| **BENCHMARK_CARM_CANONICAL (Sunday 00 UTC, 0% Cash)** | -67.4% (0%C) | +277.3% (0%C) | +102.8% (0%C) | -40.3% (0%C) | -50.2% (0%C) |

---

## 4. Seed Distribution & Stability (Seeds 42, 123, 777)

### Market-Only (8 Features)
| Seed | Final Equity ($) | Net Ret (%) | Max DD (%) | Train Ret (%) | Val Ret (%) | Holdout Ret (%) | Mean Cash (%) | Fees ($) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Seed 42** | $11,350.18 | **+13.50%** | -15.92% | +4.05% | +6.81% | +0.70% | 95.0% | $143.62 |
| **Seed 123** | $13,421.66 | **+34.22%** | -16.76% | +27.40% | +10.17% | -5.75% | 89.6% | $384.48 |
| **Seed 777** | $12,688.98 | **+26.89%** | -18.33% | +7.66% | +3.93% | +11.77% | 89.3% | $386.50 |

### Market + Regime (10 Features)
| Seed | Final Equity ($) | Net Ret (%) | Max DD (%) | Train Ret (%) | Val Ret (%) | Holdout Ret (%) | Mean Cash (%) | Fees ($) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Seed 42** | $11,253.97 | **+12.54%** | -15.92% | +5.00% | +4.36% | +1.22% | 91.9% | $186.69 |
| **Seed 123** | $12,797.34 | **+27.97%** | -20.11% | +14.43% | +1.67% | +8.45% | 88.4% | $454.66 |
| **Seed 777** | $12,031.98 | **+20.32%** | -19.49% | +12.42% | -2.46% | +8.17% | 89.0% | $420.54 |

---

## 5. Answers to the 4 Core Falsification Questions

### Q1: Does the Neural Policy beat exposure-matched baselines?
**NO.**
- While `UNIFIED_NEURAL_PILOT (Market-Only, Seed 42)` achieved **+13.50% net return** with **-15.92% Max DD**, it operated with an average realized cash weight of **95.0%**.
- A simple, non-neural rule baseline of **90% Cash + 10% BTC (rebalanced weekly)** achieved:
  - **Net Return**: +9.33%
  - **Max Drawdown**: **-9.23%** (significantly safer than neural's -15.92%)
  - **Annualized Sharpe**: **0.390** (vs neural's 0.324)
  - **Annualized Sortino**: **0.550** (vs neural's 0.453)
  - **Total Fees**: **$15.03** (vs neural's $143.62, an order-of-magnitude lower transaction cost)
- Furthermore, **80% Cash + 20% BTC (rebalanced weekly)** delivered **+18.08% net return** with **Sharpe 0.390** and **Sortino 0.550**, outperforming the neural model on both absolute return and risk-adjusted efficiency.

### Q2: Does Neural improve drawdown/Sortino at equivalent risk levels?
**NO.**
- At equivalent ~90% cash exposure, the neural policy exhibits higher downside semi-deviation than cash-dampened BTC because its remaining 5–10% risky capital is scattered across volatile altcoins (ADA, SOL, LINK, LTC).
- As a result, Neural's Sortino ratio is **0.453**, noticeably lower than the **0.550** Sortino achieved by the simple 90% Cash / 10% BTC baseline.
- The neural policy fails to produce a more efficient efficient-frontier point than a naive cash-plus-BTC combination.

### Q3: Did economic performance come from asset selection or cash timing?
**ALMOST ENTIRELY FROM CASH DAMPENING (holding 90–95% cash), NOT FROM ASSET SELECTION.**
Three independent empirical lines of evidence demonstrate this:
1. **Ablation 1 (Cash Only)**: Replacing neural asset selection with an Equal-Weight risky allocation `(1 - w_cash) / N` yields **$11,229.90 (+12.30%)**, which is within 1.20% of the full neural model ($11,350.18, +13.50%). Over 4.88 years, active cross-sectional selection contributed less than 25 bps/year.
2. **Ablation 2 (Selection Only)**: When neural asset selection is forced to run with fixed 85% cash, it yields **+8.51% net return**, which is slightly *worse* than naive Equal-Weight with 85% cash (**+9.02%**). The learned cross-sectional weights had negative alpha relative to equal weight!
3. **Falsification Control (Shuffled Signal)**: When the neural policy is trained on randomly permuted features (where features have zero true connection to forward returns), it achieved **+16.04% net return**, Sharpe **0.362**, Sortino **0.506**, and **94.5% realized cash**! This proves conclusively that the training objective (downside semi-deviation penalty + turnover penalty) drives the policy into a permanent cash shelter regardless of whether the input features contain true alpha or pure noise.

### Q4: Does the value hold after 12 bps fee and 25 bps stress?
- Under 25 bps stress, net return remains positive at **+11.85%** because one-way turnover is only 11.2.
- However, this cost resilience is trivial: any portfolio holding 95% cash naturally has negligible fee drag. The fee resilience does not reflect learned execution intelligence.

---

## 6. Scientific Decision & Single Grounded Next Step

### Final Verdict: **`NEURAL_INCREMENTAL_VALUE_NOT_SUPPORTED`**

> **Core Conclusion**: The small Unified Neural Policy's apparent outperformance over CARM Canonical (-23.97% -> +13.50%) is predominantly driven by passive cash exposure dampening (holding 90-95% cash) rather than learned asset selection alpha. When evaluated against exposure-matched baselines, simple rule-based controls (90% Cash + 10% BTC rebalanced weekly) achieve superior Sharpe (0.390 vs 0.324), higher Sortino (0.550 vs 0.453), significantly lower Max Drawdown (-9.23% vs -15.92%), and 10x lower transaction fees ($15 vs $143). Furthermore, the Shuffled-Signal falsification control achieved +16.04% net return, proving that the downside penalty in the cost-aware loss function drives the network into a permanent high-cash posture regardless of feature signal.

### Single Grounded Next Experiment Recommendation:
Do **NOT** scale model capacity or prematurely deploy complex temporal architectures (TCN, Mamba, Transformer).
The root bottleneck is that the **portfolio optimization objective allows the unconstrained cash head to satisfy the downside penalty by hiding in cash**, completely disincentivizing the network from learning true cross-sectional predictive representations.

**Next Actionable Experiment**:
1. **Decouple Asset Selection from Risk Management**: Train the neural encoder on a **Fully-Invested Long-Only Universe** ($\sum_{i=1}^N w_i = 1.0$, $w_i \ge 0$, no cash head) using a **Cross-Sectional Excess Return Objective** (maximizing $\sum_i w_i (r_{i, t} - r_{\text{BTC}, t})$ or rank IC).
2. Once (and only once) the neural network demonstrates genuine cross-sectional alpha over Equal-Weight on the fully-invested risky sleeve, combine it with a macro regime gating overlay.
