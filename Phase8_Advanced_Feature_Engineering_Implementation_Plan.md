# Phase 8 — Advanced Feature Engineering Implementation Plan

> Project: `besttime-crypto` — AI Quant Trading Platform  
> Phase: **8 — Advanced Feature Engineering**  
> Goal: tăng chất lượng alpha bằng cách nâng cấp nhãn huấn luyện, feature store, regime-aware features và validation pipeline.  
> Created: 2026-07-02
> Last Progress Update: 2026-07-02

---

## 0. Implementation Progress (Live)

### Current Status

- Phase 8 implementation has started.
- Sprint 1 (Foundation) is implemented in code.
- Sprint 2 (Triple Barrier Labeling) is implemented in code.
- Sprint 3 (Meta Labeling) is implemented in code.
- Sprint 4 (Regime and Causal Features) is implemented in code.
- Sprint 5 (Alternative Data Features) is implemented in code.
- Sprint 6 (Cross-Sectional Features) is implemented in code.
- Runtime execution in current shell is blocked by missing Python dependencies.

### Completed in Repository

- Added new package: `btc_scraper/feature_engineering/`.
- Implemented `feature_store.py` with:
  - Feature Store v2 folder bootstrap.
  - Table save/load (parquet/csv).
  - Feature metadata registry.
  - Dataset version metadata + source hash.
- Implemented `triple_barrier.py` with:
  - LONG/SHORT support.
  - ATR-based dynamic barriers.
  - TP/SL/timeout outcomes.
  - MFE/MAE and barrier diagnostics fields.
- Implemented `label_engine.py` as orchestration entrypoint.
- Implemented `meta_labeling.py` with:
  - Primary signal/direction extraction.
  - Meta label generation (`execute` vs `skip`).
  - Trade quality scoring and bucketization (A/B/C/D).
- Implemented `regime_features.py` with:
  - Regime normalization and confidence fields.
  - Regime duration and transition probability features.
  - Regime one-hot features and interaction terms.
- Implemented `causal_features.py` with:
  - Causal risk normalization and one-hot encoding.
  - Context adjustment and causal diagnostics fields.
  - Counterfactual feature outputs (`cf_delta_pnl`, intervention fields).
- Implemented `alternative_features.py` with:
  - Point-in-time-safe z-score, momentum, rank, and change transforms.
  - Composite alternative features (macro stress, on-chain strength, sentiment spread, liquidity risk).
  - Missing-data handling and quality report generation.
- Implemented `cross_sectional_features.py` with:
  - Coin ranking per timestamp from point-in-time returns.
  - Relative strength vs BTC and ETH baselines.
  - Sector/cluster-aware ranking and group excess-return features.
- Added scripts:
  - `scripts/build_feature_store_v2.py`.
  - `scripts/generate_triple_barrier_labels.py`.
  - `scripts/generate_meta_labels.py`.
  - `scripts/build_regime_features.py`.
  - `scripts/build_causal_features.py`.
  - `scripts/build_alternative_features.py`.
  - `scripts/build_cross_sectional_features.py`.
- Added tests:
  - `tests/test_feature_store.py`.
  - `tests/test_triple_barrier.py`.
  - `tests/test_meta_labeling.py`.
  - `tests/test_regime_features.py`.
  - `tests/test_causal_features.py`.
  - `tests/test_alternative_features.py`.
  - `tests/test_cross_sectional_features.py`.

### Environment Blockers (Current Machine)

- `python3 scripts/build_feature_store_v2.py` failed because `pandas` is not installed in the active Python environment.
- `python3 scripts/generate_triple_barrier_labels.py ...` failed for the same reason.
- `python3 -m pytest ...` failed because `pytest` is not installed in the active Python environment.

### Next Execution Step (After Environment Ready)

Run in repo root:

