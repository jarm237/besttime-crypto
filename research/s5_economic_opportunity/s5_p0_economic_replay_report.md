# S5-P0: Economic Opportunity Historical Replay Report

- **Pre-registration Commit:** `b894fc53de0e2b50720828c1ab72d2d774d5fcbb`
- **Base Tag:** `s4-stage1-closure`
- **Evaluation Window:** `2022-01-01T00:00:00+00:00 to 2023-12-31T23:00:00+00:00`
- **Generated At (UTC):** `2026-11-19T07:58:56.946715+00:00`
- **Scientific Economic Verdict:** **`S5_P0_NO_DEMONSTRATED_OPPORTUNITY`**

```text
S5_P0_REPLAY_2022_2023   = COMPLETED
S5_P0_SCIENTIFIC_VERDICT = S5_P0_NO_DEMONSTRATED_OPPORTUNITY
S5_2024_2026_ACCESS     = NOT_AUTHORIZED
S5_NEURAL_TRAINING      = NOT_AUTHORIZED
PRODUCTION_PROMOTION    = NOT_AUTHORIZED
NEXT_ACTION             = STOP_AND_REVIEW_ECONOMICS
```

## 1. Executive Summary & Verdict Analysis

- **BTC Buy & Hold Baseline:** CAGR = `-4.41%`, MaxDD = `-67.38%`, Calmar = `-0.0655`.
- **Is BTC CAGR Positive?:** `False`.
- **Regime Context:** Over the full 2022–2023 development period, Bitcoin experienced a net negative compound growth rate due to the severe 2022 bear market (-65.4% decline). In accordance with Pre-Execution Erratum A3, the 75% CAGR retention condition was marked `NOT_APPLICABLE`, and the fallback gate evaluated capital preservation ($V_T > V_0$), drawdown compression ($\le 65\%$ of BTC MaxDD), and Calmar superiority.

- **Qualifying Candidate Policies:** `[]`

## 2. Primary Configuration Scorecard (Weekly Sunday, 5% Band, 12 bps)

| Policy | Tier | Net CAGR | Max DD | Calmar | Sharpe | Excess vs BTC | Avg Cash% | Turnover (x/yr) | Total Fees ($) | Terminal ($) | Breakeven vs BTC |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `CASH_100` | 0 (Passive) | 0.00% | 0.00% | 0.0000 | 0.00 | +4.41% | 100.0% | 0.0x | $0.00 | $10000.00 | `N/A` |
| `BTC_BH` | 0 (Passive) | -4.41% | -67.38% | -0.0655 | -0.09 | +0.00% | 0.0% | 0.5x | $11.99 | $9137.97 | `N/A` |
| `EW4` | 0 (Passive) | -7.22% | -75.20% | -0.0960 | -0.12 | -2.81% | 0.0% | 1.0x | $24.35 | $8609.10 | `NO_POSITIVE_BREAKEVEN_EDGE` |
| `EW4_BUY_AND_HOLD` | 0 (Passive) | -17.24% | -72.09% | -0.2392 | -0.31 | -12.83% | 0.0% | 0.5x | $11.99 | $6850.53 | `NO_POSITIVE_BREAKEVEN_EDGE` |
| `TREND_GATE_BTC` | 1 (Timing) | -8.45% | -43.92% | -0.1923 | -0.26 | -4.04% | 53.8% | 19.3x | $463.91 | $8383.07 | `NO_POSITIVE_BREAKEVEN_EDGE` |
| `TREND_GATE_EW4` | 1 (Timing) | -16.73% | -56.19% | -0.2978 | -0.41 | -12.32% | 53.8% | 16.5x | $395.19 | $6935.60 | `NO_POSITIVE_BREAKEVEN_EDGE` |
| `VOL_TARGET_BTC` | 1 (Timing) | 4.01% | -49.54% | 0.0810 | 0.10 | +8.42% | 28.7% | 5.6x | $133.75 | $10818.02 | `100.0 bps` |
| `VOL_TARGET_EW4` | 1 (Timing) | 4.51% | -59.44% | 0.0759 | 0.09 | +8.92% | 28.8% | 5.1x | $122.72 | $10922.42 | `100.0 bps` |
| `MOMENTUM_TOP1` | 2 (Rotation) | -6.71% | -78.34% | -0.0856 | -0.09 | -2.30% | 0.0% | 34.5x | $827.87 | $8704.75 | `8.6 bps` |
| `MOMENTUM_TOP1_TREND_GATE` | 2 (Rotation+Timing) | -1.25% | -57.63% | -0.0217 | -0.02 | +3.16% | 53.8% | 27.2x | $652.46 | $9751.25 | `20.8 bps` |
| `MOMENTUM_TOP2` *(CARM4)* | 2 (Rotation) | -19.92% | -79.75% | -0.2498 | -0.32 | -15.51% | 0.0% | 23.1x | $553.22 | $6415.20 | `NO_POSITIVE_BREAKEVEN_EDGE` |
| `MOMENTUM_TOP2_TREND_GATE` *(CARM4+Gate)* | 2 (Rotation+Timing) | -27.51% | -67.89% | -0.4052 | -0.61 | -23.10% | 53.8% | 19.7x | $471.27 | $5257.05 | `NO_POSITIVE_BREAKEVEN_EDGE` |
| `INVERSE_VOL4` | 2 (Rotation) | -15.16% | -70.99% | -0.2136 | -0.27 | -10.75% | 0.0% | 3.1x | $73.53 | $7199.36 | `NO_POSITIVE_BREAKEVEN_EDGE` |
| `INVERSE_VOL4_TREND_GATE` | 2 (Rotation+Timing) | -19.61% | -55.27% | -0.3549 | -0.54 | -15.20% | 53.8% | 17.6x | $422.62 | $6464.09 | `NO_POSITIVE_BREAKEVEN_EDGE` |

