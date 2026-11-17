# Unified Neural Cross-Sectional Alpha Discovery Report

**Clean Aligned Horizon**: 2022-01-16 00:00 UTC to 2026-11-16 19:00 UTC (42,379 hourly bars, ~4.84 years)  
**Execution & Accounting Standards**: Next-bar open execution | Hourly close mark-to-market | 12.0 bps fee (stress: 25.0 bps) | Cash = 0% (Fully Invested)  

---

## 1. Warmup Attribution & Inception Confounder Remediation

> [!IMPORTANT]
> **Warmup Period Analysis (2022-01-01 to 2022-01-16)**:
> - Before the first valid neural decision at `2022-01-16 00:00 UTC` (requiring 194h warmup), the broader crypto market suffered an immediate crash.
> - Equal-Weight 8-coin basket: **-2.86%** return, **-16.13%** Max Drawdown.
> - BTC return: **-7.69%**.
> - **Confounder Remediation**: In earlier runs, initializing into 100% EW crypto at 2022-01-01 caused the entire recorded Max Drawdown (-15.92%) to occur *before* the neural policy ever made a single decision. In this study, all strategies begin on an identical $10,000 cash footing at `2022-01-16 00:00 UTC` with first execution at `open[2022-01-16 00:00 UTC]`.

---

## 2. Fully-Invested Risky-Sleeve Scorecard (Clean Aligned Horizon)

| Strategy / Benchmark | Final Equity ($) | Net Ret (%) | Excess vs BTC (%p) | Excess vs EW (%p) | Max DD (%) | Ann. Sharpe | Ann. Sortino | Mean N_eff | 1-Way TO | Fees ($) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **NEURAL_RISKY_SLEEVE (Market-Only, Seed 42)** | $8,142.72 | **-18.57%** | -69.14% | +0.63% | -69.58% | 0.259 | 0.355 | 7.96 | 7.5 | $157.94 |
| **NEURAL_RISKY_SLEEVE (Market+Regime, Seed 42)** | $8,087.77 | **-19.12%** | -69.69% | +0.08% | -70.47% | 0.260 | 0.357 | 7.99 | 5.5 | $114.52 |
| **NEURAL_RISKY_SLEEVE (Cost Stress 25 bps)** | $7,996.36 | **-20.04%** | -70.61% | -0.84% | -69.68% | 0.253 | 0.347 | 7.96 | 7.5 | $325.62 |
| **FALSIFICATION_UNTRAINED_NEURAL (Seed 42)** | $8,122.82 | **-18.77%** | -69.34% | +0.43% | -69.69% | 0.258 | 0.353 | 7.97 | 6.6 | $137.77 |
| **FALSIFICATION_TEMPORAL_SHUFFLED (Seed 42)** | $6,953.89 | **-30.46%** | -81.03% | -11.26% | -65.96% | 0.149 | 0.204 | 5.44 | 50.6 | $1,004.17 |
| **BENCHMARK_EQUAL_WEIGHT_WEEKLY_REBAL** | $8,079.93 | **-19.20%** | -69.77% | +0.00% | -70.41% | 0.259 | 0.356 | 7.99 | 5.9 | $122.27 |
| **BENCHMARK_EQUAL_WEIGHT_BUY_AND_HOLD** | $7,173.23 | **-28.27%** | -78.84% | -9.07% | -69.70% | 0.200 | 0.275 | 6.48 | 1.0 | $12.00 |
| **BENCHMARK_BTC_BUY_AND_HOLD** | $15,056.78 | **+50.57%** | +0.00% | +69.77% | -67.38% | 0.420 | 0.592 | 1.00 | 1.0 | $12.00 |
| **BENCHMARK_CARM_CANONICAL (Top 3 Momentum)** | $7,741.20 | **-22.59%** | -73.16% | -3.39% | -76.53% | 0.272 | 0.379 | 3.02 | 154.9 | $4,485.05 |

---

## 3. Chronological Splits & Selection Hit Rate

| Strategy / Benchmark | Train (2022-2023) | Val (2024) | Reused Holdout (2025-2026) | Hit Rate vs EW (%) | Hit Rate vs BTC (%) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **NEURAL_RISKY_SLEEVE (Market-Only, Seed 42)** | -20.60% | +100.36% | -49.71% | 52.8% | 44.0% |
| **NEURAL_RISKY_SLEEVE (Market+Regime, Seed 42)** | -21.16% | +102.95% | -50.34% | 50.8% | 43.7% |
| **NEURAL_RISKY_SLEEVE (Cost Stress 25 bps)** | -21.16% | +99.60% | -50.02% | 50.8% | 44.0% |
| **FALSIFICATION_UNTRAINED_NEURAL (Seed 42)** | -21.20% | +101.17% | -49.66% | 54.0% | 44.0% |
| **FALSIFICATION_TEMPORAL_SHUFFLED (Seed 42)** | -31.61% | +100.71% | -50.05% | 54.0% | 43.3% |
| **BENCHMARK_EQUAL_WEIGHT_WEEKLY_REBAL** | -21.32% | +103.38% | -50.40% | 0.0% | 43.7% |
| **BENCHMARK_EQUAL_WEIGHT_BUY_AND_HOLD** | -33.51% | +99.95% | -46.95% | 53.6% | 41.7% |
| **BENCHMARK_BTC_BUY_AND_HOLD** | -1.83% | +120.31% | -31.20% | 56.3% | 0.0% |
| **BENCHMARK_CARM_CANONICAL (Top 3 Momentum)** | +26.22% | +102.78% | -70.21% | 46.8% | 39.3% |

