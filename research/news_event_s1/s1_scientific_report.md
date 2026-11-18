# S1 — News & Event Shock Predictive Opportunity Discovery Report

## 1. Executive Summary & Canonical Verdict

**Repository Commit:** `280cc45a2e7b36389fb5cc2266e9832c71f5a0fc`  
**Evaluation Date:** `2026-11-18 03:46:28 UTC`  
**Research Status:** COMPLETE  

### Final Evidence-Derived Verdicts

- `NEWS_SOURCE_FEASIBILITY`: **`PARTIAL_BOUNDED`**
- `NEWS_PIT_CORRECTNESS`: **`PASS`**
- `NEWS_INCREMENTAL_PREDICTIVE_VALUE`: **`NOT_SUPPORTED`**
- `NEWS_INCREMENTAL_ECONOMIC_VALUE`: **`NOT_SUPPORTED`**
- `S1_OVERALL_CONCLUSION`: **`NEWS_SHOCK_VALUE_NOT_SUPPORTED`**
- `RECOMMENDATION_FOR_UNIFIED_NEURAL_INPUTS`: **`EXCLUDE`**

---

## 2. Hypothesis & Research Scope

> **Hypothesis (S1-H1):** Negative crypto market-wide news/event shocks, collected at their causal availability time, predict subsequent downside risk (24h primary, 72h secondary) and improve long-only spot BTC/cash allocation after transaction costs (12 bps base, 30 bps stress) beyond price/volatility-only controls.

This research was conducted independently under Workstream C, strictly isolating historical PIT data and market replay from prior R4–R11 neural training and D0.1 derivatives research.

---

## 3. Historical Data Source Feasibility & Point-in-Time Integrity

### Ingested Point-in-Time Data Sources
1. **DeFiLlama Crypto Exploits Database (Continuous 2022–2026):**
   - Verified records of crypto security exploits, private key thefts, oracle exploits, and protocol compromises.
   - Continuous coverage with verified USD loss amounts across 2023–2025.
   - **PIT Protocol:** Incident dates are assigned midnight UTC. To eliminate lookahead bias, an explicit **+24 hour publication delay** is applied: `available_at = event_timestamp + 24h`.

2. **GDELT Project 2.0 15-Minute Global Event Archives (Bounded Windows):**
   - Continuous 15-minute global event stream with 14-digit UTC timestamps (`YYYYMMDDHHMMSS`).
   - Sampled across 6 critical market shock regimes (SVB/USDC depeg, SEC regulatory enforcement, flash crash liquidations, spot ETF momentum, split boundary, and Bybit exploit).
   - **PIT Protocol:** Enforced **+1 hour ingestion delay** before decision evaluation.

### PIT Audit Summary
- Total causal checks: **796**
- Passed causal checks: **796** (Ratio: **100.0%**)
- Zero forward-fill / bfill violation: **True**

---

## 4. Statistical Falsification (No Neural Network)

### Primary Target: 24h Downside Return (< -2.0%)

| Model | Train PR-AUC | Val PR-AUC | Val ROC-AUC | Val Brier Score | Val Brier Skill Score |
| :--- | :---: | :---: | :---: | :---: | :---: |
| `Price_Vol_Baseline` | 0.1664 | 0.2520 | 0.5976 | 0.1191 | 0.0194 |
| `News_Only` | 0.2295 | 0.2296 | 0.4594 | 0.1218 | -0.0027 |
| `Combined_Price_News` | 0.1636 | 0.2265 | 0.5871 | 0.1195 | 0.0161 |
| `Negative_Control_Shifted` | 0.1680 | 0.2508 | 0.5957 | 0.1191 | 0.0193 |
| `Negative_Control_Placebo` | 0.1735 | 0.2334 | 0.5808 | 0.1196 | 0.0149 |

- **Incremental Val PR-AUC (Combined - Price/Vol):** `-0.0255`
- **100-Run Block Permutation Test p-value:** `0.9604`
- **1,000-Run Paired Block Bootstrap 95% CI:** `[-0.0671, +0.0028]` (Covers zero: `True`)

### Secondary Target: 72h Downside Return (< -4.0%)

| Model | Train PR-AUC | Val PR-AUC | Val ROC-AUC | Val Brier Score | Val Brier Skill Score |
| :--- | :---: | :---: | :---: | :---: | :---: |
| `Price_Vol_Baseline` | 0.1344 | 0.0898 | 0.4925 | 0.0839 | -0.0031 |
| `News_Only` | 0.1210 | 0.0750 | 0.4737 | 0.0841 | -0.0054 |
| `Combined_Price_News` | 0.1279 | 0.1002 | 0.5136 | 0.0841 | -0.0061 |
| `Negative_Control_Shifted` | 0.1311 | 0.0999 | 0.5467 | 0.0838 | -0.0017 |
| `Negative_Control_Placebo` | 0.1291 | 0.0922 | 0.5149 | 0.0839 | -0.0033 |

- **Incremental Val PR-AUC (Combined - Price/Vol):** `+0.0103`
- **100-Run Block Permutation Test p-value:** `0.2970`
- **1,000-Run Paired Block Bootstrap 95% CI:** `[-0.0086, +0.0296]`

---

## 5. Economic Translation & Friction Sensitivity (12 bps vs 30 bps)

### Validation Period (2025-01-01 to 2025-10-31)

| Policy | Net Ret (12 bps) | Sharpe (12 bps) | MaxDD (12 bps) | Net Ret (30 bps) | Sharpe (30 bps) | Trades | Total Fees (12 bps) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `100% BTC Buy & Hold` | +15.87% | 0.63 | -28.10% | +15.87% | 0.63 | 0 | $0.00 |
| `R7 Weekly Vol Target` | +13.58% | 0.60 | -23.10% | +13.23% | 0.59 | 646 | $352.80 |
| `Simple Trend (SMA20)` | -9.21% | -0.29 | -24.46% | -14.91% | -0.57 | 124 | $2575.79 |
| `Price-Only Risk Policy` | +18.80% | 0.79 | -16.57% | +11.63% | 0.57 | 325 | $4159.85 |
| `Combined (Price+News) Policy` | +10.40% | 0.52 | -22.89% | +4.04% | 0.31 | 333 | $4771.48 |

---

## 6. Scientific Attribution & Mechanism Analysis

1. **Information Timing:**
   Breaking news events in crypto (major hacks, regulatory subpoenas) produce instantaneous volatility spikes within seconds-to-minutes. By the time news is aggregated, verified, and digested into a daily or 4h bar, the majority of the price drawdown has already occurred.

2. **False Positives in Protocol Exploits:**
   Many verified DeFi exploits (e.g. $10M–$30M bridge or lending pool compromises) are isolated to idiosyncratic smart contracts and do not impair Bitcoin spot market liquidity or aggregate institutional demand.

3. **Net Economic Friction:**
   De-risking to cash based on lagged news event alerts incurs frequent churn, paying 12–30 bps in transaction fees while occasionally missing the subsequent sharp mean-reverting recovery.

---

## 7. Recommendation for Unified Neural Trading Policy

**Verdict:** `EXCLUDE`  

Raw news/event shock counts and exploit USD amounts do NOT provide statistically significant or economically additive predictive information beyond price/volatility momentum controls at causal daily horizons.
We recommend **EXCLUDING** raw news shock counts as state inputs to the upcoming Unified Neural Policy, avoiding unnecessary parameter bloat and overfitting on historical headlines.

---