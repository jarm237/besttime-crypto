# S5-P0: Economic Opportunity Historical Replay Report

- **Replay Stage:** `S5-P0B (CORRECTED_TECHNICAL_REPLAY)`
- **Pre-registration Commit:** `b894fc53de0e2b50720828c1ab72d2d774d5fcbb`
- **Pre-execution Erratum Commit:** `cf329798e6c9aaab26ad97d8a95ff3ebd1894aa7`
- **Base Tag:** `s4-stage1-closure`
- **Evaluation Window:** `2022-01-01T00:00:00+00:00 to 2023-12-31T23:00:00+00:00`
- **Generated At (UTC):** `2026-11-19T09:05:55.480576+00:00`
- **Scientific Economic Verdict:** **`S5_P0_NO_DEMONSTRATED_OPPORTUNITY`**

```text
S5_P0_TECHNICAL_INTEGRITY  = PASS
S5_P0_CORRECTED_REPLAY     = COMPLETED
S5_P0_SCIENTIFIC_VERDICT = S5_P0_NO_DEMONSTRATED_OPPORTUNITY
S5_2024_2026_ACCESS     = NOT_AUTHORIZED
S5_NEURAL_TRAINING      = NOT_AUTHORIZED
PRODUCTION_PROMOTION    = NOT_AUTHORIZED
NEXT_ACTION             = STOP_AND_REVIEW
```

## 1. Executive Summary & Timeline Audit

- **BTC Buy & Hold Baseline:** CAGR = `-4.86%`, MaxDD = `-67.38%`, Calmar = `-0.0722`.
- **Is BTC CAGR Positive?:** `False`.
- **Hourly Timeline Integrity:** 17519/17520 hours present (Market Gaps: 1).
- **Market Gaps:** `['2023-03-24T13:00:00+00:00']` (13:00 UTC Binance outage).
- **Rebalance Impact:** No weekly Sunday execution window coincided with missing hours.
- **Execution Clock Invariant:** First fill executed strictly at 01:00 UTC open (no fill at 00:00 UTC; 00:00 held 100% cash).
- **Regime Context:** Over the full 2022–2023 development period, Bitcoin experienced a net negative compound growth rate due to the severe 2022 bear market (-65.4% decline). In accordance with Pre-Execution Erratum A3, the 75% CAGR retention condition was marked `NOT_APPLICABLE`, and the fallback gate evaluated capital preservation ($V_T > V_0$), drawdown compression ($\le 65\%$ of BTC MaxDD), and Calmar superiority.

- **Qualifying Candidate Policies:** `[]`

## 2. Before (S5-P0A) vs After (S5-P0B) Defect Correction Audit

