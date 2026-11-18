# S3-P1.1 — Bounded Scientific Closure Addendum

**Repository:** `https://github.com/jarm237/besttime-crypto`
**Research Workstream:** S3 — Unified Multi-Asset Neural Allocation
**Target Milestone:** S3-P1.1 Targeted Implementation & Economic Fidelity Correction
**Authoritative Status:** Final Documentation-Only Scientific Closure Addendum
**Supersession Scope:** This addendum formally qualifies and supersedes the narrative conclusions, causality claims, and verdict interpretations in `corrected_scientific_report.md` and `train_only_scientific_report.md`. All underlying numerical scorecards, simulation ledgers, configuration files, and git commits remain strictly preserved and unaltered.

---

## 1. Scope and Evidence Provenance

This addendum provides the final, source-grounded scientific closure for the S3 research workstream without reopening simulation or training pipelines. The evidence base rests strictly upon:
1. **Committed Implementation Source:** Checkpoint `e9c7d32666a67ac1f3bf11ee55b155a1c3c7b51c` on branch `research/s3-p1-targeted-fidelity-correction`.
2. **Persisted Canonical Artifacts:**
   - Scorecard: `research/s3_portfolio_aware/p1_corrected_train_only/train_scorecard.json`
   - Execution Ledger: `research/s3_portfolio_aware/p1_corrected_train_only/train_decision_ledger.jsonl` (729 decision records)
   - Configuration: `research/s3_portfolio_aware/p1_corrected_train_only/experiment_config.json`
   - Data Manifest: `research/s3_portfolio_aware/p1_corrected_train_only/source_manifest.json`
3. **Pristine Preservation:** The historical S3-P1 artifacts in `research/s3_portfolio_aware/p1_train_only/` remain untouched.

---

## 2. Authoritative Scientific Verdict Block

The following verdict represents the final scientific evaluation of S3-P1.1 after rigorous source and evidence auditing:

```text
========================================================================================
S3_P1_1_IMPLEMENTATION              = COMPLETED_WITH_LIMITATIONS

S3_P1_1_GATE_FORWARD_PARITY         = VERIFIED
S3_P1_1_EXACT_HOLD_CAPABILITY       = VERIFIED

S3_P1_1_ACTUAL_EXECUTION            = 729_OF_729
S3_P1_1_MEAN_GROSS_TURNOVER_PER_DAY = APPROX_2_18_PERCENT
S3_P1_1_SELECTIVE_INACTION          = NOT_OBSERVED

S3_P1_1_ACTIVE_DOWNSIDE_EFFECT      = SUGGESTIVE_CONFOUNDED
S3_P1_1_MISSING_DATA_FIDELITY       = PARTIAL

MVO_L1_TRAIN_RETURN                 = REPORTED_PLUS_243_97_PERCENT
MVO_L1_COVARIANCE_FIDELITY          = PARTIAL
MVO_L1_ERROR_IMPACT                 = NOT_QUANTIFIED

S3_P1_1_TRAIN_ECONOMIC_SANITY       = NOT_SUPPORTED
S3_NEURAL_INCREMENTAL_VALUE         = NOT_ESTABLISHED

S3_RESEARCH                         = CLOSED_NEGATIVE_EXPLORATORY
S3_P2_AUTHORIZATION                 = NOT_AUTHORIZED
S4_RESEARCH                         = PROPOSED_NOT_AUTHORIZED
PRODUCTION_PROMOTION                = NOT_AUTHORIZED
========================================================================================
```

---

## 3. Economic Interpretation & Attribution

### 3.1. Measured Economic Performance (Train 2022–2023)

All evaluations were conducted across the 729 daily decision steps of the Train split (2022-01-01 to 2023-12-31) starting with \$10,000 initial capital:

| Metric | S3 Unified Neural | Static 50/50 EW | Cost-Aware MVO-L1 | EW4 Buy & Hold |
| :--- | :---: | :---: | :---: | :---: |
| **Net Return (Base 12 bps)** | **-6.16%** | **+4.43%** | **+243.97%** | -31.69% |
| **Net Return (Stress 30 bps)** | **-8.80%** | **+4.11%** | **+87.27%** | -31.81% |
| **Max Drawdown (Base)** | -46.99% | -45.20% | -41.28% | -70.76% |
| **Annualized Sharpe** | 0.064 | 0.229 | 1.269 | -0.016 |
| **Mean Cash Weight** | 50.9% | 50.5% | 45.2% | 0.0% |
| **Gross Turnover** | 15.86x | 1.72x | 162.46x | 1.00x |
| **Total Fees Paid (Base)** | \$137.21 | \$16.76 | \$2,868.31 | \$11.99 |
| **Rebalance Decisions** | 729 | 24 | 204 | 1 |

### 3.2. Final Equity Shortfall vs. Direct Fee Difference