## 3. Sub-Window Regime Breakdown

### 3.1. 2022 Bear / Deleveraging Window

| Policy | 2022 CAGR | 2022 Max DD | 2022 Calmar | 2022 Sharpe | 2022 Terminal ($) |
|---|---:|---:|---:|---:|---:|
| `CASH_100` | 0.00% | 0.00% | 0.0000 | 0.00 | $10000.00 |
| `BTC_BH` | -64.28% | -67.38% | -0.9540 | -1.63 | $3575.00 |
| `EW4` | -73.36% | -75.20% | -0.9755 | -1.68 | $2666.62 |
| `EW4_BUY_AND_HOLD` | -69.48% | -72.09% | -0.9638 | -1.59 | $3055.00 |
| `TREND_GATE_BTC` | -37.37% | -43.92% | -0.8507 | -1.26 | $6265.57 |
| `TREND_GATE_EW4` | -50.30% | -52.12% | -0.9649 | -1.46 | $4973.25 |
| `VOL_TARGET_BTC` | -47.44% | -49.54% | -0.9576 | -1.80 | $5259.16 |
| `VOL_TARGET_EW4` | -56.55% | -59.44% | -0.9514 | -1.87 | $4348.04 |
| `MOMENTUM_TOP1` | -77.11% | -78.11% | -0.9873 | -1.74 | $2291.21 |
| `MOMENTUM_TOP1_TREND_GATE` | -55.82% | -57.63% | -0.9686 | -1.39 | $4421.28 |
| `MOMENTUM_TOP2` | -78.49% | -79.75% | -0.9841 | -1.89 | $2153.97 |
| `MOMENTUM_TOP2_TREND_GATE` | -64.32% | -65.43% | -0.9830 | -1.81 | $3571.21 |
| `INVERSE_VOL4` | -69.11% | -70.99% | -0.9736 | -1.58 | $3091.92 |
| `INVERSE_VOL4_TREND_GATE` | -45.16% | -47.13% | -0.9583 | -1.35 | $5486.23 |

### 3.2. 2023 Recovery / Chop Window

| Policy | 2023 CAGR | 2023 Max DD | 2023 Calmar | 2023 Sharpe | 2023 Terminal ($) |
|---|---:|---:|---:|---:|---:|
| `CASH_100` | 0.00% | 0.00% | 0.0000 | 0.00 | $10000.00 |
| `BTC_BH` | 155.50% | -21.74% | 7.1525 | 2.21 | $25531.07 |
| `EW4` | 223.01% | -29.74% | 7.4983 | 2.27 | $32270.73 |
| `EW4_BUY_AND_HOLD` | 298.27% | -30.75% | 9.6988 | 2.33 | $39783.32 |
| `TREND_GATE_BTC` | 33.83% | -27.05% | 1.2504 | 0.91 | $13379.59 |
| `TREND_GATE_EW4` | 39.50% | -38.81% | 1.0177 | 0.82 | $13945.81 |
| `VOL_TARGET_BTC` | 105.64% | -23.83% | 4.4339 | 2.10 | $20552.01 |
| `VOL_TARGET_EW4` | 151.21% | -30.08% | 5.0271 | 2.21 | $25102.72 |
| `MOMENTUM_TOP1` | 280.66% | -49.46% | 5.6748 | 1.72 | $38025.30 |
| `MOMENTUM_TOP1_TREND_GATE` | 120.69% | -49.78% | 2.4247 | 1.11 | $22055.26 |
| `MOMENTUM_TOP2` | 198.23% | -38.54% | 5.1435 | 1.93 | $29797.31 |
| `MOMENTUM_TOP2_TREND_GATE` | 47.25% | -44.56% | 1.0605 | 0.80 | $14720.62 |
| `INVERSE_VOL4` | 132.70% | -28.59% | 4.6414 | 1.85 | $23254.37 |
| `INVERSE_VOL4_TREND_GATE` | 17.84% | -38.45% | 0.4640 | 0.47 | $11782.38 |