```bash
python3 -m pip install -r requirements.txt
python3 scripts/build_feature_store_v2.py
python3 scripts/generate_triple_barrier_labels.py \
  --input logs/adaptive_signals_v2.json \
  --output data/feature_store/labels/triple_barrier_labels.parquet \
  --data-dir data \
  --timeframe 15m
python3 scripts/generate_meta_labels.py \
  --input data/feature_store/labels/triple_barrier_labels.parquet \
  --output-meta data/feature_store/labels/meta_labels.parquet \
  --output-trade-quality data/feature_store/labels/trade_quality_labels.parquet
python3 scripts/build_regime_features.py \
  --input logs/adaptive_signals_v2.json \
  --output data/feature_store/regime/regime_features.parquet
python3 scripts/build_causal_features.py \
  --input logs/adaptive_signals_v2.json \
  --output data/feature_store/causal/causal_features.parquet
python3 scripts/build_alternative_features.py \
  --input data/alternative_data.json \
  --output data/feature_store/derived/alternative_features.parquet \
  --quality-report data/feature_store/derived/alternative_feature_quality_report.json
python3 scripts/build_cross_sectional_features.py \
  --input logs/adaptive_signals_v2.json \
  --output data/feature_store/derived/cross_sectional_features.parquet
```

---

## 1. Executive Summary

Phase 8 tập trung vào việc biến dữ liệu thô và dữ liệu alternative từ Phase 7 thành **feature có giá trị giao dịch thực tế**.

Hiện tại hệ thống đã có:

- Technical indicators: RSI, EMA, SMA, MACD, ATR, Bollinger Bands, Chandelier.
- ML Ensemble: RandomForest, LightGBM, CatBoost, XGBoost.
- Causal World Model.
- WorldState.
- FeatureSnapshot.
- Continuous Learning weekly.
- RL Exit Manager.
- Portfolio Manager.

Vấn đề hiện tại không còn nằm ở việc thiếu model, mà nằm ở:

```text
Data quality
    ↓
Label quality
    ↓
Feature quality
    ↓
Validation quality
    ↓
Real alpha
```

Phase 8 sẽ bổ sung:

1. Meta-labeling.
2. Triple Barrier Labeling.
3. Feature Store v2.
4. Regime-aware features.
5. Fractional Differencing.
6. Cross-sectional crypto features.
7. Feature quality monitoring.
8. Leakage prevention.
9. Feature selection pipeline.
10. ML dataset v3.

---

## 2. Target Architecture

```text
Raw Market Data
Alternative Data
Closed Trades
WorldState Snapshots
Causal Context Logs
        ↓
Feature Store v2
        ├── raw/
        ├── clean/
        ├── normalized/
        ├── labels/
        ├── derived/
        ├── causal/
        ├── regime/
        └── training/
        ↓
Feature Builder
        ├── Technical Features
        ├── Alternative Data Features
        ├── Causal Features
        ├── Regime Features
        ├── Cross-Sectional Features
        └── Meta Features
        ↓
Label Engine
        ├── Triple Barrier Labeling
        ├── Meta Labeling
        ├── Time-to-Event Labeling
        └── Trade Quality Labeling
        ↓
Feature Validator
        ├── Missing Value Check
        ├── Leakage Check
        ├── Correlation Filter
        ├── Stability Check
        └── Drift Check
        ↓
ML Dataset v3
        ↓
Meta Model Ensemble
        ↓
Causal Context Provider
        ↓
Decision Engine
```

---

## 3. Main Objectives

| Objective | Description |
|---|---|
| Improve label quality | Replace simple WIN/LOSS with richer trading labels. |
| Improve alpha features | Build regime, causal, liquidity, on-chain, macro and cross-sectional features. |
| Reduce leakage | Prevent future data from leaking into training. |
| Improve robustness | Make features stable across market regimes. |
| Improve explainability | Each prediction should be traceable to feature groups. |
| Improve retraining | Make continuous learning safer and more consistent. |

---

## 4. Folder Structure

Recommended new structure:

