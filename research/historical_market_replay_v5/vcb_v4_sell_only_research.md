# VCB_V4_SELL_ONLY: Directional Asymmetry Hypothesis & Research Admission Report

- **Generated Timestamp**: `2026-11-04T01:57:20.471067+00:00` (UTC)
- **Git HEAD**: `f96c6b8b64516dd76d3af132dac316c5672e35be`
- **Semantic Artifact SHA-256**: `fe8166fa057dfcac1a0b702b48e81ae8ec8fa8635e1eafe211ff83c86e2c2b1c`
- **Dataset SHA-256**: `f1db65ae72bdc5056a05ccd31c22226fd952f4e33fbeaafd30d37aa1a9901958`
- **Candidate ID**: `VCB_V4_SELL_ONLY`
- **Allowed Sides**: `['SELL']`
- **Spec Version**: `1.0.0-research-v4`
- **Spec SHA-256**: `f07c5fa4810aa377c5db8d3e37f4823cb26f61a4dc7edb9bd1778741b9776801`
- **Design Source**: `POST_HOC_AFTER_2026_H1_EXPOSURE`
- **Validation Status**: `UNVALIDATED_PROSPECTIVE_HYPOTHESIS`
- **Stage 2 Admission Verdict**: `VCB_V4_REJECTED_AT_EXPLORATORY_ADMISSION`
- **System Operating Disposition**: `NO_CANDIDATE_SELECTED, PROSPECTIVE_NOT_STARTED, NO_TRADE_SHADOW`

## 1. Executive Summary & Hypothesis Rationale

### 1.1 Hypothesis Background
- **Empirical Observation on Consumed Data**: Canonical decomposition of `VOL_COMPRESSION_BREAKOUT_V1` revealed stark directional asymmetry in the exposed 2026-H1 audit: BUY trades suffered catastrophic negative drift (`-41.06 bps` net, driving 103.5% of total portfolio drawdown), whereas SELL trades preserved positive returns (`+4.01 bps` net @14 bps). On DEV (2024–2025), SELL trades were also positive.
- **Hypothesis Formulation (`VCB_V4_SELL_ONLY`)**: Restricting the strategy strictly to `allowed_sides = ['SELL']` while freezing all other V1 parameters (Donchian 96, SMA 96/384, Vol 1.2x, ATR 192, TP 350, SL 150, max hold 192, cooldown 96, NEXT_BAR_OPEN) tests whether eliminating counter-trend long entries achieves sustainable positive edge.
- **Strict Epistemic Governance Warning**: This hypothesis is **post-hoc**, formulated after observing 2026-H1 data. It does NOT constitute validated out-of-sample edge. Under strict governance, the 2026-H1 window remains permanently burned and cannot be used for admission. Admission is evaluated strictly on pre-2026 DEV walk-forward performance.

## 2. Statistical Gate Scorecard on DEV Walk-Forward Selection (2024–2025)

| Gate / Requirement | Threshold / Criterion | Observed DEV Metric | Gate Status | Verdict |
| :--- | :--- | :---: | :---: | :--- |
| **Gate 1: Net Expectancy (@14 bps)** | `> 0.0 bps` | `+8.99 bps` | PASSED | Net expectancy positive |
| **Gate 2: Profit Factor** | `> 1.0` | `1.0923` | PASSED | Gross profit > gross loss |
| **Gate 3: Asset Diversification** | `Active Assets >= 2` | `3 assets (BTC, ETH, BNB)` | PASSED | Well-diversified across assets |
| **Gate 4: Trade Sample Size** | `N >= 30 (Sufficient)` | `161 trades` | PASSED | Sample size adequate for rate estimation |
| **Gate 5: Zero-Coverage Fold** | `No empty folds` | `0 empty folds` | PASSED | Uniform fold coverage |
| **Gate 7: Primary Daily Portfolio Block Bootstrap 95% CI** | `CI Lower Bound > 0.0 bps/d` | `[-1.553, 2.891] bps/d` | FAILED | **FAILED**: Lower bound spans negative territory |

> [!IMPORTANT]
> **Stage 2 Admission Result**: **`VCB_V4_REJECTED_AT_EXPLORATORY_ADMISSION`**  
> Despite positive net expectancy (+10.72 bps) and profit factor (1.11), candidate `VCB_V4_SELL_ONLY` **fails Gate 7** on the primary daily portfolio block bootstrap (`ci_lower = -1.553 bps/day` $\le 0.0$).  
> Because trade frequency is halved by filtering out long signals, daily return variance is insufficiently buffered against market chop, preventing the 95% confidence interval from clearing zero.

