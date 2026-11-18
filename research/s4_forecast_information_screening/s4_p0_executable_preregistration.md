# S4-P0 — Executable Pre-registration: One Shared Forecaster vs. Ridge

**Status:** FROZEN_BEFORE_STAGE1_EXECUTION (when committed)
**Parent design:** s4_p0_forecast_information_screening_design_reference.md at ee771abd8386ef3934d5d429a174bdb01dc16cbc
**Research authority:** User authorized starting S4 on 2026-11-19; **Stage 1 only**. This document overrides the older design reference's historical PROPOSED_NOT_AUTHORIZED state for Stage 1, without altering the archived source.
**No S3 reuse as policy:** S3 stays CLOSED_NEGATIVE_EXPLORATORY; do not merge S3's allocation, gate, optimizer, or zero-imputed feature path into S4.
**Main question:** On one frozen 2023 reused internal screen, does one shared four-asset neural forecaster produce incremental causal information about 24-hour execution-to-execution returns beyond a Ridge forecast using the exact same information?
**Scope:** Development and exactly one Stage-1 screen only. No portfolio optimizer, fees-based trading replay, paper/live execution, production integration, external holdout claims, or 2024–2026 data access.

## 1. Source, universe, timestamps, boundaries

- Universe, in fixed order: BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT. Source: authentic Binance **Spot** 1h OHLCV; timestamps use UTC candle **open time**. Fetch/cache only 2021-11-01 00:00 UTC through 2023-12-31 23:00 UTC; data from 2024+ is prohibited even for warmup.
- New isolated S4 research data cache and builder. Inspect the actual base branch: it does **not** contain the S3-only historical_data_loader.py or s3_p1_train_only.py. Implement a minimal dedicated reader/fetcher if necessary, with no silent dependency on the S3 branch. Cache raw-source provenance and SHA256.
- Every decision date t: feature cutoff t 00:00 UTC; decision 00:05; last input hourly candle has open timestamp t−1h (23:00 previous day) and closes by 00:00; assumed feasible execution proxy is 01:00 UTC open of t and t+1 day. The proxy is not a live fill guarantee.
- For each asset i: y(i,t) = ln(open(i,t+1 day at 01:00)/open(i,t at 01:00)). Price at either execution time may NEVER enter features for that decision. Require authentic strictly positive endpoint prices.
- Complete-case: raw hourly bars and all required derived features must be authentic and valid. If an input's 168h feature tensor or its trailing feature history intersects a missing/invalid bar, exclude the decision; do not zero-impute or interpolate. Conservatively exclude a label if its 24h execution interval contains a missing/invalid market bar, even if both endpoint opens exist; list exclusions. Known gap candidate: 2023-03-24 13:00 UTC, but independently audit actual data.
- Strict as-of: a prior daily label can update online volatility/rolling states only after its end at 01:00; at t 00:00 the newest eligible daily label is ordinarily from t−2. No 2023 realized label can update model weights, alpha, feature scalers, or clipping; completed 2023 labels may update the pre-frozen causal volatility state at their lawful availability time.
- 2022 is model development; 2023-01-01 through 2023-12-30 decisions are a **ONE_SHOT_REUSED_INTERNAL_SCREEN**. The 2023 period was previously inspected/used as S3 Train, so it is not a pristine OOS or independent external holdout. Exclude 2023-12-31 decision to avoid 2024 label access. 2024–2026 remains REUSED_DIAGNOSTIC_NOT_ACCESSED.

## 2. Input feature tensor — frozen

Input shape for neural: [batch, 168 hourly observations, 4 assets, 6 features], last observation is the 23:00–00:00 closed candle. Per asset/bar the exact six channels are:
1. ln(close[h]/close[h−1h]);
2. ln(close[h]/close[h−24h]);
3. ln(close[h]/close[h−72h]);
4. ln(close[h]/close[h−168h]);
5. Sample standard deviation of the last 168 authentic consecutive 1h log returns (ddof=1), without annualization;
6. volume[h]/max(arithmetic mean(volume[h−167h:h]),1e−12), using authentic Binance Spot base-asset volume.

