# S1 — News & Event Shock Predictive Opportunity Discovery Report

## 1. Executive Summary & Canonical Verdict

- **Repository Commit:** `8501bad7f49ad4e7bf354115008314ca0795559a`
- **Evaluation Date:** `2026-11-18 04:28:02 UTC`
- **Research Status:** `CLOSED_EXPLORATORY`

### Final Evidence-Derived Verdicts

- `S1_RESEARCH`: **`CLOSED_EXPLORATORY`**
- `S1_HISTORICAL_PIT`: **`PARTIAL`**
- `S1_COVERAGE_SPLIT_COUNTS`: **`CORRECTED_VERIFIED`**
- `NEWS_SOURCE_FEASIBILITY`: **`PARTIAL_BOUNDED`**
- `NEWS_PIT_CORRECTNESS`: **`PARTIAL`**
- `S1_DEFILLAMA_HACK_PROXY_24H`: **`NOT_SUPPORTED`**
- `S1_DEFILLAMA_HACK_PROXY_72H`: **`INCONCLUSIVE`**
- `S1_INCREMENTAL_ECONOMIC_VALUE`: **`NOT_SUPPORTED`**
- `S1_GDELT_ECONOMIC_EVALUATION`: **`NOT_PERFORMED`**
- `S1_R7_CANONICAL_PARITY`: **`FAILED`**
- `S1_BACKFILL_ACTUAL_IMPACT`: **`ZERO_EVALUATED_ROWS`**
- `GENERAL_NEWS_INFORMATION_VALUE`: **`NOT_ESTABLISHED`**
- `UNIFIED_NEURAL_ALPHA`: **`NOT_ESTABLISHED`**
- `PRODUCTION_PROMOTION`: **`NOT_AUTHORIZED`**

This closure corrects artifact/source consistency only. The experiment was not rerun, and the predictive and economic measurements below are unchanged.

---

## 2. Hypothesis & Research Scope

> **Hypothesis (S1-H1):** Negative crypto market-wide news/event shocks, collected at their causal availability time, predict subsequent downside risk (24h primary, 72h secondary) and improve long-only spot BTC/cash allocation after transaction costs (12 bps base, 30 bps stress) beyond price/volatility-only controls.

This research was conducted independently under Workstream C, strictly isolating historical PIT data and market replay from prior R4–R11 neural training and D0.1 derivatives research.

---

## 3. Historical Data Source Feasibility & Point-in-Time Integrity

### Ingested Point-in-Time Data Sources

1. **DeFiLlama Crypto Exploits Database:**
   - Records crypto security exploits, private-key thefts, oracle exploits, and protocol compromises.
   - **PIT protocol:** Incident dates are represented at midnight UTC. Because publication timestamps are unavailable, the experiment applies an assumed **+24 hour availability delay**: `available_at = event_timestamp + 24h`.
   - `amount_usd` may be retrospectively enriched and is not guaranteed to equal the amount known at first publication.

2. **GDELT Project 2.0 Global Event Archives (bounded windows):**
   - The source archives have 15-minute granularity, but this experiment sampled one archive every **2 hours** within six bounded regimes (34 days), not complete 15-minute coverage.
   - **PIT protocol:** An additional **+1 hour ingestion delay** was applied.
   - GDELT events were inspected for feasibility only and were **not used** in predictive features or economic replay.

### Corrected DeFiLlama Coverage

| Split | Inclusive period convention | Events |
| :--- | :--- | ---: |
| Train | `2023-01-01 <= event < 2025-01-01` | 414 |
| Validation | `2025-01-01 <= event < 2025-11-01` | 120 |
| Excluded before research window | `event < 2023-01-01` | 446 |
| Excluded after validation window | `event >= 2025-11-01` | 382 |

The full source contains 1,362 records. The earlier 860/502 figures were cumulative-boundary counts rather than split-local counts and are superseded by 414/120.

### PIT Audit Summary

- Checked decision days with a non-empty 24h event window: **796**
- Passed latest-event causal checks: **796** (100.0%)
- 24h event memberships across those windows: **1,097**
- 72h event memberships: **3,287**
- Decision days containing multiple 24h events: **227**
- Audit scope: the latest event on each checked decision day; this is not an exhaustive membership-by-membership publication-time audit.
- Economic replay backward fill: **removed**. A source/artifact comparison found **0 evaluated rows** whose values had been changed by the previous `.bfill().ffill()` expression.

