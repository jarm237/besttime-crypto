# BESTTIME-CRYPTO — S4-P0 Forecast Information Screening

**Status:** `DESIGN_REFERENCE / PROPOSED_NOT_AUTHORIZED`
**Scope:** Future Stage-1 forecasting protocol, **not** permission to implement, train, replay, or access quarantined periods.
**Historical context:** S3 `CLOSED_NEGATIVE_EXPLORATORY`; S3 documentation closure commit `1c6ed07d412de8a1c46aad011b02aa1a67a7c1a0`.
**Universe:** BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT; Spot long-only + cash if any later allocation study is separately authorized.
**Data provenance:** Research program's 2024–2026 data are `REUSED_DIAGNOSTIC`, not pristine/untouched OOS. This document authorizes **zero** access to them.

## 1. Research question and boundaries

**Question:** Does **one shared multi-asset neural forecaster** extract incremental *causal predictive information* about feasible 24-hour execution-to-execution returns, relative to a pre-registered simple Ridge regression trained on the same information? S4-P0 is not an economic alpha claim.

Stage 1 includes feature/label construction, Ridge and one shared neural forecaster, and paired statistical screening **only after separate authorization**. It excludes any convex L1 allocation optimizer, cost-aware trading simulator, new production integration, trading, or live/paper execution. A future positive Stage-1 result would be necessary research evidence, not automatic Stage-2 authorization.

## 2. Executable-time label and feature information set

For UTC decision date `t`:

| Event | Clock | Contract |
|---|---|---|
| Last observed information | `t 00:00:00 UTC` | Only bar data strictly closed/available by this instant; for Binance 1h open-time indexing, the 23:00–00:00 bar is the last eligible bar |
| Decision | `t 00:05:00 UTC` | Model features and causal transforms must already be frozen |
| Feasible execution entry | `t 01:00:00 UTC` | Open price of the 01:00–02:00 bar, **never an input feature** |
| Label completion | `(t+1 day) 01:00:00 UTC` | Next 01:00-bar open, observed only at that later time |

For asset `i`:

\[
y_{i,t}=\log\left(P^{open}_{i,t+1d,01:00}/P^{open}_{i,t,01:00}\right).
\]

Labels must be computed only where both authentic execution prices exist; no interpolation, future fill, or invented OHLCV. Label values may be used for supervised training only **after their end timestamp is observable**, never in same-day model inputs. Missing feature windows are excluded by a documented complete-case rule or are separately masked under a pre-registered architecture; don't silently replace missing return with zero.

**Causal sigma time rule:** At cutoff `t 00:00`, the label from decision `t−1` finishes at `t 01:00`, and is **not known yet**. The most recent available *daily execution-to-execution label* is ordinarily the one from decision `t−2`, completed at `(t−1) 01:00`. This constraint must be enforced in EWMA, scaling, cross-validation, and any precomputed features.

## 3. Four proposed micro-constants — fixed in this design reference

### C1. Causal volatility standardization

- Raw input to volatility estimator: authentic **completed historical 24h execution-to-execution log returns**, not future labels or zero-imputed return placeholders.
- Exponentially weighted mean and second moment with daily decay `lambda = 2 ** (-1/20)` (**half-life = 20 completed daily observations**). Raw variance: `max(EWMA(y²) − EWMA(y)², 0)`; raw sigma = square root of this variance.
- Require **at least 30 previously completed, valid daily labels** for a valid sigma estimate; older eligible historical warmup may be used and must be identified in a future data manifest. Missing observations do not become zero returns.
- Floor rule by asset and fit: `epsilon_i = max(0.0001, 0.1 × median(raw_sigma_i over the fitting partition))` in daily log-return units. The median is estimated using **only the fit partition**, never its validation period or the 2023 screen. Refit once on full permitted 2022 development data before the frozen 2023 screen. For every date, use `sigma_i,t = max(raw_sigma_i,t, epsilon_i)` with causal as-of availability.
- Standardized label: `z_i,t = y_i,t / sigma_i,t`.

**Important:** A floor estimated from full 2022 is allowed for the final 2023 screen but would leak across folds if reused when cross-validating within 2022. Fit/transform must be folded correctly.

### C2. Forecast de-standardization and calibration

The model predicts `z_hat_i,t`; its return-scale forecast is defined as:

\[
\hat y_{i,t}=\hat z_{i,t}\,\hat\sigma_{i,t}^{causal}.
\]

Report per-asset Mincer–Zarnowitz regression on the **unclipped actual** execution return `y`:

\[
y_{i,t}=\alpha_i+\beta_i\hat y_{i,t}+\varepsilon_{i,t}.
\]