Every historical point in a sample must have all six channels calculable without a missing intermediary bar, including required pre-lookback feature history. This strict rule may remove multiple days around a single gap; document exact dates/counts. No S3 availability-mask channel or fillna(0) substitute. No news, funding, macro, portfolio weights, gate, cash, or transaction-cost features.

Input feature normalization: for each of six feature channels compute one mean and population standard deviation (ddof=0) across all **fit-partition** asset/hour observations; apply the same six parameters to all assets, and freeze before validation. If a fitted std <1e−12 or any input is nonfinite, fail the affected fold/protocol. Do not fit transformations on 2023.

Neural receives this standardized tensor. Ridge sees the exact same standardized tensor flattened deterministically into [168×4×6] channels in time-major, asset-major, feature-major order and outputs four forecasts. This is shared information parity, not parameter-count parity. Same eligible date set and targets for both.

## 3. Daily causal sigma and targets — frozen

For each asset, process valid, **completed** past daily execution-to-execution log labels in chronological order. EWMA mean and second raw moment use lambda = 2^(−1/20); initialize each EWMA moment with the arithmetic mean of the first 30 completed valid warmup labels, then update once per additional completed valid label (no update for missing day). The first 30 samples exist for warmup only; sigma valid from the next eligible decision with 30 completed observations.

Raw variance = max(EWMA(y²)−EWMA(y)²,0); raw sigma = sqrt(variance). At each fold, floor epsilon_i = max(0.0001, 0.1×median(raw sigma on eligible fit-partition decision dates)). Use only fit rows to estimate epsilon. For final 2023 screen refit floors once using eligible 2022 development dates. As-of effective sigma(i,t) = max(raw sigma(i,t), epsilon_i). Store timestamp of most recent completed label used for each sigma.

Standardized realized target z(i,t)=y(i,t)/sigma(i,t). The **training** target is clip(z,−4,+4); squared-error neural objective and penalized squared-error Ridge objective use identical clipped target. A clipped-target squared-loss forecast estimates a robust surrogate E[clip(z)|X], **not** automatically raw E[y|X]. Never claim downstream calibrated mean returns solely from training loss.

For evaluation, primary realized target remains **raw unclipped** z; report clipped-target IC as secondary. Forecast on return scale: yhat(i,t)=zhat(i,t)×sigma(i,t). Calibration is diagnosed on original unclipped y.

## 4. Chronological split and Ridge selection — frozen

Development expanding-window folds (all dates 2022):
- Fold 1: nominal fit 2022-01-01..2022-04-30; validate 2022-05-01..2022-06-15.
- Fold 2: nominal fit 2022-01-01..2022-06-15; validate 2022-06-16..2022-07-31.
- Fold 3: nominal fit 2022-01-01..2022-07-31; validate 2022-08-01..2022-09-30.
- Fold 4: nominal fit 2022-01-01..2022-09-30; validate 2022-10-01..2022-12-30.

For each fold, remove nominal fit rows with label completion **after** first validation decision cutoff. Typically this removes the immediately preceding day's decision. Validate only dates with completed labels by end of validation window. Fit input transforms and sigma floors using eligible nominal fit rows; warmup causal history may precede 2022 without using future target information.

Ridge is standard multi-output L2-regularized least squares on the flattened identical input, with intercept, the exact alpha grid [0.001,0.01,0.1,1,10,100,1000,10000]. Choose alpha minimizing the arithmetic mean of the four fold mean squared errors on clipped standardized labels; exact ties choose the **largest** alpha. No other Ridge search.

Final model train rows are decisions in 2022 with y completion <= 2023-01-01 00:00 UTC; specifically 2022-12-31 decision excluded. Freeze input scaler, floor, Ridge alpha and both model weights after 2022 training. 2023 prediction loop is strictly frozen model plus causal, algorithmically predetermined input/sigma updates. No retrain or tuning after looking at 2023 scores.

## 5. ONE shared neural model — fixed, small

Architecture: shared one-layer PyTorch GRU(input_size=6, hidden_size=16, num_layers=1, batch_first=True) processing each asset's 168-step history with shared weights. Last hidden embeddings form [batch,4,16]; one MultiheadAttention(embed_dim=16,num_heads=2,batch_first=True,dropout=0) across 4 assets; residual+LayerNorm(16); **shared** Linear(16,1) maps each contextual asset embedding to one standardized 24h forecast. No asset-specific output heads, no portfolio-state fusion, no cash head, no binary gate, no covariance forecast, no separate models. Assert <= 5,000 trainable parameters. No separate model architecture search.