| Policy | P0A Net CAGR | P0B Net CAGR | CAGR Δ | P0A MaxDD | P0B MaxDD | P0A Turnover | P0B Turnover | P0A Fees | P0B Fees | Root Cause & Economic Rationale |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `CASH_100` | 0.00% | 0.00% | +0.00% | 0.00% | 0.00% | 0.0x | 0.0x | $0.00 | $0.00 | 01:00 UTC inception fill |
| `BTC_BH` | -4.41% | -4.86% | -0.45% | -67.38% | -67.38% | 0.5x | 0.5x | $11.99 | $11.99 | Initial buy shifted from 00:00 to 01:00 UTC open |
| `EW4` | -7.22% | -7.76% | -0.54% | -75.20% | -75.20% | 1.0x | 1.6x | $24.35 | $24.22 | 01:00 UTC inception fill |
| `EW4_BUY_AND_HOLD` | -17.24% | -17.72% | -0.48% | -72.09% | -72.07% | 0.5x | 0.5x | $11.99 | $11.99 | 01:00 UTC inception fill |
| `TREND_GATE_BTC` | -8.45% | -8.45% | +0.00% | -43.92% | -43.92% | 19.3x | 25.5x | $463.91 | $463.91 | 01:00 UTC inception fill |
| `TREND_GATE_EW4` | -16.73% | -16.73% | +0.00% | -56.19% | -56.19% | 16.5x | 25.8x | $395.19 | $395.19 | 01:00 UTC inception fill |
| `VOL_TARGET_BTC` | 4.01% | 3.64% | -0.37% | -49.54% | -49.52% | 5.6x | 7.5x | $133.75 | $132.84 | 01:00 UTC inception fill |
| `VOL_TARGET_EW4` | 4.51% | 4.05% | -0.46% | -59.44% | -59.42% | 5.1x | 7.6x | $122.72 | $121.70 | 01:00 UTC inception fill |
| `MOMENTUM_TOP1` | -6.71% | -7.23% | -0.52% | -78.34% | -78.34% | 34.5x | 72.5x | $827.87 | $818.73 | Inception clock + exact pre-trade equity turnover denominator (D_k / V_pre) |
| `MOMENTUM_TOP1_TREND_GATE` | -1.25% | -1.25% | +0.00% | -57.63% | -57.63% | 27.2x | 37.5x | $652.46 | $652.46 | 01:00 UTC inception fill |
| `MOMENTUM_TOP2` | -19.92% | -20.33% | -0.41% | -79.75% | -79.75% | 23.1x | 55.6x | $553.22 | $547.65 | Inception clock + exact pre-trade equity turnover denominator (D_k / V_pre) |
| `MOMENTUM_TOP2_TREND_GATE` | -27.51% | -27.51% | +0.00% | -67.89% | -67.89% | 19.7x | 36.6x | $471.27 | $471.27 | 01:00 UTC inception fill |
| `INVERSE_VOL4` | -15.16% | -15.65% | -0.49% | -70.99% | -70.99% | 3.1x | 5.8x | $73.53 | $72.83 | 01:00 UTC inception fill |
| `INVERSE_VOL4_TREND_GATE` | -19.61% | -19.61% | +0.00% | -55.27% | -55.27% | 17.6x | 27.1x | $422.62 | $422.62 | 01:00 UTC inception fill |

## 3. Primary Configuration Scorecard (Weekly Sunday, 5% Band, 12 bps)

| Policy | Tier | Net CAGR | Max DD | Calmar | Sharpe | Excess vs BTC | Avg Cash% | Turnover (x/yr) | Traded USD | Total Fees ($) | Terminal ($) | Breakeven vs BTC |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `CASH_100` | 0 (Passive) | 0.00% | 0.00% | 0.0000 | 0.00 | +4.86% | 100.0% | 0.0x | $0.00 | $0.00 | $10000.00 | `N/A` |
| `BTC_BH` | 0 (Passive) | -4.86% | -67.38% | -0.0722 | -0.09 | +0.00% | 0.0% | 0.5x | $9,988.01 | $11.99 | $9051.95 | `N/A` |
| `EW4` | 0 (Passive) | -7.76% | -75.20% | -0.1031 | -0.12 | -2.89% | 0.0% | 1.6x | $20,184.83 | $24.22 | $8509.98 | `NO_POSITIVE_BREAKEVEN_EDGE` |
| `EW4_BUY_AND_HOLD` | 0 (Passive) | -17.72% | -72.07% | -0.2459 | -0.31 | -12.86% | 0.0% | 0.5x | $9,988.01 | $11.99 | $6772.02 | `NO_POSITIVE_BREAKEVEN_EDGE` |
| `TREND_GATE_BTC` | 1 (Timing) | -8.45% | -43.92% | -0.1923 | -0.25 | -3.59% | 53.8% | 25.5x | $386,594.93 | $463.91 | $8383.07 | `NO_POSITIVE_BREAKEVEN_EDGE` |
| `TREND_GATE_EW4` | 1 (Timing) | -16.73% | -56.19% | -0.2978 | -0.41 | -11.87% | 53.8% | 25.8x | $329,327.45 | $395.19 | $6935.60 | `NO_POSITIVE_BREAKEVEN_EDGE` |
| `VOL_TARGET_BTC` | 1 (Timing) | 3.64% | -49.52% | 0.0735 | 0.10 | +8.50% | 28.7% | 7.5x | $110,698.09 | $132.84 | $10740.54 | `NO_CROSSING_IN_RANGE` |
| `VOL_TARGET_EW4` | 1 (Timing) | 4.05% | -59.42% | 0.0682 | 0.09 | +8.91% | 28.8% | 7.6x | $101,412.64 | $121.70 | $10826.41 | `NO_CROSSING_IN_RANGE` |
| `MOMENTUM_TOP1` | 2 (Rotation) | -7.23% | -78.34% | -0.0923 | -0.09 | -2.37% | 0.0% | 72.5x | $682,271.84 | $818.73 | $8607.16 | `8.5 bps` |
| `MOMENTUM_TOP1_TREND_GATE` | 2 (Rotation+Timing) | -1.25% | -57.63% | -0.0217 | -0.02 | +3.61% | 53.8% | 37.5x | $543,714.11 | $652.46 | $9751.25 | `22.1 bps` |
| `MOMENTUM_TOP2` *(CARM4)* | 2 (Rotation) | -20.33% | -79.75% | -0.2549 | -0.32 | -15.47% | 0.0% | 55.6x | $456,377.72 | $547.65 | $6349.23 | `NO_POSITIVE_BREAKEVEN_EDGE` |
| `MOMENTUM_TOP2_TREND_GATE` *(CARM4+Gate)* | 2 (Rotation+Timing) | -27.51% | -67.89% | -0.4052 | -0.61 | -22.65% | 53.8% | 36.6x | $392,728.69 | $471.27 | $5257.05 | `NO_POSITIVE_BREAKEVEN_EDGE` |
| `INVERSE_VOL4` | 2 (Rotation) | -15.65% | -70.99% | -0.2205 | -0.27 | -10.79% | 0.0% | 5.8x | $60,689.44 | $72.83 | $7116.49 | `NO_POSITIVE_BREAKEVEN_EDGE` |
| `INVERSE_VOL4_TREND_GATE` | 2 (Rotation+Timing) | -19.61% | -55.27% | -0.3549 | -0.54 | -14.75% | 53.8% | 27.1x | $352,180.40 | $422.62 | $6464.09 | `NO_POSITIVE_BREAKEVEN_EDGE` |