## 4. Factorial Attribution (Timing vs Rotation vs Interaction)

- **Base Risky Asset (EW4) CAGR:** `-7.22%`
- **Standalone Cash Timing Contribution (TREND_GATE_EW4 - EW4):** `-9.51%`
- **Standalone Relative Rotation Contribution (MOMENTUM_TOP2 - EW4):** `-12.70%`
- **Combined Joint Policy (MOMENTUM_TOP2_TREND_GATE - EW4):** `-20.29%`
- **Non-Linear Interaction & Turnover Friction Cost:** `+1.92%`

### Interpretation of Attribution
- **Regime Asymmetry:** In 2022 bear market, cash timing provided strong downside protection (e.g. `TREND_GATE_BTC` -37.37% vs `BTC_BH` -64.28%). However, in 2023 chop/recovery, weekly 168h trend gating lagged the sharp recoveries (33.83% vs 155.50%), leading to net negative incremental CAGR across the full 2-year cycle for weekly cadence.
- **Rotation Turnover Drag:** Unconstrained relative momentum rotation incurred high turnover (up to 34.5x/yr) in choppy sideways conditions, compounding fee drag and lagging equal-weight allocations.

## 5. Systematic Sensitivity Matrices

### 5.1. Fee Drag Sensitivity (10 bps vs 20 bps vs 30 bps)

| Policy | 10 bps CAGR | 20 bps CAGR | 30 bps CAGR | Drop (10->30 bps) |
|---|---:|---:|---:|---:|
| `CASH_100` | 0.00% | 0.00% | 0.00% | +0.00% |
| `BTC_BH` | -4.40% | -4.45% | -4.50% | -0.10% |
| `EW4` | -7.19% | -7.34% | -7.48% | -0.29% |
| `EW4_BUY_AND_HOLD` | -17.24% | -17.28% | -17.32% | -0.08% |
| `TREND_GATE_BTC` | -7.98% | -10.30% | -12.56% | -4.58% |
| `TREND_GATE_EW4` | -16.30% | -18.43% | -20.51% | -4.21% |
| `VOL_TARGET_BTC` | 4.17% | 3.39% | 2.62% | -1.55% |
| `VOL_TARGET_EW4` | 4.67% | 3.88% | 3.09% | -1.59% |
| `MOMENTUM_TOP1` | -5.34% | -11.97% | -18.13% | -12.79% |
| `MOMENTUM_TOP1_TREND_GATE` | -0.51% | -4.17% | -7.70% | -7.19% |
| `MOMENTUM_TOP2` | -19.02% | -23.41% | -27.56% | -8.54% |
| `MOMENTUM_TOP2_TREND_GATE` | -26.98% | -29.60% | -32.13% | -5.15% |
| `INVERSE_VOL4` | -15.06% | -15.55% | -16.04% | -0.98% |
| `INVERSE_VOL4_TREND_GATE` | -19.18% | -21.34% | -23.44% | -4.26% |

### 5.2. Rebalancing Cadence Sensitivity (Weekly vs Daily)

| Policy | Weekly Sunday CAGR | Daily Rebalance CAGR | Difference |
|---|---:|---:|---:|
| `CASH_100` | 0.00% | 0.00% | +0.00% |
| `BTC_BH` | -4.41% | -4.41% | +0.00% |
| `EW4` | -7.22% | -10.30% | -3.08% |
| `EW4_BUY_AND_HOLD` | -17.24% | -17.24% | +0.00% |
| `TREND_GATE_BTC` | -8.45% | 19.11% | +27.56% |
| `TREND_GATE_EW4` | -16.73% | 32.10% | +48.83% |
| `VOL_TARGET_BTC` | 4.01% | 5.47% | +1.46% |
| `VOL_TARGET_EW4` | 4.51% | 5.97% | +1.46% |
| `MOMENTUM_TOP1` | -6.71% | 21.41% | +28.12% |
| `MOMENTUM_TOP1_TREND_GATE` | -1.25% | 79.28% | +80.54% |
| `MOMENTUM_TOP2` | -19.92% | 6.49% | +26.41% |
| `MOMENTUM_TOP2_TREND_GATE` | -27.51% | 48.35% | +75.86% |
| `INVERSE_VOL4` | -15.16% | -15.34% | -0.18% |
| `INVERSE_VOL4_TREND_GATE` | -19.61% | 22.96% | +42.58% |