Training: set Python random, NumPy and PyTorch seeds to 42 **before** model construction; CPU as canonical deterministic device (record PyTorch/version/device); torch.use_deterministic_algorithms(True), single-thread if feasible. Initialize using PyTorch default seeded parameters. AdamW(lr=0.001, weight_decay=0.001), batch_size=32, fixed 30 epochs, fixed ordered chronological batches (shuffle=False), no LR scheduler, no dropout, no early stopping, final epoch weights only. Mean squared error over four clipped standardized targets. No hyperparameter tuning or additional seeds. A one-time fixed 2022 fit suffices: neural CV is not required for parameter selection, and 2023 cannot serve as early stopping.

Training failure (nonfinite loss, wrong shape, broken reproducibility, missing data) is a **technical/protocol failure**, not predictive NOT_SUPPORTED. Fix implementation-caused faults without changing scientific hyperparameters or reopening 2023 scores. If a protocol/architecture change is economically meaningful after a 2023 screen, require a separate new pre-registration and new genuinely future validation population; do not rerun 2023 and present it as one shot.

## 6. Primary statistic and paired uncertainty — frozen

Use the common eligible **date intersection across all 4 assets and both forecasters**; do not cherry-pick per-asset evaluation calendars. Require >=300 common 2023 dates, each with finite targets, predictions and causal volatility. Otherwise INCONCLUSIVE / DATA_INSUFFICIENT.

Per asset and model on those dates, IC_i(model)=PearsonCorr(zhat_i,t,z_i,t) with **raw unclipped standardized z**. S(model) = tanh((sum_i atanh(IC_i(model)))/4). Primary ΔS=S(Neural)−S(Ridge). If constant series or undefined correlation, mark INCONCLUSIVE, never drop the asset. Do not pool 4×T rows pretending they are independent.

Paired stationary bootstrap by joint date vector (4 actuals, 4 neural forecasts, 4 Ridge forecasts, relevant flags), with Politis–Romano geometric blocks, circular date indexing, mean block lengths 14 (primary), 7 and 21 days (sensitivity). Each length exactly 2000 bootstrap draws; use isolated NumPy RNG seed=42 per block length, preserving all same-date asset and model dependence. Report two-sided 95% **percentile** confidence interval of ΔS, along with valid draw count; if >1% draws invalid/nonfinite, INCONCLUSIVE. Bootstrap assumes approximate stability and is conditional on the frozen, reused 2023 screen; it is not an independent external significance guarantee.

Secondary diagnostics, never re-rank them into primary results:
- Common/relative standardized decomposition: at each date take means of actual z across 4 assets and means of each model's zhat across 4; compute common market time-series correlation for each model. For each asset subtract its contemporaneous cross-asset mean from actual and predicted standardized returns; compute asset-wise Fisher-z relative IC aggregate and comparative Δ. Do not label spot-long-only relative result market-neutral.
- Per-asset Mincer–Zarnowitz y=alpha+beta*yhat+error on **unclipped** execution return scale, with intercept and uncertainty; report slope/intercept, standard deviation and bps scale.
- BTC-relative spread sign accuracy for ETH−BTC, SOL−BTC, BNB−BTC only on dates where |predicted return-scale spread| > 0.0024; report sample count/coverage; 24 bps is a diagnostic threshold, not established break-even trading cost.
- Drop exactly ceil(0.05×N_common_dates) days with largest absolute equal-weight average of four **raw log execution returns**, ties break by ascending UTC date; recompute both S and ΔS, no retrain or data selection.
- First half of 2023 vs second half by UTC date, and raw-vs-clipped target IC, each labeled diagnostic.
- Explicit valid-date count, discarded dates and causes, block-length 7/14/21 sensitivity, and actual S3 historical use of 2023.

## 7. Precommitted Stage-1 decision — exactly three substantive statuses