```text
btc_scraper/
  feature_engineering/
    __init__.py
    feature_store.py
    label_engine.py
    triple_barrier.py
    meta_labeling.py
    fractional_diff.py
    regime_features.py
    causal_features.py
    alternative_features.py
    cross_sectional_features.py
    feature_validator.py
    feature_selector.py
    dataset_builder_v3.py

  scripts/
    build_feature_store_v2.py
    generate_triple_barrier_labels.py
    generate_meta_labels.py
    build_ml_dataset_v3.py
    validate_feature_quality.py
    feature_importance_report.py

data/
  feature_store/
    raw/
    clean/
    normalized/
    labels/
    derived/
    causal/
    regime/
    training/

logs/
  feature_quality/
  label_quality/
  dataset_versions/
```

---

## 5. Dataset Versioning

Every training dataset should be versioned.

Example:

```text
data/feature_store/training/
  ml_dataset_v3_2026_07_02.parquet
  ml_dataset_v3_2026_07_09.parquet
  ml_dataset_v3_2026_07_16.parquet
```

Metadata:

```json
{
  "dataset_version": "v3_2026_07_02",
  "created_at": "2026-07-02T00:00:00Z",
  "row_count": 18908,
  "feature_count": 120,
  "label_type": "triple_barrier_meta",
  "lookahead_bars": 48,
  "timeframe": "15m",
  "source_hash": "sha256...",
  "feature_groups": [
    "technical",
    "alternative",
    "causal",
    "regime",
    "cross_sectional"
  ]
}
```

---

## 6. Label Engineering

### 6.1. Current Problem

Current label:

```text
Trade closed with profit → WIN
Trade closed with loss   → LOSS
```

This is too simple.

Problems:

- It ignores path dependency.
- It ignores whether TP or SL was hit first.
- It ignores holding time.
- It ignores opportunity cost.
- It does not distinguish good signal from lucky exit.
- It can make the model learn noise.

---

## 6.2. Triple Barrier Labeling

Triple Barrier Labeling adds 3 exit conditions:

```text
Upper barrier: Take Profit
Lower barrier: Stop Loss
Vertical barrier: Timeout
```

For each signal:

```text
Entry time = t0
Entry price = P0

Upper barrier = P0 + ATR * tp_mult
Lower barrier = P0 - ATR * sl_mult
Vertical barrier = t0 + max_holding_bars
```

Label:

| Outcome | Label |
|---|---|
| TP hit first | `+1` |
| SL hit first | `-1` |
| Timeout first | `0` |

For SHORT:

```text
Upper/lower logic is reversed.
```

Recommended default parameters:

```python
triple_barrier_config = {
    "timeframe": "15m",
    "max_holding_bars": 48,
    "tp_atr_mult": 2.0,
    "sl_atr_mult": 1.2,
    "use_dynamic_atr": True,
    "min_rr": 1.3
}
```

Output schema:

```python
triple_barrier_label
triple_barrier_reason
barrier_hit_time
barrier_hold_bars
barrier_return_pct
barrier_mfe_pct
barrier_mae_pct
```

---

## 6.3. Meta Labeling

Meta-labeling changes the ML problem.

Primary model:

```text
Rule / Strategy Engine → BUY / SELL / NEUTRAL
```

Meta model:

```text
Should we execute this signal?
```

Target:

```text
1 = execute signal
0 = skip signal
```

This helps the model filter bad rule-based signals instead of trying to predict market direction from scratch.

Recommended logic:

```python
if primary_signal in ["BUY", "SELL", "STRONG_BUY", "STRONG_SELL"]:
    meta_label = 1 if triple_barrier_label == expected_direction else 0
else:
    meta_label = None
```

Output schema:

```python
primary_signal
primary_direction
triple_barrier_label
meta_label
meta_label_reason
```

---

## 6.4. Trade Quality Label

Add quality labels beyond win/loss.

```python
trade_quality_score = (
    0.35 * normalized_return
    + 0.25 * rr_quality
    + 0.20 * low_drawdown_quality
    + 0.10 * fast_resolution_quality
    + 0.10 * regime_alignment_quality
)
```

Buckets:

| Score | Bucket |
|---:|---|
| >= 0.75 | `A` |
| >= 0.55 | `B` |
| >= 0.35 | `C` |
| < 0.35 | `D` |

Use case:

- Position sizing.
- Signal ranking.
- Portfolio allocation.
- Model evaluation.