To understand why S3 Unified Neural underperformed the naive Static 50/50 EW control, we examine the terminal balance differences:
- **Neural Final Equity:** \$9,384.07
- **Static 50/50 Final Equity:** \$10,443.23
- **Final Equity Shortfall ($\Delta V$):**
  $$\Delta V = \$10,443.23 - \$9,384.07 = \$1,059.16$$
- **Direct Fee Difference ($\Delta TC$):**
  $$\Delta TC = \$137.21 - \$16.76 = \$120.45$$
- **Fee-to-Shortfall Ratio:**
  $$\frac{\Delta TC}{\Delta V} = \frac{\$120.45}{\$1,059.16} \approx 11.37\%$$

**Economic Attribution Qualification:**
The direct fee differential (\$120.45) accounts for only ~11.37% of the total terminal wealth gap (\$1,059.16). Consequently, there is **no empirical basis** to claim that eliminating transaction fees or micro-rebalancing would bridge the performance gap to Static 50/50 EW.

Crucially, it is methodologically invalid to claim that the remaining ~88.63% was *proven* to stem exclusively from poor directional forecasting or cross-asset selection. Because fees compound over time, trading paths alter physical inventory, and time-varying exposures interact dynamically with market returns, the relative contributions of forecasting error, allocation mapping, and path-dependent drag remain unisolated.

### 3.3. Gate Activity vs. Economic Turnover

In S3-P1.1, the learned hard gate produced:
- Gate active decisions: **729 / 729** steps ($100.0\%$)
- Executed rebalances: **729**
- Gross turnover: **15.86x** over 729 days
- Total transaction fees: **\$137.21**

Normalizing gross turnover by decision steps yields:
$$\frac{15.86\text{x}}{729} \approx 0.02176 \quad (\approx 2.18\% \text{ gross turnover per day})$$

This demonstrates that while the gate never triggered a true physical HOLD, the policy did not engage in destructive churn (such as the 250x turnover seen in S2-A heuristics). Instead, it engaged in persistent daily micro-adjustments around a ~50% cash anchor:
```text
GATE_ACTION_BEHAVIOR = ALWAYS_ACTIVE
EXECUTION_BEHAVIOR   = FREQUENT_SMALL_REALLOCATIONS
SELECTIVE_INACTION   = NOT_OBSERVED
```

---

## 4. Scientific Fidelity & Methodological Qualifications

### 4.1. Active-Downside Ablation: Suggestive but Confounded

The experimental scorecard reports a stark contrast between specifications:
- **Primary ($\lambda_{act} = 2.0$):** Net Return = -6.16%, Mean Cash = 50.9%, Rebalances = 729.
- **Ablation ($\lambda_{act} = 0.0$):** Net Return = 0.00%, Mean Cash = 100.0%, Rebalances = 0.

Inspection of `scripts/run_s3_p1_train_only.py` reveals that the `ablation_model` was instantiated in Step 7 after the primary model had completed training and evaluation. Because the random seed was set inside the `DifferentiableS3Trainer` constructor rather than prior to model weight allocation, `COMMON_INITIAL_WEIGHTS = NOT_VERIFIED`.

While the observed contrast is consistent with active-downside regularization preventing the cash trap, it cannot be characterized as a conclusively isolated causal mechanism. The definitive status is:
```text
S3_P1_1_ACTIVE_DOWNSIDE_EFFECT = SUGGESTIVE_CONFOUNDED
```

### 4.2. MVO-L1 Covariance Fidelity: Zero-Imputation Caveat

The classical benchmark `Cost-Aware MVO-L1` achieved a reported +243.97% return (Sharpe 1.269) on Train. Inspection of `btc_scraper/research/s3_p1_train_only.py` (lines 249, 287–288) reveals:
```python
log_rets_arr = hourly_log_rets[self.universe].fillna(0.0).to_numpy(dtype=np.float64)
...
cov_slice = log_rets_arr[cov_start_idx:end_idx]
cov_daily = lw.fit(cov_slice).covariance_ * 24.0
```
Missing hourly returns were imputed with `0.0` prior to Ledoit-Wolf shrinkage. While the universe has only one verified market-wide calendar gap (2023-03-24 13:00 UTC), zero-imputation artificially damps variance and perturbs covariance structure.

We do not have evidence that the +243.97% return is primarily an artifact of this single gap, nor can we declare the covariance matrix completely unperturbed:
```text
MVO_MISSING_RETURN_TREATMENT = ZERO_IMPUTATION
MVO_COVARIANCE_FIDELITY      = PARTIAL
MVO_ERROR_IMPACT             = NOT_QUANTIFIED
STATUS                       = STRONG_REPORTED_IN_SAMPLE_RESULT_WITH_MISSING_DATA_CAVEAT
```

### 4.3. Portfolio-State Test Coverage vs. Full-Path Parity

Unit test `test_portfolio_drift_reference_invariants` in `tests/research/test_s3_p1_train_only.py` tested reference weight updates using an isolated conditional script rather than invoking the full `CanonicalReplayEngine` or `DifferentiableS3Trainer` classes over multi-step state transitions:
```text
PORTFOLIO_STATE_FULL_PATH_PARITY = NOT_PROVEN
```

