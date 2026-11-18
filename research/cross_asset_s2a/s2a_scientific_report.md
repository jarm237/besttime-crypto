# S2-A — Cross-Asset Selection vs Cash-Timing Opportunity Screen Report

**Repository:** `jarm237/besttime-crypto`
**Branch:** `research/s2a-cross-asset-opportunity-screen`
**Git Checkpoint:** `6613c4eb889b1244e544db49a21b23a08b6daca3`
**Generated At:** `2026-11-18T11:32:03.104279+00:00`
**Initial Capital:** `$10,000.00` | **Fee Model:** 12 bps Base / 30 bps Stress
**Decision Cadence:** Daily (00:00 UTC execution after completed UTC day $t$)
**Calibrated Buffer:** 2.0% divergence threshold

---

## 1. Executive Summary & Canonical Verdict

S2-A investigates whether cross-asset selection and cash-timing mechanisms create incremental economic value after transaction fees in a 4-asset spot crypto portfolio (`BTC`, `ETH`, `SOL`, `BNB`), before deciding whether to authorize neural architecture experiments (S2-B).

```text
========================================================================================
S2A_CROSS_ASSET_ALLOCATION_OPPORTUNITY = NOT_SUPPORTED
S2B_NEURAL_PILOT_AUTHORIZATION         = NOT_AUTHORIZED
PRODUCTION_PROMOTION                   = NOT_AUTHORIZED
OVERALL_CONCLUSION                     = CROSS_ASSET_ALLOCATION_NOT_SUPPORTED
========================================================================================
```

### Empirical Answers to Core Scientific Questions:

1. **Cross-Asset Selection Value ($D - C$):**
   - **Validation 2024:** Net delta = `-15.64%` ($+31.71\%$ vs $+47.35\%$). Selection underperforms static equal-weight by **-15.64%** due to severe rebalancing friction and chasing altcoin momentum that repeatedly reversed back into Bitcoin.
   - **Full Horizon:** Net delta = `-1.47%` ($+44.47\%$ vs $+45.94\%$), incurring **$5,429.63** in transaction fees (127.98x turnover).
   - **Verdict:** Cross-asset selection does **NOT** produce incremental economic value after fees.

2. **Cash/Exposure Timing Value ($E - C$):**
   - **Validation 2024:** Net delta = `+5.44%` ($+52.79\%$ vs $+47.35\%$). While raw return was slightly higher during the strong 2024 bull run, the annualized Sharpe ratio degraded from **1.43 to 1.22**, and turnover cost **$1,088.66** in execution drag.
   - **Reused Diagnostic (2025–2026):** Timing suffered severe whipsaws (**-34.90%** vs **-15.45%** for Static 50/50).
   - **Verdict:** Exposure timing does **NOT** provide robust, fee-resilient risk-adjusted outperformance.

3. **Combined Policy ($F - \max(D, E, C)$):**
   - **Validation 2024:** Net delta = `-18.62%` ($+34.17\%$ vs $+52.79\%$).
   - **Stress 30 bps (Validation 2024):** Policy F collapses to **+3.55%** (Sharpe 0.30) compared to Static 50/50's **+47.05%** (Sharpe 1.43).
   - **Full Horizon:** Policy F generated **884 rebalances** with **250.16x gross turnover**, burning **$11,382.36** in transaction fees at 12 bps (and collapsing to **-55.93%** / **$15,109.10 fees** at 30 bps).
   - **Verdict:** Combining daily selection with exposure timing creates catastrophic turnover friction that completely erodes alpha.

---

## 2. Policy Performance Comparison Across Splits

### Validation 2024 (Primary Diagnostic Horizon)

| Policy | Net Return (12 bps) | Net Return (30 bps) | Sharpe (12 bps) | Max Drawdown | Trades | Turnover (Gross) | Total Fees (12 bps) | Mean Cash W |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **A. BTC Buy & Hold** | +121.04% | +120.64% | 1.76 | -32.31% | 1 | 1.00x | $12.00 | 0.0% |
| **B. EW 4-Asset Buy & Hold** | +94.48% | +94.13% | 1.40 | -37.88% | 1 | 1.00x | $12.00 | 0.0% |
| **C. Static 50/50 EW** | **+47.35%** | **+47.05%** | **1.43** | **-19.23%** | 16 | 1.11x | $15.41 | 49.7% |
| **D. Selection Top-2** | +31.71% | +16.57% | 1.03 | -23.77% | 143 | 67.79x | $964.16 | 49.9% |
| **E. Timing Breadth** | +52.79% | +35.54% | 1.22 | -22.09% | 125 | 66.49x | $1088.66 | 37.0% |
| **F. Combined Top-2** | +34.17% | +3.55% | 0.87 | -29.13% | 199 | 143.65x | $2233.22 | 37.0% |

### Full Horizon (2022–2026)

| Policy | Net Return (12 bps) | Net Return (30 bps) | Sharpe (12 bps) | Max Drawdown | Trades | Total Fees (12 bps) | Total Fees (30 bps) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **A. BTC Buy & Hold** | +71.25% | +70.94% | 0.49 | -67.38% | 1 | $12.00 | $30.00 |
| **C. Static 50/50 EW** | **+45.94%** | **+44.94%** | **0.42** | **-44.90%** | 79 | $54.67 | $136.14 |
| **D. Selection Top-2** | +44.47% | -19.16% | 0.41 | -44.99% | 667 | $5429.63 | $9888.73 |
| **E. Timing Breadth** | +5.88% | -43.68% | 0.24 | -58.95% | 626 | $4615.65 | $8199.57 |
| **F. Combined Top-2** | +40.84% | -55.93% | 0.40 | -56.01% | 884 | $11382.36 | $15109.10 |