---

## 7. Feature Groups

### 7.1. Technical Features

Existing features should be retained and standardized.

```python
rsi_14
macd_hist
ema9_slope
ema21_slope
sma50_slope
sma200_slope
atr_pct
bb_width_pct
volume_ratio
chandelier_state
distance_to_support
distance_to_resistance
bos_flag
choch_flag
```

New technical features:

```python
return_1
return_3
return_6
return_12
return_24
realized_vol_20
realized_vol_50
volatility_ratio
trend_efficiency
range_position_20
range_position_50
candle_body_pct
upper_wick_pct
lower_wick_pct
```

---

### 7.2. Alternative Data Features

From Phase 7:

```python
exchange_netflow
exchange_inflow_zscore
exchange_outflow_zscore
whale_transfer_count
whale_transfer_volume
whale_score
stablecoin_supply_change_1d
stablecoin_supply_change_7d
stablecoin_momentum
tvl_change_1d
tvl_change_7d
etf_netflow
etf_flow_zscore
options_iv
options_iv_rank
options_skew
orderbook_imbalance
liquidation_pressure
funding_dispersion
open_interest_delta
```

---

### 7.3. Causal Features

From Causal World Model:

```python
causal_risk_level
causal_risk_raw
causal_alpha
causal_context_adjustment
causal_overridden
causal_context_skipped
causal_primary_path_confidence
causal_num_rules_fired
causal_num_active_edges
cf_delta_pnl
cf_intervention_node
cf_intervention_value
```

Convert categorical causal fields:

```python
causal_risk_LOW
causal_risk_MEDIUM
causal_risk_HIGH
causal_risk_CRITICAL
```

---

### 7.4. Regime Features

Market regime should be encoded as both categorical and numerical.

```python
regime
regime_confidence
regime_duration_bars
regime_transition_probability
regime_volatility_state
regime_trend_state
regime_liquidity_state
```

One-hot:

```python
regime_bull_trend
regime_bear_trend
regime_sideway
regime_high_vol
regime_low_vol
regime_risk_on
regime_risk_off
regime_transitioning
```

Regime interaction features:

```python
rsi_x_regime_bull
funding_x_regime_risk_on
dxy_x_regime_risk_off
oi_delta_x_high_vol
orderbook_imbalance_x_trend
```

---

### 7.5. Cross-Sectional Features

Useful for ranking coins.

For each timestamp:

```python
coin_return_rank_1h
coin_return_rank_4h
coin_volume_rank
coin_volatility_rank
coin_funding_rank
coin_oi_delta_rank
coin_relative_strength_vs_btc
coin_relative_strength_vs_eth
sector_rank
```

Derived:

```python
cross_sectional_momentum_score
relative_strength_score
altcoin_rotation_score
btc_dominance_pressure
```

---

### 7.6. Time Features

```python
hour_of_day
day_of_week
is_weekend
is_us_session
is_asia_session
is_europe_session
is_fomc_day
is_cpi_day
is_nfp_day
```

---

## 8. Fractional Differencing

### Objective

Make price series more stationary without destroying memory.

Instead of using raw price:

```python
close
```

Use:

```python
fracdiff_close_d_0_4
fracdiff_log_price_d_0_4
```

Recommended implementation:

```python
def get_fracdiff_weights(d: float, threshold: float = 1e-5):
    weights = [1.0]
    k = 1
    while True:
        w = -weights[-1] * (d - k + 1) / k
        if abs(w) < threshold:
            break
        weights.append(w)
        k += 1
    return weights
```

Candidate values:

```python
d_values = [0.2, 0.3, 0.4, 0.5]
```

Selection rule:

- Use the smallest `d` that passes stationarity test.
- Preserve as much memory as possible.

---

## 9. Feature Store v2

### 9.1. Storage Format

Recommended:

```text
Parquet for tabular features
JSON for metadata
SQLite/MongoDB for indexes and query tracking
```

### 9.2. Feature Record Schema

```python
timestamp
coin
timeframe
feature_group
feature_name
feature_value
source
created_at
data_version
```

For training:

```python
timestamp
coin
timeframe
features...
labels...
metadata...
```

### 9.3. Feature Metadata

Each feature must have metadata:

```json
{
  "feature_name": "orderbook_imbalance",
  "group": "alternative",
  "source": "binance_depth_stream",
  "refresh_interval": "1s",
  "lookback_window": "5m",
  "is_point_in_time_safe": true,
  "requires_lag": true,
  "lag_bars": 1
}
```

---

## 10. Leakage Prevention

### 10.1. Rules

Every feature must obey:

```text
feature timestamp <= decision timestamp
```

Never use:

```text
future close
future high
future low
future volume
future macro release
future label outcome
```

### 10.2. Mandatory Lag

For risky features:

```python
feature_lag_bars = 1
```

Apply to:

- OHLCV-derived features.
- Alternative data.
- Macro data.
- Causal context.
- Aggregated cross-sectional features.

### 10.3. Point-in-Time Dataset Builder

Dataset builder must use:

```python
asof_join(left=signals, right=features, on="timestamp", by="coin")
```

instead of normal merge.

---

## 11. Feature Validation

### 11.1. Missing Value Check

Metrics:

```python
missing_rate
missing_rate_by_coin
missing_rate_by_feature_group
```

Threshold:

```text
Feature rejected if missing_rate > 20%
Feature warning if missing_rate > 5%
```

---

### 11.2. Correlation Filter

Remove redundant features.

```python
abs(correlation) > 0.85
```

Keep the feature with:

1. Higher predictive value.
2. Lower missing rate.
3. Better stability.
4. More interpretable source.

---

### 11.3. Stability Check

Use PSI:

```text
PSI < 0.1   stable
PSI 0.1-0.25 warning
PSI > 0.25 drift
```

---

### 11.4. Leakage Check

For each feature:

```python
corr(feature_t, label_t_future)
corr(feature_t_plus_1, label_t)
```

If future correlation is suspiciously high, mark feature as leakage risk.

---

## 12. Feature Selection Pipeline

Recommended selection stages:

```text
1. Remove invalid features
2. Remove high missing features
3. Remove leakage-risk features
4. Remove highly correlated features
5. Train baseline model
6. Compute SHAP / permutation importance
7. Keep stable predictive features
8. Validate with walk-forward split
```

Feature scoring formula:

```python
feature_score = (
    0.35 * predictive_importance
    + 0.25 * stability_score
    + 0.20 * coverage_score
    + 0.10 * interpretability_score
    + 0.10 * regime_consistency_score
)
```

---

## 13. Integration with Existing ML Pipeline

### Current

```text
adaptive_signals.json
    ↓
feature_extractor.py
    ↓
meta_model.py
    ↓
meta_confidence
```

### Target

```text
Feature Store v2
    ↓
dataset_builder_v3.py
    ↓
ml_dataset_v3.parquet
    ↓
meta_model_v3.py
    ↓
calibrated_meta_confidence
    ↓
Decision Engine
```

Recommended model targets:

| Model | Target |
|---|---|
| Direction Model | `triple_barrier_label` |
| Meta Model | `meta_label` |
| Trade Quality Model | `trade_quality_bucket` |
| Position Sizing Model | `expected_return / expected_drawdown` |

---

## 14. Integration with Causal World Model

Add feature groups into WorldState and ContextProvider.

```text
WorldState
  ├── macro
  ├── liquidity
  ├── crypto
  ├── sentiment
  ├── risk
  └── alternative
```

ContextProvider should consume:

```python
exchange_netflow
stablecoin_momentum
etf_flow_zscore
options_iv_rank
orderbook_imbalance
liquidation_pressure
funding_dispersion
```

Causal graph should add nodes:

```text
StablecoinSupply → CryptoLiquidity
ETFNetFlow → BTCDemand
OptionsIV → MarketRisk
FundingDispersion → LeverageRisk
ExchangeNetflow → SellPressure
OrderbookImbalance → ShortTermPressure
```

---

## 15. Sprint Plan

## Sprint 1 — Foundation

### Progress Snapshot