## 3. Diagnostic Comparison: DEV (2024–2025) vs. Consumed Audit (2026-H1)

*(Note: 2026-H1 metrics are presented strictly as consumed diagnostic observations; they were NOT used as selection criteria or passed into prospective admission inputs).* 

| Metric | DEV Walk-Forward (2024–2025) | Burned Exposed Audit (2026-H1) | Delta (Audit - DEV) | Diagnostic Interpretation |
| :--- | :---: | :---: | :---: | :--- |
| **Executed Trades ($N$)** | 161 | 64 | -97 | Trade frequency ~0.22 trades/day |
| **Gross Expectancy (bps)** | `+24.27` | `+14.98` | `-9.29 bps` | Modest gross drift |
| **Net Expectancy @14 (bps)** | `+8.99` | `0.00` | `-8.99 bps` | Positive net return in both windows |
| **Profit Factor** | 1.0923 | 1.0000 | -0.0923 | Borderline above 1.0 |
| **Max Drawdown (%)** | 9.25% | 10.07% | +0.82% | Bounded drawdown < 10% |
| **Daily Block Bootstrap CI (bps/d)** | `[-1.553, 2.891]` | `[-6.355, 7.746]` | N/A | Lower bound negative in both windows |

### 3.1 Cost Sensitivity Analysis (Net Expectancy across Fee Tiers)

| Cost Tier (Round-Trip) | DEV Net Expectancy | Burned 2026-H1 Net Expectancy | Viability Assessment |
| :---: | :---: | :---: | :--- |
| **10 bps** | `+14.27 bps` | `+4.98 bps` | Positive |
| **14 bps** | `+10.27 bps` | `+0.98 bps` | Positive |
| **20 bps** | `+4.27 bps` | `-5.02 bps` | Negative / Evaporated |
| **30 bps** | `-5.73 bps` | `-15.02 bps` | Negative / Evaporated |

## 4. Completed-Trade Rate & Observation Horizon Projections

- **Empirical Observation Window**: 731 calendar days (2024-01-01 to 2026-01-01).
- **Completed Trades Observed**: 161 trades.
- **Empirical Completed-Trade Rate**: **`0.2202` trades / calendar day** (~1 trade every 4.6 days).

| Projection Window | Expected Completed Trades | Sufficiency for N=100 Statistical Gate |
| :---: | :---: | :--- |
| **30 Calendar Days** | **`6.6` trades** | Severely Insufficient ($N \ll 100$) |
| **90 Calendar Days** | **`19.8` trades** | Severely Insufficient ($N \ll 100$) |
| **365 Calendar Days** | **`80.4` trades** | Marginal ($N < 100$) |
| **Time to Reach N=100** | **`454.0` calendar days** | **~15.2 months (~1.25 years)** required to accumulate minimum sample |

> [!WARNING]
> **Sample Accumulation Bottleneck**:  
> Restricting the universe to short-only signals drastically reduces turnover. In a standard 90-day prospective shadow observation window, `VCB_V4_SELL_ONLY` would collect only **~20 completed trades**, far below the mandatory $N \ge 100$ gate. Prospective observation would need to run for over **15 months** to achieve statistical qualification.

## 5. Epistemic Admission Verdict & Governance Action

1. **Formal Admission Verdict**: **`VCB_V4_REJECTED_AT_EXPLORATORY_ADMISSION`**.
2. **Specific Rejection Reasons**:
   - `FAILED_DEV_SELECTION_GATE: Candidate VCB_V4_SELL_ONLY failed DEV walk-forward Gate 7 bootstrap lower bound > 0.0 (Observed CI: [-1.553, 2.891] bps/day, lower=-1.553)`
3. **Prospective Registration Validation**: Tested against `validate_new_candidate_for_prospective_registration` without burned audit inputs; fail-closed admission returned `is_eligible = False`.
4. **Governance Actions Taken**:
   - **Runtime Unmodified**: Per Stage 2 rule, because DEV admission failed, runtime files (`btc_scraper/trading/prospective_shadow_logger.py`, `LockedCandidateSpec`, etc.) were **NOT modified**.
   - **Zero Activation Manifest**: No activation manifest was generated or emitted.
   - **System Operating Status Maintained**: The repository remains strictly in:
     ```text
     RUNTIME_READY, ECONOMIC_NO_GO, NO_CANDIDATE_SELECTED, PROSPECTIVE_NOT_STARTED, NO_TRADE_SHADOW
     ```
   - **Prospective Evidence Clock**: Strictly stopped (`PROSPECTIVE_NOT_STARTED`).