A **SUPPORTED** result requires ALL: (a) >=300 eligible common dates; (b) S(Neural)>0; (c) **primary 14-day paired 95% CI lower bound for ΔS strictly >0**; (d) finite per-asset MZ slopes, at least 3 of 4 positive AND median of the four positive; (e) extreme-day-excluded ΔS>0. This is only **incremental predictive information on reused internal 2023**, not confirmed out-of-sample alpha. Block 7/21 or common/relative diagnostics can qualify stability but cannot be used to swap the primary test post hoc.

**NOT_SUPPORTED** if sample/protocol valid AND either S(Neural)<=0 OR primary 14-day 95% ΔS **upper CI<=0**. Explain that this rejects support for *this particular specification under this screen*, not all nonlinear prediction or neural trading.

**INCONCLUSIVE** for every remaining valid-screen case, including CI straddling/touching zero, MZ or extreme-day corroboration failures, block-length contradictions materially undermining stability, or insufficient/undefined data. A hard protocol integrity defect is explicitly **INVALID_PROTOCOL** (a technical outcome outside the three scientific verdicts); do not manufacture economic verdicts from broken data.

For all verdicts: NO 2023 re-tuning/repeat, no expansion to 2024–2026, no training until one-shot selection has been frozen, no automatic Stage 2. If SUPPORTED, Stage 2 requires a separate user decision, explicitly recognizing statistical/holdout limitations.

## 8. Implementation boundaries and deliverables

- Isolate new S4 code, tests, CLI and evidence under S4 names. Suggested locations: btc_scraper/research/s4_forecast.py, scripts/run_s4_stage1_screen.py, tests/research/test_s4_forecast.py, research/s4_forecast_information_screening/stage1_evidence/. Adjust to actual branch layout, report deviations.
- Preflight must confirm this document was committed **before** generating any 2023 forecast or IC. Tests may use tiny synthetic handcrafted prices and as-of timestamps; no 2023 experimentation before freeze.
- Implement tests for: timestamp cutoff/label boundaries and 2022-12-31 purge; 2023-12-31 excluded; missing-hour fail-closed; no future inputs; EWMA sigma uses only completed labels (t−2 as latest at t cutoff); fold-local scaler/floor; identical sample/tensor for neural and Ridge; seeding before initialization; deterministic outputs; bootstrap joint-date resampling and decision classification.
- A single manual, bounded CLI should prepare 2021–2023 raw provenance, conduct 2022-only selection/fitting, then unlock **one** 2023 screen on the frozen models. Never run as a daemon or unbounded observer. Have an explicit development-only preflight option and an explicit one-shot screen option.
- Evidence: frozen experiment config and SHA, data/source manifest with window/symbols/gaps/exclusions, 2022 Ridge CV scores, training trace, 2023 timestamped immutable paired predictions, primary IC and ΔS with 95% bootstrap CI/sensitivity, MZ/relative/extreme diagnostics, honest three-state scientific verdict, and a short report. Keep artifact names deterministic and avoid silently overwriting a completed 2023 screen.
- Do not modify main, the S3 closure branch, crypto production runtime, CARM observer, trading services, credentials, or execution account state. No broker adapters or optimizer/simulator. Report commit SHA, tests actually run, data availability, actual evidence and verdict; no claims of statistical or economic success based on tests alone.

## 9. Authorization state after committing this document

~~~text
S3_RESEARCH                  = CLOSED_NEGATIVE_EXPLORATORY
S4_RESEARCH                  = AUTHORIZED_STAGE1_ONLY
S4_P0_EXECUTABLE_PREREG      = FROZEN
S4_STAGE1_IMPLEMENTATION     = AUTHORIZED
S4_2022_MODEL_FITTING        = AUTHORIZED_AFTER_CODE_PRECHECK
S4_2023_ONE_SHOT_SCREEN      = AUTHORIZED_AFTER_FREEZE_AND_PREFLIGHT
S4_2024_2026_ACCESS         = NOT_AUTHORIZED
S4_STAGE2_CONVEX_ALLOCATOR   = NOT_AUTHORIZED
PRODUCTION_PROMOTION         = NOT_AUTHORIZED
~~~

**Research stop:** After exactly one bounded 2023 Stage-1 screen, publish SUPPORTED / NOT_SUPPORTED / INCONCLUSIVE (or explicit INVALID_PROTOCOL), then STOP. Do not start Convex L1 based on a technical PASS.