- Status: **DONE (code completed, runtime pending environment setup)**
- Completed files:
  - `btc_scraper/feature_engineering/feature_store.py`
  - `scripts/build_feature_store_v2.py`
  - `tests/test_feature_store.py`

### Tasks

- Create `feature_engineering/` package.
- Create Feature Store v2 folders.
- Define feature metadata schema.
- Build dataset versioning logic.
- Create base feature builder interface.

### Deliverables

```text
feature_store.py
dataset_version.json
feature_metadata.json
BaseFeatureBuilder
```

### Acceptance Criteria

- Can save and load feature tables.
- Can register feature metadata.
- Dataset version is generated automatically.

---

## Sprint 2 — Triple Barrier Labeling

### Progress Snapshot

- Status: **DONE (code completed, runtime pending environment setup)**
- Completed files:
  - `btc_scraper/feature_engineering/triple_barrier.py`
  - `btc_scraper/feature_engineering/label_engine.py`
  - `scripts/generate_triple_barrier_labels.py`
  - `tests/test_triple_barrier.py`

### Tasks

- Implement `triple_barrier.py`.
- Support LONG and SHORT.
- Support ATR-based dynamic barriers.
- Add MFE/MAE calculation.
- Add timeout label.

### Deliverables

```text
generate_triple_barrier_labels.py
data/feature_store/labels/triple_barrier_labels.parquet
```

### Acceptance Criteria

- Each signal has label `-1 / 0 / +1`.
- Barrier hit time is recorded.
- MFE and MAE are recorded.
- No future features leak into model features.

---

## Sprint 3 — Meta Labeling

### Progress Snapshot

- Status: **DONE (code completed, runtime pending environment setup)**
- Completed files:
  - `btc_scraper/feature_engineering/meta_labeling.py`
  - `scripts/generate_meta_labels.py`
  - `tests/test_meta_labeling.py`

### Tasks

- Implement `meta_labeling.py`.
- Convert primary signals into meta labels.
- Link rule-based signals with triple barrier outcomes.
- Add trade quality score.

### Deliverables

```text
generate_meta_labels.py
meta_labels.parquet
trade_quality_labels.parquet
```

### Acceptance Criteria

- Each executable signal gets `meta_label`.
- Neutral signals are excluded or marked as non-training.
- Trade quality bucket is generated.

---

## Sprint 4 — Regime and Causal Features

### Progress Snapshot

- Status: **DONE (code completed, runtime pending environment setup)**
- Completed files:
  - `btc_scraper/feature_engineering/regime_features.py`
  - `btc_scraper/feature_engineering/causal_features.py`
  - `scripts/build_regime_features.py`
  - `scripts/build_causal_features.py`
  - `tests/test_regime_features.py`
  - `tests/test_causal_features.py`

### Tasks

- Build `regime_features.py`.
- Build `causal_features.py`.
- Add regime one-hot features.
- Add causal risk and context adjustment features.
- Add regime interaction features.

### Deliverables

```text
regime_features.parquet
causal_features.parquet
```

### Acceptance Criteria

- Regime features are available per timestamp.
- Causal features are point-in-time safe.
- FeatureSnapshot can map to training rows.

---

## Sprint 5 — Alternative Data Features

### Progress Snapshot

- Status: **DONE (code completed, runtime pending environment setup)**
- Completed files:
  - `btc_scraper/feature_engineering/alternative_features.py`
  - `scripts/build_alternative_features.py`
  - `tests/test_alternative_features.py`

### Tasks

- Build `alternative_features.py`.
- Convert Phase 7 raw data into model-ready features.
- Add z-score, momentum, rank and change features.
- Handle missing data.

### Deliverables

```text
alternative_features.parquet
alternative_feature_quality_report.json
```

### Acceptance Criteria

- At least 20 alternative features generated.
- Missing data report created.
- Features can be joined with signal dataset.

---

## Sprint 6 — Cross-Sectional Features

### Progress Snapshot

- Status: **DONE (code completed, runtime pending environment setup)**
- Completed files:
  - `btc_scraper/feature_engineering/cross_sectional_features.py`
  - `scripts/build_cross_sectional_features.py`
  - `tests/test_cross_sectional_features.py`