---

## 3. Economic Attribution Decomposition

Attribution formulas:
- $\Delta_D = D - C$ (Cross-Asset Selection Value at fixed 50% exposure)
- $\Delta_E = E - C$ (Cash/Exposure Timing Value at fixed equal-weight sleeve)
- $\Delta_F = F - \max(D, E, C)$ (Combined Incremental Interaction Value)

| Split Horizon | Selection Value ($D - C$) | Timing Value ($E - C$) | Combined Value ($F - \max(D,E,C)$) | F vs Static ($F - C$) | Strongest Control |
| :--- | :---: | :---: | :---: | :---: | :--- |
| **Train (2022–2023)** | +22.21% | -10.62% | +9.77% | +31.98% | Policy D (+39.26%) |
| **Validation (2024)** | **-15.64%** | **+5.44%** | **-18.62%** | **-13.18%** | Policy E (+52.79%) |
| **Reused (2025–2026)** | -5.86% | -19.45% | -14.12% | -14.12% | Policy C (-15.45%) |
| **Full Horizon (2022–2026)** | -1.47% | -40.06% | -5.10% | -5.10% | Policy C (+45.94%) |

---

## 4. Sub-Regime Analysis

| Market Regime | Period | Policy A (BTC) | Policy C (Static 50/50) | Policy D (Selection) | Policy E (Timing) | Policy F (Combined) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **2022 Bear Market** | 2022-01-31 to 2022-12-31 | -56.09% | -38.25% | -36.40% | -37.89% | -39.12% |
| **2023 Recovery** | 2023-01-01 to 2023-12-31 | +154.21% | +89.57% | +119.01% | +71.35% | +144.78% |
| **2024 Bull Market** | 2024-01-01 to 2024-12-31 | +121.04% | +47.35% | +31.71% | +52.79% | +34.17% |
| **2025–2026 Reused Diagnostic** | 2025-01-01 to 2026-11-16 | -30.68% | -15.45% | -21.31% | -34.90% | -29.57% |

---

## 5. Statistical Falsification Suite

### A. Temporal Shuffle & Cross-Sectional Permutations
- **Temporal Shuffle Timing Control (100 runs):**
  - Shuffled Mean Return: `+33.79%` (Std: `27.92%`)
  - Range: `[-30.68%, +120.81%]`
- **Cross-Sectional Rank Permutation Selection Control (100 runs):**
  - Permuted Mean Return: `+18.14%` (Std: `11.54%`)
  - Range: `[-17.16%, +48.87%]`
- **Static Exposure-Matched Control for E (Mean Exposure 63.0%):**
  - Net Return: `+61.08%` | Sharpe: `1.44` | Fees: `$23.81`

### B. Paired Block Bootstrap (Validation 2024 Daily Return Differences)
- **Policy F vs Policy C ($F - C$):**
  - Mean Daily Difference: `-0.000093`
  - 95% Bootstrap CI: `[-0.001437, +0.001729]`
  - Covers Zero: **`True`** (Statistically insignificant / fails to demonstrate outperformance).
- **Policy D vs Policy C ($D - C$):**
  - 95% Bootstrap CI: `[-0.000800, +0.000356]`
  - Covers Zero: **`True`**
- **Policy E vs Policy C ($E - C$):**
  - 95% Bootstrap CI: `[-0.000936, +0.001646]`
  - Covers Zero: **`True`**

---

## 6. S2-B Neural Pilot Gate Audit

| Gate Condition | Required Threshold | Observed Value | Verdict |
| :--- | :--- | :--- | :---: |
| **1. Outperform Strongest Non-Neural Baseline (Val 2024 @ 12 bps)** | $F > \max(C, E) = +52.79\%$ | $F = +34.17\%$ | **FAILED** |
| **2. Incremental Net Return Positive @ 30 bps Stress** | $F_{30} - C_{30} > 0\%$ | $F_{30} - C_{30} = -43.50\%$ ($+3.55\%$ vs $+47.05\%$) | **FAILED** |
| **3. Risk-Adjusted Quality Improved** | Sharpe $> 1.43$ or MaxDD $< -19.23\%$ | Sharpe $= 0.87$, MaxDD $= -29.13\%$ | **FAILED** |
| **4. Distinct Mechanisms Demonstrate Independent Value** | $\Delta_D > 0$ and $\Delta_E > 0$ | $\Delta_D = -15.64\%$, $\Delta_E = +5.44\%$ (Sharpe degraded) | **FAILED** |
| **5. Statistically Significant vs Controls** | Bootstrap 95% CI strictly $> 0$ | 95% CI covers zero | **FAILED** |
| **6. Non-Trivial Asset Contribution** | Not driven by single asset/decision | Multi-asset participation (BTC/SOL/ETH/BNB active) | **PASS** |

### Authorization Decision:
All 5 out of 6 quantitative gates failed. Policy F fails to beat passive static allocation after realistic spot transaction friction.

```text
S2A_CROSS_ASSET_ALLOCATION_OPPORTUNITY = NOT_SUPPORTED
S2B_NEURAL_PILOT_AUTHORIZATION         = NOT_AUTHORIZED
PRODUCTION_PROMOTION                   = NOT_AUTHORIZED
```

---

## 7. Hard Stop & Research Next Steps

In strict accordance with the experiment specification:
- S2-A research is **CONCLUDED**.
- **No** S2-B neural network training is authorized.
- **No** modifications to live production trading or CARM observer components.