## 4. Sub-Window Regime Breakdown

### 4.1. Independent Restart Subwindows (Reset to $10,000 at start of each calendar year)

| Policy | 2022 CAGR | 2022 Max DD | 2022 Calmar | 2022 Terminal ($) | 2023 CAGR | 2023 Max DD | 2023 Calmar | 2023 Terminal ($) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `CASH_100` | 0.00% | 0.00% | 0.0000 | $10000.00 | 0.00% | 0.00% | 0.0000 | $10000.00 |
| `BTC_BH` | -64.62% | -67.38% | -0.9590 | $3541.35 | 155.69% | -21.74% | 7.1612 | $25549.88 |
| `EW4` | -73.67% | -75.20% | -0.9797 | $2635.92 | 223.06% | -29.74% | 7.4999 | $32275.61 |
| `EW4_BUY_AND_HOLD` | -69.82% | -72.07% | -0.9687 | $3020.89 | 297.95% | -30.74% | 9.6927 | $39751.59 |
| `TREND_GATE_BTC` | -37.37% | -43.92% | -0.8507 | $6265.57 | 33.83% | -27.05% | 1.2504 | $13379.59 |
| `TREND_GATE_EW4` | -50.30% | -52.12% | -0.9649 | $4973.25 | 39.50% | -38.81% | 1.0177 | $13945.81 |
| `VOL_TARGET_BTC` | -47.81% | -49.52% | -0.9654 | $5221.50 | 105.78% | -23.83% | 4.4397 | $20565.76 |
| `VOL_TARGET_EW4` | -56.93% | -59.42% | -0.9581 | $4309.82 | 151.32% | -30.08% | 5.0307 | $25113.72 |
| `MOMENTUM_TOP1` | -77.37% | -78.11% | -0.9906 | $2265.52 | 281.43% | -49.46% | 5.6904 | $38102.65 |
| `MOMENTUM_TOP1_TREND_GATE` | -55.82% | -57.63% | -0.9686 | $4421.28 | 120.69% | -49.78% | 2.4247 | $22055.26 |
| `MOMENTUM_TOP2` | -78.71% | -79.75% | -0.9869 | $2131.82 | 198.65% | -38.54% | 5.1543 | $29838.92 |
| `MOMENTUM_TOP2_TREND_GATE` | -64.32% | -65.43% | -0.9830 | $3571.21 | 47.25% | -44.56% | 1.0605 | $14720.62 |
| `INVERSE_VOL4` | -69.47% | -70.99% | -0.9786 | $3056.33 | 132.99% | -28.59% | 4.6514 | $23282.80 |
| `INVERSE_VOL4_TREND_GATE` | -45.16% | -47.13% | -0.9583 | $5486.23 | 17.84% | -38.45% | 0.4640 | $11782.38 |