Positive slope is directional calibration evidence; a slope > 0 alone does **not** establish correct magnitude, conditional mean calibration, or downstream economic value. Report intercept, slope, uncertainty, and forecast/actual scale in bps. All regressions and transformations use only the frozen 2023 screen for evaluation, with no subsequent model tuning.

### C3. Clipping — explicitly a robust *surrogate* estimand

Pre-register symmetric clipping at `−4.0` and `+4.0` **only for supervised training target and its squared-error training objective**:

\[
z^{clip}_{i,t}=\operatorname{clip}(z_{i,t},-4,+4),\quad
L_{train}=\operatorname{mean}(\hat z-z^{clip})^2.
\]

Both models use the **same clipped training targets** and squared-error objective (Ridge also adds its L2 coefficient penalty). Clipping changes the estimand from `E[z | X]` to `E[clip(z,−4,4) | X]`; therefore the unscaled forecast is **not automatically an unbiased conditional expected raw return**. Before using such forecasts as `mu` in any later Mean–Variance optimizer, independently establish return-scale calibration or separately authorize an estimand revision.

**Primary 2023 IC uses raw, unclipped standardized realized `z`** and the frozen forecasts. Report clipped-target IC as a secondary sensitivity and rerun the primary score after excluding the predetermined 5% highest-absolute-move market days. Never choose which version is primary after seeing scores. Do not clip inputs using statistics from the 2023 evaluation period.

### C4. Ridge alpha and chronological development CV

- Ridge objective: penalized **squared loss** on identical clipped standardized targets; standard `Ridge` is not Huber regression.
- Alpha grid: `{1e-3, 1e-2, 1e-1, 1, 10, 100, 1000, 10000}` exactly.
- Pre-specified **four expanding-window forward-validation folds within 2022**, for example:
  1. Fit Jan 01–Apr 30; validate May 01–Jun 15.
  2. Fit Jan 01–Jun 15; validate Jun 16–Jul 31.
  3. Fit Jan 01–Jul 31; validate Aug 01–Sep 30.
  4. Fit Jan 01–Sep 30; validate Oct 01–Dec 30.
- At **each** fold start, remove any fit row whose label ends later than the first validation decision's information cutoff (typically the immediately preceding day's decision). This is a time-of-information purge, not arbitrary removal of 24 rows.
- Fit sigma floors, feature scalers, any normalization, and candidate Ridge weights on that fold's permitted training rows only. Scored validation labels must have actually completed inside their eligible validation window. Resolve tie in mean fold validation squared error by selecting **larger alpha** (more regularization).
- Before evaluating 2023 once, re-fit both forecasting models on eligible 2022 data with labels completed no later than the 2023-01-01 00:00 UTC cutoff. In particular **exclude the 2022-12-31 decision label**, which completes 2023-01-01 01:00.
- Last permitted 2023 evaluation decision is **2023-12-30**, whose label completes 2023-12-31 01:00. Do not use the 2023-12-31 decision label because it completes in 2024.

The example fold calendar is **proposed as the design default**, not evidence that training or model selection has been executed.

## 4. Neural/Ridge information parity

- One shared temporal/cross-asset neural forecaster, **not** multiple independently trained models.
- Both estimators must see data from the exact same `as-of` market information set and use the same target construction, sample/asset universe, eligible rows and evaluation dates.
- Ridge may consume a causal flattened representation of the feature tensor; the neural model may have temporal inductive bias. This is **information parity**, not necessarily equal parameter counts or identical transformations.
- Set seeds for Python, NumPy, PyTorch and dataloader workers **before** constructing models or samplers. Deterministic settings and hardware-dependent nondeterminism must be disclosed.
- Neural architecture size, initialization, fixed optimizer schedule, epochs, checkpoint-selection rule, model-selection budget, feature list and preprocessing still require exact pre-registration **before any Stage-1 execution**. Therefore this file is a design reference, **not yet a completely frozen executable study**.

## 5. Frozen evaluation statistic and paired uncertainty

Daily evaluation is at the same 00:05 UTC decision each day with 24h execution-to-execution labels. Labels have no mechanical 23-hour overlap; nevertheless returns, features and common-market shocks may remain serially/cross-sectionally dependent.

For each asset `i` on the same eligible 2023 dates, compute Pearson time-series IC:

\[
IC_i^{(m)}=corr_t(\hat z_{i,t}^{(m)}, z_{i,t}),\quad
S_m=\tanh\left(\frac{1}{4}\sum_{i=1}^{4}\operatorname{atanh}(IC_i^{(m)})\right)
\]

for model `m ∈ {Neural,Ridge}`. Define **primary comparison** `ΔS = S_Neural − S_Ridge`. If any series has zero variance or too few complete dates, classify as a protocol/data insufficiency rather than silently dropping an asset. Fisher-z averaging is a *pre-registered aggregation choice*, not a universal optimum; the four asset ICs remain correlated and must **not** be treated as independent samples.