### Tasks

- Build `cross_sectional_features.py`.
- Compute coin ranks per timestamp.
- Compute relative strength vs BTC and ETH.
- Compute sector/cluster ranking if coin groups exist.

### Deliverables

```text
cross_sectional_features.parquet
```

### Acceptance Criteria

- Each coin has relative strength features.
- Ranking is computed using only timestamp-safe data.
- No future coin data is used.

---

## Sprint 7 — Fractional Differencing

### Progress Snapshot

- Status: **NOT STARTED**

### Tasks

- Implement `fractional_diff.py`.
- Generate fractional differenced price features.
- Run stationarity tests.
- Select best `d` per coin/timeframe.

### Deliverables

```text
fracdiff_features.parquet
fracdiff_report.json
```

### Acceptance Criteria

- Fractional differencing works for all major coins.
- Stationarity report is generated.
- Features are optional and controlled by config.

---

## Sprint 8 — Feature Validation

### Progress Snapshot

- Status: **NOT STARTED**

### Tasks

- Implement `feature_validator.py`.
- Add missing value checks.
- Add correlation filter.
- Add leakage detection.
- Add PSI drift check.

### Deliverables

```text
feature_quality_report.json
feature_rejection_report.json
```

### Acceptance Criteria

- Features with high missing rate are flagged.
- Correlated features are grouped.
- Leakage-risk features are blocked from training.

---

## Sprint 9 — Dataset Builder v3

### Progress Snapshot

- Status: **NOT STARTED**

### Tasks

- Implement `dataset_builder_v3.py`.
- Use point-in-time joins.
- Merge features and labels.
- Export training dataset.
- Generate dataset metadata.

### Deliverables

```text
ml_dataset_v3.parquet
ml_dataset_v3_metadata.json
```

### Acceptance Criteria

- Dataset contains features + labels.
- Dataset is reproducible.
- Dataset has version metadata.
- Dataset can be used by training pipeline.

---

## Sprint 10 — ML Pipeline Integration

### Progress Snapshot

- Status: **NOT STARTED**

### Tasks

- Update `meta_model.py` or create `meta_model_v3.py`.
- Train models using new labels.
- Compare old vs new model.
- Add calibration report.
- Add feature group importance report.

### Deliverables

```text
meta_model_v3.joblib
meta_model_v3.json
calibration_report_v3.json
feature_importance_v3.json
```

### Acceptance Criteria

- New model trains successfully.
- Walk-forward validation is supported.
- Model comparison report exists.
- Old model remains fallback.

---

## 16. Config Files

Recommended config:

```json
{
  "phase8": {
    "enabled": true,
    "labeling": {
      "triple_barrier": {
        "enabled": true,
        "timeframe": "15m",
        "max_holding_bars": 48,
        "tp_atr_mult": 2.0,
        "sl_atr_mult": 1.2
      },
      "meta_labeling": {
        "enabled": true,
        "exclude_neutral": true
      }
    },
    "features": {
      "technical": true,
      "alternative": true,
      "causal": true,
      "regime": true,
      "cross_sectional": true,
      "fractional_diff": false
    },
    "validation": {
      "max_missing_rate": 0.2,
      "warning_missing_rate": 0.05,
      "max_corr": 0.85,
      "max_psi": 0.25,
      "mandatory_lag_bars": 1
    }
  }
}
```

---

## 17. Database / Storage Schema

### 17.1. MongoDB Collections

Optional collections:

```text
feature_metadata
feature_quality_reports
label_quality_reports
dataset_versions
model_training_runs
```

### 17.2. SQLite Tables

Useful for local development:

```sql
CREATE TABLE dataset_versions (
    id TEXT PRIMARY KEY,
    created_at TEXT,
    row_count INTEGER,
    feature_count INTEGER,
    label_type TEXT,
    source_hash TEXT,
    metadata_json TEXT
);

CREATE TABLE feature_quality (
    dataset_id TEXT,
    feature_name TEXT,
    missing_rate REAL,
    psi REAL,
    correlation_group TEXT,
    leakage_risk INTEGER,
    status TEXT
);
```