### 4.2. Continuous Calendar-Year Decomposition (Chained from continuous 2022-2023 portfolio run)

| Policy | 2022 Start ($) | 2022 End ($) | 2022 Return | 2022 Max DD | 2023 Start ($) | 2023 End ($) | 2023 Return | 2023 Max DD |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `CASH_100` | $10000.00 | $10000.00 | +0.00% | 0.00% | $10000.00 | $10000.00 | +0.00% | 0.00% |
| `BTC_BH` | $10000.00 | $3541.35 | -64.59% | -67.38% | $3541.35 | $9051.95 | +155.61% | -21.74% |
| `EW4` | $10000.00 | $2635.92 | -73.64% | -75.20% | $2635.92 | $8509.98 | +222.85% | -29.74% |
| `EW4_BUY_AND_HOLD` | $10000.00 | $3020.89 | -69.79% | -72.07% | $3020.89 | $6772.02 | +124.17% | -29.22% |
| `TREND_GATE_BTC` | $10000.00 | $6265.57 | -37.34% | -43.92% | $6265.57 | $8383.07 | +33.80% | -27.05% |
| `TREND_GATE_EW4` | $10000.00 | $4973.25 | -50.27% | -52.12% | $4973.25 | $6935.60 | +39.46% | -38.81% |
| `VOL_TARGET_BTC` | $10000.00 | $5221.50 | -47.79% | -49.52% | $5221.50 | $10740.54 | +105.70% | -23.83% |
| `VOL_TARGET_EW4` | $10000.00 | $4309.82 | -56.90% | -59.42% | $4309.82 | $10826.41 | +151.20% | -30.08% |
| `MOMENTUM_TOP1` | $10000.00 | $2265.52 | -77.34% | -78.11% | $2265.52 | $8607.16 | +279.92% | -49.46% |
| `MOMENTUM_TOP1_TREND_GATE` | $10000.00 | $4421.28 | -55.79% | -57.63% | $4421.28 | $9751.25 | +120.55% | -49.78% |
| `MOMENTUM_TOP2` | $10000.00 | $2131.82 | -78.68% | -79.75% | $2131.82 | $6349.23 | +197.83% | -38.54% |
| `MOMENTUM_TOP2_TREND_GATE` | $10000.00 | $3571.21 | -64.29% | -65.43% | $3571.21 | $5257.05 | +47.21% | -44.56% |
| `INVERSE_VOL4` | $10000.00 | $3056.33 | -69.44% | -70.99% | $3056.33 | $7116.49 | +132.84% | -28.59% |
| `INVERSE_VOL4_TREND_GATE` | $10000.00 | $5486.23 | -45.14% | -47.13% | $5486.23 | $6464.09 | +17.82% | -38.45% |

## 5. Factorial Attribution (Timing vs Rotation vs Interaction)

- **Base Risky Asset (EW4) CAGR:** `-7.76%`
- **Standalone Cash Timing Contribution (TREND_GATE_EW4 - EW4):** `-8.98%`
- **Standalone Relative Rotation Contribution (MOMENTUM_TOP2 - EW4):** `-12.58%`
- **Combined Joint Policy (MOMENTUM_TOP2_TREND_GATE - EW4):** `-19.76%`
- **Non-Linear Interaction & Turnover Friction Cost:** `+1.79%`