Accordingly, the historical PIT verdict remains `PARTIAL`: availability is inferred from a fixed delay rather than verified first-seen publication timestamps.

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
- **100-run block permutation p-value:** `0.9604`
- **1,000-run paired block bootstrap 95% CI:** `[-0.0671, +0.0028]` (covers zero)
- **Scoped verdict:** `NOT_SUPPORTED`

### Secondary Target: 72h Downside Return (< -4.0%)

| Model | Train PR-AUC | Val PR-AUC | Val ROC-AUC | Val Brier Score | Val Brier Skill Score |
| :--- | :---: | :---: | :---: | :---: | :---: |
| `Price_Vol_Baseline` | 0.1344 | 0.0898 | 0.4925 | 0.0839 | -0.0031 |
| `News_Only` | 0.1210 | 0.0750 | 0.4737 | 0.0841 | -0.0054 |
| `Combined_Price_News` | 0.1279 | 0.1002 | 0.5136 | 0.0841 | -0.0061 |
| `Negative_Control_Shifted` | 0.1311 | 0.0999 | 0.5467 | 0.0838 | -0.0017 |
| `Negative_Control_Placebo` | 0.1291 | 0.0922 | 0.5149 | 0.0839 | -0.0033 |

- **Incremental Val PR-AUC (Combined - Price/Vol):** `+0.0103`
- **100-run block permutation p-value:** `0.2970`
- **1,000-run paired block bootstrap 95% CI:** `[-0.0086, +0.0296]`
- **Scoped verdict:** `INCONCLUSIVE`

---

## 5. Economic Translation & Friction Sensitivity (12 bps vs 30 bps)

### Validation Period (2025-01-01 to 2025-10-31)

| Policy | Net Ret (12 bps) | Sharpe (12 bps) | MaxDD (12 bps) | Net Ret (30 bps) | Sharpe (30 bps) | Val Trades (Full) | Val Fees 12 bps (Full) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `100% BTC Buy & Hold` | +15.87% | 0.63 | -28.10% | +15.87% | 0.63 | 0 (1) | $0.00 ($11.99) |
| `S1 30D Vol Target (40% Target, Weekly Signal, Daily Rebalance)` | +13.58% | 0.60 | -23.10% | +13.23% | 0.59 | 131 (646) | $95.67 ($352.80) |
| `Simple Trend (SMA20)` | -9.21% | -0.29 | -24.46% | -14.91% | -0.57 | 36 (124) | $1000.44 ($2575.79) |
| `Price-Only Risk Policy` | +18.80% | 0.79 | -16.57% | +11.63% | 0.57 | 82 (325) | $1549.15 ($4159.85) |
| `Combined (Price+News) Policy` | +10.40% | 0.52 | -22.89% | +4.04% | 0.31 | 81 (333) | $1639.75 ($4771.48) |

> **Trade-count audit note:** The S1 volatility policy uses 30-day realized volatility, a 40% annualized target, a weekly target-weight update, and daily rebalancing/mark-to-market. It is not established as canonical R7 parity. Daily rebalancing produced 131 trades in Validation and 646 over the full horizon.

---

## 6. Scientific Attribution & Bounded Mechanism Analysis

1. **Data provenance and retrospective enrichment:** DeFiLlama incident timestamps represent occurrence dates, not verified publication timestamps. The +24h availability rule is a conservative heuristic, while `amount_usd` may reflect a finalized post-mortem value.
2. **GDELT boundary:** The six bounded, two-hour-sampled regimes establish only partial source feasibility. Because GDELT was not included in the model or replay, S1 provides no GDELT economic verdict.
3. **Bounded economic mechanism:** In this experiment, adding raw hack counts and USD loss amounts degraded out-of-sample risk timing and increased whipsaw relative to price/volatility controls. This finding is limited to the evaluated DeFiLlama proxy and does not establish a general result for all news sources.

---

## 7. Bounded Scientific Verdict & Closure

- The DeFiLlama hack proxy is `NOT_SUPPORTED` for the primary 24h target and `INCONCLUSIVE` for the secondary 72h target.
- GDELT economic evaluation was `NOT_PERFORMED`.
- General news information value and unified-neural alpha remain `NOT_ESTABLISHED`.
- News-derived neural inputs and production promotion remain `NOT_AUTHORIZED`.
- S1 is closed as `CLOSED_EXPLORATORY`; this closure does not authorize S1.1, S2, retraining, replay, crawling, or deployment work.

The conclusion is deliberately bounded: the evaluated S1 raw-hack proxy did not establish incremental predictive or economic value. It does not claim that all news signals are permanently useless.