---

## 4. Annual Performance by Market Regime

| Strategy / Benchmark | 2022 (Bear Ex-Warmup) | 2023 (Recovery) | 2024 (Bull) | 2025 (Bear) | 2026 (Chop) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **NEURAL_RISKY_SLEEVE (Market-Only, Seed 42)** | -68.1% | +149.9% | +100.4% | -19.6% | -37.6% |
| **NEURAL_RISKY_SLEEVE (Market+Regime, Seed 42)** | -68.9% | +154.6% | +103.0% | -20.4% | -37.8% |
| **NEURAL_RISKY_SLEEVE (Cost Stress 25 bps)** | -68.2% | +149.0% | +99.6% | -19.9% | -37.7% |
| **FALSIFICATION_UNTRAINED_NEURAL (Seed 42)** | -68.2% | +148.7% | +101.2% | -19.7% | -37.5% |
| **FALSIFICATION_TEMPORAL_SHUFFLED (Seed 42)** | -64.8% | +95.0% | +100.7% | -20.7% | -37.2% |
| **BENCHMARK_EQUAL_WEIGHT_WEEKLY_REBAL** | -68.8% | +153.5% | +103.4% | -20.5% | -37.7% |
| **BENCHMARK_EQUAL_WEIGHT_BUY_AND_HOLD** | -67.1% | +103.2% | +100.0% | -15.5% | -37.3% |
| **BENCHMARK_BTC_BUY_AND_HOLD** | -61.6% | +155.8% | +120.3% | -7.2% | -26.0% |
| **BENCHMARK_CARM_CANONICAL (Top 3 Momentum)** | -66.3% | +277.3% | +102.8% | -40.3% | -50.2% |

---

## 5. Seed Distribution & Robustness (Seeds 42, 123, 777)

### Market-Only Risky Sleeve (8 Features)
| Seed | Final Equity ($) | Net Ret (%) | Excess vs BTC | Excess vs EW | Max DD (%) | Train Ret (%) | Val Ret (%) | Holdout Ret (%) | Mean N_eff | Fees ($) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Seed 42** | $8,142.72 | **-18.57%** | -69.37% | +0.61% | -69.58% | -20.60% | +100.36% | -49.71% | 7.96 | $157.94 |
| **Seed 123** | $8,129.42 | **-18.71%** | -69.51% | +0.47% | -70.36% | -21.03% | +104.70% | -50.60% | 7.99 | $148.90 |
| **Seed 777** | $8,180.54 | **-18.19%** | -68.99% | +0.99% | -70.00% | -20.29% | +104.39% | -50.67% | 7.98 | $126.21 |

### Market + Regime Risky Sleeve (10 Features)
| Seed | Final Equity ($) | Net Ret (%) | Excess vs BTC | Excess vs EW | Max DD (%) | Train Ret (%) | Val Ret (%) | Holdout Ret (%) | Mean N_eff | Fees ($) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Seed 42** | $8,087.77 | **-19.12%** | -69.92% | +0.06% | -70.47% | -21.16% | +102.95% | -50.34% | 7.99 | $114.52 |
| **Seed 123** | $8,167.44 | **-18.33%** | -69.13% | +0.85% | -70.58% | -20.11% | +103.79% | -50.73% | 7.98 | $114.67 |
| **Seed 777** | $8,197.64 | **-18.02%** | -68.82% | +1.16% | -70.38% | -20.21% | +105.05% | -50.78% | 7.99 | $113.60 |

---

## 6. Scientific Verdict & Architectural Follow-Up

### Final Verdict: **`CROSS_SECTIONAL_NEURAL_ALPHA_NOT_SUPPORTED`**

> **Detailed Finding**: The fully-invested Neural Risky Sleeve delivered -18.57% net return (vs BTC +50.57%, EW -19.20%). Performance is comparable to or worse than non-neural benchmarks, with higher turnover and fee drag.

### Unified Policy Objective Follow-Up:
1. **Shared Encoder Evaluation**: In diagnostic mode with zero cash, the small shared MLP encoder mapping multi-asset causal returns and momentum to relative weights did not beat naive Equal-Weighting on a risk-adjusted basis. Cross-sectional momentum in altcoins exhibits high idiosyncratic variance and severe mean reversion during bear markets, leading to high turnover drag without sustained excess alpha.
2. **Auxiliary Selection Objective Decision**: Adding an auxiliary cross-sectional selection loss to the joint network is **NOT recommended at this stage** using the current 168h raw return features. Before adding complex multi-task objectives, the feature representation itself (or prediction target horizon) must demonstrate genuine information content over simple baselines.
3. **Single Grounded Next Experiment**: Instead of hand-engineering multi-asset weekly features, test whether an **information-theoretic feature selection audit** (Mutual Information & Canonical Correlation Analysis across multiple lookbacks 1h to 168h) reveals any statistically significant non-linear predictability in the 8-coin universe, or if altcoin cross-sectional alpha is fundamentally dominated by market beta and transaction friction at the weekly scale.
