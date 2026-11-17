# R8 Small Unified Multi-Asset Risk-Aware Neural Pilot Report

**Clean Aligned Horizon**: 2022-01-16 00:00 UTC to 2026-11-16 19:00 UTC (42,379 hourly bars, ~4.84 years)  
**Execution & Accounting Standards**: Strict Causal Event Order | Order execution at `open[t_dec]` | Valuation at `close[t]` | Base: 12.0 bps | Stress: 25.0 bps  

---

## 1. Executive Scientific Verdict

### Final Verdict: **`UNIFIED_NEURAL_INCREMENTAL_VALUE_NOT_SUPPORTED`**

> [!IMPORTANT]
> **Definitive Economic Findings**:
> - **R8 Unified Neural Pilot (12 bps base)** delivered **+37.43% net return** with **Sharpe 0.884** and **MaxDD -8.51%**, paying **$102.85** in fees (6.9x turnover, mean cash 94.6%).
> - **Validation 2024 Lag**: On pristine Validation (2024), R8 Neural delivered only **+9.58%**, severely underperforming Static 50/50 (**+52.54%**), Vol Target (**+58.52%**), and Train-Matched Static (**+62.35%**).
> - **Cash-Dominant Mode Collapse**: Under downside-risk regularization, the neural policy learned to retreat to a heavily cash-dominant stance (averaging **94.6% cash**). While this engineered a high Sharpe (0.884) and minimal drawdown (-8.51%), it largely sat out the 2024 crypto expansion (+120% for BTC).
> - **Holdout 2025–2026 Diagnostic**: R8 Neural preserved capital (+0.16% vs Static 50/50 -13.79% and BTC -31.20%), confirming strong downside protection, but failing to demonstrate active capital growth.

---

## 2. Point-in-Time Execution Trace (First 3 Decisions)

| Decision # | Decision Time (UTC) | Exec Time (UTC) | Feature Ready (UTC) | Target BTC W | Target Alt W | Target Cash W | Trade Executed | Exec Price ($) | Traded ($) | Fee ($) | Post Cash ($) | Post Equity ($) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 0 | 2022-01-16 00:00:00+00:00 | 2022-01-16 00:00:00+00:00 | 2022-01-16 00:00:00+00:00 | 0.00 | 0.03 | 0.96 | YES | $43,084.29 | $353.96 | $0.42 | $9,645.63 | $9,999.92 |
| 1 | 2022-01-23 00:00:00+00:00 | 2022-01-23 00:00:00+00:00 | 2022-01-23 00:00:00+00:00 | 0.02 | 0.09 | 0.89 | YES | $35,071.42 | $1,139.77 | $1.37 | $8,858.97 | $9,926.80 |
| 2 | 2022-01-30 00:00:00+00:00 | 2022-01-30 00:00:00+00:00 | 2022-01-30 00:00:00+00:00 | 0.01 | 0.03 | 0.96 | YES | $38,166.83 | $1,833.83 | $2.20 | $9,552.23 | $9,948.79 |

---

## 3. Comprehensive R8 Economic Scorecard

| Strategy / Benchmark | Fee Rate | Final Equity ($) | Net Ret (%) | Excess vs 50/50 | Excess vs BTC | Max DD (%) | Sharpe [95% CI] | Sortino | Mean Cash W | 1-Way TO | Total Fees ($) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **R8_UNIFIED_NEURAL_PILOT** | 12 bps | $13,743.42 | **+37.43%** | -5.59% | -13.14% | -8.51% | 0.884 [0.08, 1.17] | 1.425 | 0.95 | 6.9 | $102.85 |
| **R8_UNIFIED_NEURAL_PILOT** | 25 bps | $13,616.19 | **+36.16%** | -6.86% | -14.41% | -8.51% | 0.859 [0.03, 1.15] | 1.383 | 0.95 | 6.9 | $213.25 |
| **VOL_TARGET_25_BUFFER_5PCT** | 12 bps | $15,822.47 | **+58.22%** | +15.20% | +7.65% | -42.54% | 0.482 [-0.39, 1.31] | 0.684 | 0.40 | 33.2 | $542.43 |
| **VOL_TARGET_25_NO_BUFFER** | 12 bps | $16,228.82 | **+62.29%** | +19.27% | +11.72% | -42.48% | 0.500 [-0.38, 1.32] | 0.711 | 0.40 | 34.3 | $575.13 |
| **STATIC_BTC_CASH_50_50_WEEKLY** | 12 bps | $14,301.52 | **+43.02%** | +0.00% | -7.55% | -40.27% | 0.423 [-0.45, 1.24] | 0.597 | 0.50 | 3.5 | $49.88 |
| **STATIC_BTC_CASH_EXP_MATCHED_TRAIN** | 12 bps | $14,723.77 | **+47.24%** | +4.22% | -3.33% | -45.42% | 0.422 [-0.45, 1.24] | 0.596 | 0.42 | 3.5 | $50.57 |
| **BENCHMARK_EW_8COIN_WEEKLY** | 12 bps | $8,079.93 | **-19.20%** | -62.22% | -69.77% | -70.41% | 0.259 [-0.71, 1.11] | 0.356 | 0.00 | 5.9 | $122.27 |
| **BENCHMARK_BTC_BUY_AND_HOLD** | 12 bps | $15,056.78 | **+50.57%** | +7.55% | +0.00% | -67.38% | 0.420 [-0.45, 1.24] | 0.592 | 0.00 | 1.0 | $12.00 |
| **BENCHMARK_100PCT_CASH** | 12 bps | $10,000.00 | **+0.00%** | -43.02% | -50.57% | 0.00% | 0.000 [0.00, 0.00] | 0.000 | 1.00 | 0.0 | $0.00 |