### 5.3. No-Trade Band Sensitivity (0% vs 5% vs 10%)

| Policy | 0% Band (Continuous) | 5% Band (Primary) | 10% Band (Wide) |
|---|---:|---:|---:|
| `CASH_100` | 0.00% | 0.00% | 0.00% |
| `BTC_BH` | -4.41% | -4.41% | -4.41% |
| `EW4` | -9.86% | -7.22% | -6.83% |
| `EW4_BUY_AND_HOLD` | -17.24% | -17.24% | -17.24% |
| `TREND_GATE_BTC` | -8.45% | -8.45% | -8.45% |
| `TREND_GATE_EW4` | -17.04% | -16.73% | -16.60% |
| `VOL_TARGET_BTC` | 4.25% | 4.01% | 4.58% |
| `VOL_TARGET_EW4` | 4.50% | 4.51% | 6.07% |
| `MOMENTUM_TOP1` | -6.71% | -6.71% | -6.71% |
| `MOMENTUM_TOP1_TREND_GATE` | -1.25% | -1.25% | -1.25% |
| `MOMENTUM_TOP2` | -20.05% | -19.92% | -20.80% |
| `MOMENTUM_TOP2_TREND_GATE` | -27.66% | -27.51% | -27.74% |
| `INVERSE_VOL4` | -15.63% | -15.16% | -14.92% |
| `INVERSE_VOL4_TREND_GATE` | -19.85% | -19.61% | -18.65% |

## 6. Pre-Registered Gate Audit Table

| Policy | Capital Preserved? | MaxDD <= 65% BTC? | Calmar > BTC? | Active Participation? | Survives 20 bps Stress? | Gate Verdict |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| `EW4` | False | False | False | True | False | FAIL |
| `TREND_GATE_BTC` | False | False | False | True | False | FAIL |
| `TREND_GATE_EW4` | False | False | False | True | False | FAIL |
| `VOL_TARGET_BTC` | True | False | True | True | False | FAIL |
| `VOL_TARGET_EW4` | True | False | True | True | False | FAIL |
| `MOMENTUM_TOP1` | False | False | False | True | False | FAIL |
| `MOMENTUM_TOP1_TREND_GATE` | False | False | True | True | False | FAIL |
| `MOMENTUM_TOP2` | False | False | False | True | False | FAIL |
| `MOMENTUM_TOP2_TREND_GATE` | False | False | False | True | False | FAIL |
| `INVERSE_VOL4` | False | False | False | True | False | FAIL |
| `INVERSE_VOL4_TREND_GATE` | False | False | False | True | False | FAIL |

## 7. Conclusions & Research Recommendations for S5-P1

1. **Primary Economic Verdict:** **`S5_P0_NO_DEMONSTRATED_OPPORTUNITY`**
2. **Zero Qualifying Policies:** None of the 11 active candidate policies met all four pre-registered primary gate criteria simultaneously under the primary configuration (Weekly Sunday, 5% band, 12 bps).
3. **Cadence Latency as Primary Failure Mode:** Under the weekly Sunday rebalancing schedule, the 7-day decision latency caused significant delay in exiting risk assets during sharp deleveraging events (e.g. May/June 2022, Nov 2022) and entering during explosive rallies (Jan/Oct 2023). Consequently, no weekly policy compressed MaxDD below the pre-registered 65% BTC threshold (-43.80%).
4. **Cadence Sensitivity Contrast:** The systematic sensitivity grid revealed that daily rebalancing dramatically mitigates this latency lag (e.g., `MOMENTUM_TOP1_TREND_GATE` CAGR increased from -1.25% weekly to +79.28% daily, and `TREND_GATE_EW4` increased from -16.73% to +32.10%), demonstrating that the economic edge is heavily conditioned on decision frequency.
5. **Recommendation for S5 Research:** Under the strictly frozen weekly Sunday pre-registration, there is NO demonstrated economic opportunity justifying an expensive Unified Neural Policy (S5-P1). Any future research must rigorously address the rebalancing cadence boundary before considering neural policy architectures.
6. **Boundary Reminder:** This evaluation is strictly bounded to the 2022–2023 development period. It does not grant live production promotion, does not unlock 2024–2026 data, and does not authorize neural training.