**Paired stationary bootstrap:** Resample the date-level vector `D_t = (y_4, z_4, predictions_Neural_4, predictions_Ridge_4, auxiliary flags)` as one joint unit, preserving same-date cross-asset and between-model dependence. Use geometric-block stationary bootstrap (Politis–Romano), mean block length **14 days**, **2,000 draws**, fixed bootstrap random seed **42**, and a two-sided **95% percentile CI** for `ΔS`. Report sensitivity at block means **7** and **21 days** with the same 2,000 draws per setting. This is uncertainty under serial-dependence assumptions, not proof of independent 4×T observations.

**Required diagnostics, never substitute for the primary metric post hoc:**

1. Market-common versus relative signal: separate a common-factor component and asset-relative component using a fully pre-specified algebraic decomposition and compare incremental results to Ridge. Cross-asset pooled IC must not silently replace asset-wise IC.
2. Mincer–Zarnowitz: slope, intercept and uncertainty on raw execution-return scale, using `y_hat = z_hat × causal_sigma`.
3. BTC-relative pair signs for ETH/BTC, SOL/BTC, BNB/BTC only when absolute **forecasted spread** exceeds **24 bps** (diagnostic heuristic `2×12 bps`; not a universal break-even cost threshold). Report sample count and coverage; don't frame this diagnostic as realized tradable profit.
4. Extreme-day sensitivity: drop the **5% dates with largest absolute equal-weight market return**, ranking criterion fixed in advance; recompute `S_Neural`, `S_Ridge`, and `ΔS`. Recalculate this screening subset only for diagnosis, not for retraining.
5. Sub-period stability, e.g. first vs second half of 2023, with small-sample uncertainty disclosed.
6. Effective sample dates, excluded missing-data periods, per-asset valid counts, and 7/14/21 block-bootstrap sensitivity.

## 6. Three-state research decision — no automatic Stage-2 authorization

- `STAGE1_SIGNAL_SUPPORTED`: Positive primary neural IC, 95% paired-bootstrap **lower** confidence bound for `ΔS` above zero, positive MZ slope on a pre-specified aggregation/asset rule, and no complete collapse of positive relative performance when the pre-specified extreme-day check is applied. This is **predictive-information evidence**, not alpha or deployment permission.
- `STAGE1_SIGNAL_NOT_SUPPORTED`: Evidence is sufficiently negative (e.g., 95% paired-bootstrap **upper** confidence bound for `ΔS` ≤ 0, or pre-registered decisive failure condition). State the exact ground; it rejects this **specific** forecaster/feature/protocol hypothesis, not all neural trading or all nonlinear forecasts.
- `STAGE1_SIGNAL_INCONCLUSIVE`: CI straddles zero, insufficient effective dates, unstable or contradictory diagnostics, too few valid observations, or unresolved protocol validity. **No tuning/repeated evaluation to escape the gray zone.**

**Caveat:** The exact MZ aggregation rule, definition of an extreme-day diagnostic failure, minimum sample/coverage threshold and admissible confidence assumptions need to be frozen before a real run. A statistically significant IC gain is not sufficient for economic utility. Conversely, an inconclusive result is not proof of no signal.

## 7. Preservation and explicit non-authorization

```text
S3_RESEARCH                   = CLOSED_NEGATIVE_EXPLORATORY
S3_FURTHER_TRAINING           = NOT_AUTHORIZED
S3_FURTHER_REPLAY             = NOT_AUTHORIZED
S4_RESEARCH                   = PROPOSED_NOT_AUTHORIZED
S4_P0_BLUEPRINT               = DESIGN_REFERENCE_ONLY
S4_P0_EXECUTABLE_PREREG       = INCOMPLETE
S4_STAGE1_IMPLEMENTATION      = NOT_STARTED
S4_STAGE1_TRAINING            = NOT_AUTHORIZED
S4_STAGE2_CONVEX_ALLOCATOR    = NOT_IMPLEMENTED
S4_2024_2026_ACCESS          = NOT_AUTHORIZED
PRODUCTION_PROMOTION          = NOT_AUTHORIZED
```

This standalone Markdown reference has **not** been written to the user's GitHub repository. No new branch, code, model, experiment, market-data download, training, replay or trading action is authorized or performed by this document.

## 8. Methodology references

- Politis, D. N., & Romano, J. P. (1994). *The Stationary Bootstrap*, Journal of the American Statistical Association. https://doi.org/10.1080/01621459.1994.10476870
- scikit-learn documentation, *Ridge*: linear least squares loss with L2 penalty. https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.Ridge.html
- López de Prado, M. (2018), *Advances in Financial Machine Learning*, Chapter 7: purged cross-validation / label-time leakage.

*Research design reference prepared on 2026-11-19. No experimental results in this document.*