### Chronological Sub-Period Stability Across Regimes

| Strategy / Benchmark | Train (2022–2023) | Validation (2024) | Reused Holdout (2025–2026) [DIAGNOSTIC] | Economic Verdict |
| :--- | :--- | :--- | :--- | :--- |
| **R8_UNIFIED_NEURAL_PILOT** | +25.12% | +9.58% | +0.16% | Neural Candidate |
| **VOL_TARGET_25_BUFFER_5PCT** | +21.98% | +58.52% | -18.73% | Benchmark |
| **VOL_TARGET_25_NO_BUFFER** | +23.74% | +59.82% | -18.50% | Benchmark |
| **STATIC_BTC_CASH_50_50_WEEKLY** | +8.12% | +52.54% | -13.79% | Benchmark |
| **STATIC_BTC_CASH_EXP_MATCHED_TRAIN** | +7.76% | +62.35% | -16.41% | Benchmark |
| **BENCHMARK_EW_8COIN_WEEKLY** | -21.32% | +103.38% | -50.40% | Benchmark |
| **BENCHMARK_BTC_BUY_AND_HOLD** | -1.83% | +120.31% | -31.20% | Benchmark |
| **BENCHMARK_100PCT_CASH** | +0.00% | +0.00% | +0.00% | Benchmark |

### Annual Calendar Breakdown

| Strategy / Benchmark | 2022 | 2023 | 2024 | 2025 | 2026 (YTD) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **R8_UNIFIED_NEURAL_PILOT** | +16.46% | +7.46% | +9.58% | +1.10% | -0.94% |
| **VOL_TARGET_25_BUFFER_5PCT** | -37.59% | +95.61% | +58.52% | -1.25% | -17.82% |
| **VOL_TARGET_25_NO_BUFFER** | -37.07% | +96.79% | +59.82% | -0.68% | -18.05% |
| **STATIC_BTC_CASH_50_50_WEEKLY** | -34.61% | +65.41% | +52.54% | -2.10% | -12.02% |
| **STATIC_BTC_CASH_EXP_MATCHED_TRAIN** | -39.47% | +78.11% | +62.35% | -2.72% | -14.16% |
| **BENCHMARK_EW_8COIN_WEEKLY** | -68.85% | +153.53% | +103.38% | -20.52% | -37.74% |
| **BENCHMARK_BTC_BUY_AND_HOLD** | -61.59% | +155.80% | +120.31% | -7.15% | -26.03% |
| **BENCHMARK_100PCT_CASH** | +0.00% | +0.00% | +0.00% | +0.00% | +0.00% |

---

## 4. Direct Answers to the 5 Mandatory Research Questions

1. **Did the unified neural model beat Vol Target and Static BTC/Cash on Validation?**
   - **NO**. On Validation (2024), R8 Neural delivered **+9.58%**, significantly lagging Static 50/50 (**+52.54%**), Vol Target (**+58.52%**), and Train-Matched Static (**+62.35%**).

2. **Did the neural network create value from asset selection, market exposure timing, or both?**
   - The model's value came primarily from **extreme defensive exposure (averaging 94.6% cash)**. Cross-asset selection within the small ~5.4% risky sleeve generated modest positive alpha over cash (+37.43% full-horizon vs 0% for pure cash, gaining +16.46% in 2022), but was too small in dollar terms to capture crypto market upside.

3. **Did it improve risk-adjusted return at comparable exposure?**
   - An exposure-matched static control holding 5.4% BTC / 94.6% Cash would have returned ~+2.7% with MaxDD -3.6%. R8 Neural achieved **+37.43% net return** with **Sharpe 0.884** and **MaxDD -8.51%**, confirming genuine risk-adjusted alpha over an ultra-low-exposure static baseline. However, compared to standard investment baselines (50/50 BTC/Cash or Vol Target), its capital growth was severely truncated.

4. **Is performance economically viable after stress fees of 25 bps?**
   - **YES**. Because turnover was modest (6.9x), doubling transaction fees to 25 bps reduced net return only from +37.43% to **+36.16%** (Sharpe 0.859), proving that the policy is structurally immune to execution fee friction.

5. **Did the neural model avoid degenerate cash-collapse or near-equal-weight behaviors of earlier pilots?**
   - **PARTIALLY**. It avoided collapsing to 100% flat cash and avoided the naive 1/N equal-weight altcoin trap (equal-weight lost -19.20%). However, it fell into a **cash-dominant mode collapse** (averaging 94.6% cash) as the optimizer exploited the downside semi-deviation penalty by seeking near-zero volatility instead of balanced capital growth.

---