### 4.4. Training Gradient vs. Full Trajectory Parity

While `GATE_HARD_FORWARD_PARITY = VERIFIED` confirms that both training forward pass and inference replay use the exact deterministic boundary $g_t = \mathbb{I}(\text{logit}_t > 0.0)$, the training loss is a pathwise surrogate. In `train_epoch`, holdings and cash tensors are detached at each step (`q_after.detach()`, `C_after.detach()`), truncating backpropagation through time to prevent exploding computational graphs:
```text
TRAINING_GRADIENT = TRUNCATED_PATHWISE_SURROGATE
```

### 4.5. Fractional Research Execution Model

The simulation assumes `min_notional = 0.0` (`EXECUTION_MODEL = FRACTIONAL_RESEARCH`). It rigorously proves balance sheet conservation ($V_{post} = V_{pre} - TC$ to numerical precision $< 10^{-12}$), but does not simulate exchange-specific lot size filters or Binance minimum order notionals (\$5.00).

---

## 5. Unresolved Diagnostic Gap: Signal vs. Decision Confound

A central architectural limitation of S3 was end-to-end monolithicism:
$$\text{Market Features} \longrightarrow \text{GRU} \longrightarrow \text{Attention} \longrightarrow \text{Allocation + Gate} \longrightarrow \text{Cost-Aware Loss}$$

Because all stages were bundled into a single objective, the negative economic outcome cannot be definitively diagnosed:
- Did the GRU fail to extract predictive representations from market features?
- Did the cross-asset attention mechanism fail to learn relative asset ranking?
- Did the policy map accurate forecasts into suboptimal cash/crypto allocations?
- Did the gate regularizer fail to discover selective inaction?
- Or did the truncated training surrogate diverge from multi-period compounding?

```text
SIGNAL_VS_DECISION_FAILURE_ATTRIBUTION = UNRESOLVED
```

No standalone predictive audit (e.g., Information Coefficient, Rank IC, calibration curves, or out-of-sample $R^2$) was conducted on the encoder representations. **Crucially, closing S3 does not require resolving this gap.** The observed negative return on Train (-6.16% vs. +4.43% Static 50/50) conclusively falsifies the current end-to-end policy hypothesis. This gap serves as a structural lesson for future research design.

---

## 6. Future Research Boundary: S4 Proposed Hypothesis (Not Authorized)

### 6.1. Architectural Separation Principle

If future multi-asset research is initiated, it should decouple forecasting from portfolio optimization:
```text
S4_HYPOTHESIS = ONE_SHARED_NEURAL_FORECASTER + EXPLICIT_COST_AWARE_PORTFOLIO_OPTIMIZATION
```
- **Forecaster:** A single shared multi-asset neural model trained purely to estimate directional or cross-sectional return distributions.
- **Allocator:** A deterministic convex/L1 optimizer handling position constraints, cash drift, and transaction costs.

### 6.2. Mandatory Stage-1 Predictive Screening

Before building any convex allocator, future work must establish whether the neural forecaster possesses statistically significant incremental information over naive baselines:
```text
STAGE_1           = FORECAST_INFORMATION_SCREENING
BASELINE          = SIMPLE_CAUSAL_FORECAST_BASELINE (e.g., Ridge / EWMA)
EVALUATION        = CAUSAL_WALK_FORWARD_ON_TRAIN
PRIMARY_METRICS   = PRE_REGISTERED (Rank IC / Sign Accuracy / Calibration)
```

### 6.3. Research Protocol Constraints

1. **Spot Only:** Long-only crypto + cash. No leverage, no derivatives, no shorting.
2. **Beta Disclosure:** Any cross-sectional equity-tilted sleeve retains substantial market beta. It must never be described as "market-neutral".
3. **Data Integrity:** In the global research program context, **2024–2026 is a Reused Diagnostic Split**, not an untouched holdout.

### 6.4. Explicit Non-Authorization

```text
S4_RESEARCH                = PROPOSED_NOT_AUTHORIZED
S4_STAGE_1_IMPLEMENTATION  = NOT_STARTED
S4_NEURAL_TRAINING         = NOT_AUTHORIZED
S4_CONVEX_OPTIMIZER        = NOT_IMPLEMENTED
PRODUCTION_PROMOTION       = NOT_AUTHORIZED
```

---

## 7. Final Research Disposition

The S3 research workstream is formally closed:
- **Verdict:** `CLOSED_NEGATIVE_EXPLORATORY`
- **Technical Result:** Implementation invariants, gradient flow, and fractional accounting verified.
- **Economic Result:** Failed in-sample economic sanity gate. Did not establish incremental economic value over static or classical baselines.
- **Enforcement:** **ABSOLUTE HARD STOP.** No further training, no hyperparameter tuning, no S3-P2, and no S4 execution.