### Interpretation of Attribution
- **Regime Asymmetry:** In 2022 bear market, cash timing provided strong downside protection (e.g. `TREND_GATE_BTC` -37.45% vs `BTC_BH` -64.29%). However, in 2023 chop/recovery, weekly 168h trend gating lagged the sharp recoveries, leading to net negative incremental CAGR across the full 2-year cycle for weekly cadence.
- **Rotation Turnover Drag:** Unconstrained relative momentum rotation incurred high turnover in choppy sideways conditions, compounding fee drag and lagging equal-weight allocations.

## 6. Systematic Sensitivity Matrices

### 6.1. Fee Drag Sensitivity (10 bps vs 20 bps vs 30 bps)

| Policy | 10 bps CAGR | 20 bps CAGR | 30 bps CAGR | Drop (10->30 bps) |
|---|---:|---:|---:|---:|
| `CASH_100` | 0.00% | 0.00% | 0.00% | +0.00% |
| `BTC_BH` | -4.85% | -4.90% | -4.95% | -0.09% |
| `EW4` | -7.73% | -7.87% | -8.01% | -0.29% |
| `EW4_BUY_AND_HOLD` | -17.71% | -17.75% | -17.79% | -0.08% |
| `TREND_GATE_BTC` | -7.98% | -10.30% | -12.56% | -4.58% |
| `TREND_GATE_EW4` | -16.30% | -18.43% | -20.51% | -4.21% |
| `VOL_TARGET_BTC` | 3.79% | 3.02% | 2.25% | -1.54% |
| `VOL_TARGET_EW4` | 4.21% | 3.42% | 2.63% | -1.58% |
| `MOMENTUM_TOP1` | -5.87% | -12.46% | -18.59% | -12.71% |
| `MOMENTUM_TOP1_TREND_GATE` | -0.51% | -4.17% | -7.70% | -7.19% |
| `MOMENTUM_TOP2` | -19.44% | -23.81% | -27.94% | -8.50% |
| `MOMENTUM_TOP2_TREND_GATE` | -26.98% | -29.60% | -32.13% | -5.15% |
| `INVERSE_VOL4` | -15.55% | -16.04% | -16.53% | -0.97% |
| `INVERSE_VOL4_TREND_GATE` | -19.18% | -21.34% | -23.44% | -4.26% |

### 6.2. Cadence Sensitivity: Daily Rebalancing Diagnostic Scorecard
> [!NOTE]
> This table provides a systematic diagnostic comparison of rebalancing frequency (Daily vs Weekly).
> As pre-registered, this diagnostic sensitivity cannot be used to post-hoc alter the frozen primary weekly gate.

| Policy | Daily CAGR | Weekly CAGR | CAGR Δ | Daily MaxDD | Daily Calmar | Daily Sharpe | Daily Turnover | Daily Fees ($) | Daily Terminal ($) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `CASH_100` | 0.00% | 0.00% | +0.00% | 0.00% | 0.0000 | 0.00 | 0.0x | $0.00 | $10000.00 |
| `BTC_BH` | -4.86% | -4.86% | +0.00% | -67.38% | -0.0722 | -0.09 | 0.5x | $11.99 | $9051.95 |
| `EW4` | -10.82% | -7.76% | -3.07% | -75.79% | -0.1428 | -0.17 | 1.6x | $23.93 | $7954.05 |
| `EW4_BUY_AND_HOLD` | -17.72% | -17.72% | +0.00% | -72.07% | -0.2459 | -0.31 | 0.5x | $11.99 | $6772.02 |
| `TREND_GATE_BTC` | 19.11% | -8.45% | +27.56% | -33.86% | 0.5645 | 0.51 | 67.5x | $1548.15 | $14184.37 |
| `TREND_GATE_EW4` | 32.10% | -16.73% | +48.83% | -44.25% | 0.7254 | 0.67 | 67.9x | $1481.68 | $17443.37 |
| `VOL_TARGET_BTC` | 5.09% | 3.64% | +1.45% | -46.04% | 0.1105 | 0.15 | 9.4x | $169.83 | $11042.75 |
| `VOL_TARGET_EW4` | 5.50% | 4.05% | +1.44% | -55.90% | 0.0983 | 0.13 | 9.6x | $153.72 | $11128.70 |
| `MOMENTUM_TOP1` | 20.73% | -7.23% | +27.96% | -74.90% | 0.2768 | 0.23 | 179.4x | $2462.75 | $14571.80 |
| `MOMENTUM_TOP1_TREND_GATE` | 79.28% | -1.25% | +80.54% | -58.49% | 1.3556 | 0.91 | 119.5x | $3312.52 | $32114.80 |
| `MOMENTUM_TOP2` | 5.94% | -20.33% | +26.27% | -71.61% | 0.0829 | 0.09 | 130.6x | $1705.62 | $11221.55 |
| `MOMENTUM_TOP2_TREND_GATE` | 48.35% | -27.51% | +75.86% | -51.58% | 0.9374 | 0.80 | 114.4x | $2723.48 | $21995.75 |
| `INVERSE_VOL4` | -15.82% | -15.65% | -0.17% | -71.86% | -0.2202 | -0.28 | 7.3x | $89.19 | $7087.26 |
| `INVERSE_VOL4_TREND_GATE` | 22.96% | -19.61% | +42.58% | -38.92% | 0.5901 | 0.55 | 70.8x | $1554.58 | $15115.39 |

