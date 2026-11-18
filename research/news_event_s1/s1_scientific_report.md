# S1 — News & Event Shock Predictive Opportunity Discovery Report

## 1. Executive Summary & Canonical Verdict

**Repository Commit:** `8501bad7f49ad4e7bf354115008314ca0795559a`
**Evaluation Date:** `2026-11-18 04:28:02 UTC`
**Research Status:** COMPLETE

### Final Evidence-Derived Verdicts

- `NEWS_SOURCE_FEASIBILITY`: **`PARTIAL_BOUNDED`**
- `NEWS_PIT_CORRECTNESS`: **`PARTIAL`**
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

| Policy | Net Ret (12 bps) | Sharpe (12 bps) | MaxDD (12 bps) | Net Ret (30 bps) | Sharpe (30 bps) | Val Trades (Full) | Val Fees 12 bps (Full) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `100% BTC Buy & Hold` | +15.87% | 0.63 | -28.10% | +15.87% | 0.63 | 0 (1) | $0.00 ($11.99) |
| `R7 Weekly Vol Target` | +13.58% | 0.60 | -23.10% | +13.23% | 0.59 | 131 (646) | $95.67 ($352.80) |
| `Simple Trend (SMA20)` | -9.21% | -0.29 | -24.46% | -14.91% | -0.57 | 36 (124) | $1000.44 ($2575.79) |
| `Price-Only Risk Policy` | +18.80% | 0.79 | -16.57% | +11.63% | 0.57 | 82 (325) | $1549.15 ($4159.85) |
| `Combined (Price+News) Policy` | +10.40% | 0.52 | -22.89% | +4.04% | 0.31 | 81 (333) | $1639.75 ($4771.48) |

> **Trade Count Audit Note:** The 'Val Trades (Full)' column clarifies the actual trades executed during the 304-day Validation window versus the 1,034-day Full Horizon. R7 Weekly Vol Target executed 131 trades in Validation because daily MTM rebalances small drift variations from the target weight.

---

## 6. Scientific Attribution & Bounded Mechanism Analysis

1. **Audit of Data Provenance & Retrospective Enrichment:**
   - DeFiLlama incident timestamps represent `EVENT_OCCURRENCE_DATE` (midnight UTC). The publication timestamp is not verified, so an `ASSUMED_AVAILABILITY` heuristic of +24h was applied.
   - Furthermore, `amount_usd` is a `RETROSPECTIVELY_ENRICHED_VALUE` (finalized post-mortem total rather than preliminary breaking report). Even with this hindsight-enriched precision, the feature failed to predict downside risk out-of-sample.

2. **GDELT Sampling & Coverage Boundaries:**
   - GDELT archives were sampled across 6 discrete bounded regimes (34 days) and not mixed into the continuous daily series, preventing artificial zero-news bias on un-crawled days.

3. **Bounded Economic Mechanism:**
   - In this specific experiment, adding raw hack counts and USD loss amounts degraded out-of-sample risk timing by inducing whipsaw rebalances on idiosyncratic smart contract exploits that did not impair macro Bitcoin liquidity.
   - This observation is strictly bounded to the evaluated proxy and does NOT prove a universal law across all possible alternative news sources.

---

## 7. Bounded Scientific Verdict & Decision on Unified Neural Inputs

- `S1_RAW_HACK_AND_SAMPLED_EVENT_SHOCK_PROXY`: **`NOT_SUPPORTED`**
- `NEWS_HISTORICAL_PIT`: **`PARTIAL`**
- `GENERAL_NEWS_INFORMATION_VALUE`: **`NOT_ESTABLISHED`**
- `NEWS_NEURAL_INPUT_AUTHORIZATION`: **`NOT_AUTHORIZED`**

We do NOT assert that 'all news signals are permanently useless' or that 'news intelligence must never be researched'.
Rather, under strict scientific discipline: **The evaluated S1 raw hack and sampled event shock proxy is NOT SUPPORTED, and news-based features are NOT AUTHORIZED as state inputs for the upcoming Unified Neural Policy.**

---