---

## 18. Monitoring Dashboard

Add dashboard tab:

```text
Feature Engineering
```

Panels:

- Dataset version.
- Row count.
- Feature count.
- Label distribution.
- Triple barrier outcome distribution.
- Meta label distribution.
- Missing value heatmap.
- Feature group importance.
- Top rejected features.
- Drift warning.
- Leakage warning.

---

## 19. Testing Plan

### Unit Tests

```text
tests/test_triple_barrier.py
tests/test_meta_labeling.py
tests/test_fractional_diff.py
tests/test_feature_store.py
tests/test_feature_validator.py
tests/test_dataset_builder_v3.py
```

### Integration Tests

```text
tests/test_phase8_pipeline.py
tests/test_phase8_ml_training.py
tests/test_phase8_causal_integration.py
```

### Test Cases

- LONG TP hit.
- LONG SL hit.
- LONG timeout.
- SHORT TP hit.
- SHORT SL hit.
- SHORT timeout.
- Neutral signal excluded.
- Missing feature handling.
- Correlation filter.
- Leakage check.
- Point-in-time join.

---

## 20. Success Metrics

| Metric | Target |
|---|---:|
| Dataset reproducibility | 100% |
| Feature missing rate | < 5% preferred |
| Label coverage | > 80% executable signals |
| Feature leakage incidents | 0 |
| High-correlation redundancy | < 15% after filter |
| PSI drift severe features | < 10% |
| Meta model CV ROC-AUC | improve vs v2 |
| Calibration error | lower vs v2 |
| Walk-forward stability | stable across regimes |
| Model fallback safety | old model available |

---

## 21. Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Data leakage | Very high | Mandatory lag and point-in-time join |
| Label imbalance | High | Class weights, threshold tuning |
| Too many features | High | Feature selection pipeline |
| Alternative data missing | Medium | Forward fill with max age limit |
| Overfitting | High | Walk-forward validation |
| Regime instability | Medium | Regime-aware metrics |
| Fractional diff complexity | Low/Medium | Keep optional in config |
| Training too slow | Medium | Parquet + incremental builds |

---

## 22. Recommended Implementation Order

```text
1. Feature Store v2
2. Triple Barrier Labeling
3. Meta Labeling
4. Dataset Builder v3
5. Feature Validation
6. Regime + Causal Features
7. Alternative Features
8. Cross-Sectional Features
9. Fractional Differencing
10. ML Model v3
```

Reason:

```text
Better labels first
    ↓
Better dataset
    ↓
Better features
    ↓
Better model
```

Do not add too many features before fixing label quality.

---

## 23. Final Deliverables

```text
feature_engineering/
scripts/build_ml_dataset_v3.py
scripts/generate_triple_barrier_labels.py
scripts/generate_meta_labels.py
data/feature_store/
ml_dataset_v3.parquet
meta_model_v3.joblib
feature_quality_report.json
label_quality_report.json
dashboard_feature_engineering_tab
tests/test_phase8_*.py
```

---

## 24. Definition of Done

Phase 8 is complete when:

- Triple Barrier Labeling is active.
- Meta Labeling is active.
- Feature Store v2 is operational.
- Dataset v3 is generated reproducibly.
- Feature validation blocks bad features.
- Causal, regime and alternative features are included.
- ML model v3 trains successfully.
- Model v3 is compared against v2.
- Dashboard shows feature and label quality.
- Existing system can fall back to model v2 safely.

---

## 25. Recommended First Task

Start with:

```text
btc_scraper/feature_engineering/triple_barrier.py
```

Because label quality has the highest impact on the entire ML pipeline.

Suggested first command:

```bash
python scripts/generate_triple_barrier_labels.py \
  --input data/adaptive_signals_v2.json \
  --output data/feature_store/labels/triple_barrier_labels.parquet \
  --timeframe 15m \
  --max-holding-bars 48 \
  --tp-atr-mult 2.0 \
  --sl-atr-mult 1.2
```