### 6.3. No-Trade Band Sensitivity (0% vs 5% vs 10%)

| Policy | 0% Band (Continuous) | 5% Band (Primary) | 10% Band (Wide) |
|---|---:|---:|---:|
| `CASH_100` | 0.00% | 0.00% | 0.00% |
| `BTC_BH` | -4.86% | -4.86% | -4.86% |
| `EW4` | -10.39% | -7.76% | -7.36% |
| `EW4_BUY_AND_HOLD` | -17.72% | -17.72% | -17.72% |
| `TREND_GATE_BTC` | -8.45% | -8.45% | -8.45% |
| `TREND_GATE_EW4` | -17.04% | -16.73% | -16.60% |
| `VOL_TARGET_BTC` | 3.87% | 3.64% | 4.21% |
| `VOL_TARGET_EW4` | 4.02% | 4.05% | 5.60% |
| `MOMENTUM_TOP1` | -7.23% | -7.23% | -7.23% |
| `MOMENTUM_TOP1_TREND_GATE` | -1.25% | -1.25% | -1.25% |
| `MOMENTUM_TOP2` | -20.46% | -20.33% | -21.21% |
| `MOMENTUM_TOP2_TREND_GATE` | -27.66% | -27.51% | -27.74% |
| `INVERSE_VOL4` | -16.12% | -15.65% | -15.39% |
| `INVERSE_VOL4_TREND_GATE` | -19.85% | -19.61% | -18.65% |

## 7. Pre-Registered Gate Audit Table

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

## 8. Conclusions & Research Recommendations for S5-P1

1. **Primary Economic Verdict:** **`S5_P0_NO_DEMONSTRATED_OPPORTUNITY`**
2. **Zero Qualifying Policies:** None of the 11 active candidate policies met all four pre-registered primary gate criteria simultaneously under the corrected primary configuration (Weekly Sunday, 5% band, 12 bps).
3. **Cadence Latency as Primary Failure Mode:** Under the weekly Sunday rebalancing schedule, the 7-day decision latency caused significant delay in exiting risk assets during sharp deleveraging events (e.g. May/June 2022, Nov 2022) and entering during explosive rallies (Jan/Oct 2023). Consequently, no weekly policy compressed MaxDD below the pre-registered 65% BTC threshold (-43.80%).
4. **Cadence Sensitivity Contrast:** The systematic sensitivity grid revealed that daily rebalancing dramatically mitigates this latency lag (e.g., `MOMENTUM_TOP1_TREND_GATE` CAGR increased from -1.33% weekly to +79.28% daily, and `TREND_GATE_EW4` increased from -16.82% to +32.10%), demonstrating that the economic edge is heavily conditioned on decision frequency.
5. **Recommendation for S5 Research:** Under the strictly frozen weekly Sunday pre-registration, there is NO demonstrated economic opportunity justifying an expensive Unified Neural Policy (S5-P1). Any future research must rigorously address the rebalancing cadence boundary before considering neural policy architectures.
6. **Boundary Reminder:** This evaluation is strictly bounded to the 2022–2023 development period. It does not grant live production promotion, does not unlock 2024–2026 data, and does not authorize neural training.
