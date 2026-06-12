# Implementation Plan: Adaptive ML Model Fixes

## Status: MOSTLY FIXED ✅ (as of 2026-06-13)

### Already Resolved ✅
1. **Time-aligned MTF** — `generate_labeled_trades()` uses `get_closed_candles()` to prevent lookahead bias
2. **TimeSeriesSplit validation** — both training scripts use `TimeSeriesSplit(n_splits=5)` instead of shuffled K-fold
3. **Temporal holdout evaluation** — 80/20 split by time order with separate holdout ROC-AUC reporting
4. **Unified FEATURE_SCHEMA** — all training uses `build_meta_features()` returning 14 canonical fields
5. **Proper documentation** — saves CV ROC-AUC, holdout ROC-AUC, and training methods

**Latest metrics (train_report.json, 2026-06-13 01:56):**
- CV ROC-AUC: 0.6361 ± 0.0218
- **Holdout ROC-AUC: 0.6408** ← validates time-series generalization  
- Samples: 992 (793 train, 199 holdout)
- Win rate: 42.44%

### Remaining Minor Concerns ⚠️
1. **Runtime feature alignment** — `signal_score.py` uses `features_from_analysis()` (includes legacy fields) but model was trained on 14 FEATURE_SCHEMA fields. Verify saved model has exactly those feature names.
2. **Meta model calibration** — high-probability buckets (0.6-1.0) show calibration errors >10%, suggesting overconfidence.
3. **Zero-importance features** — `volume_ratio` and `fear_greed` show 0.0 importance in meta_feature_importance.json.
4. **Drift detection recalibration** — continuous learning threshold (0.53) was set pre-fixes; may need adjustment.

## Scope
- `train_april_model.py` ✅ Fixed
- `scripts/continuous_learning.py` ✅ Fixed  
- `btc_scraper/signal_score.py` ⚠️ Minor concern
- `btc_scraper/feature_extractor.py` ✅ Working
- `btc_scraper/meta_model.py` ✅ Working
- `logs/train_report.json` and `logs/meta_model.json` ✅ Verified

## Proposed Workstreams

### 1. Verify Runtime Feature Alignment ✅ → 1-2 hours
Confirm `signal_score.py` correctly maps features when loading `adaptive_model.joblib`.
- Check that model.get("features") matches the 14 FEATURE_SCHEMA fields
- Verify `features_from_analysis()` produces all required fields (it has legacy extras but includes all 14)
- No changes needed if alignment is correct

### 2. Recalibrate Drift Detection Threshold (Optional)
Current threshold: 0.53 holdout ROC-AUC. Given new training pipeline:
- Run historical continuous_learning on past data windows
- Measure holdout ROC-AUC distribution
- Set threshold at 10th percentile to avoid false negatives
- Update DRIFT_THRESHOLD in `scripts/continuous_learning.py`

### 3. Investigate Zero-Importance Features
`volume_ratio` and `fear_greed` have 0.0 importance in meta model:
- Check data quality in `logs/adaptive_signals.json`
- Verify these fields are being populated at training time
- Consider removing if consistently zero or replacing with better alternatives

### 4. Improve Meta Model Calibration (Optional)
High-probability buckets (0.6-1.0) show calibration errors 10-22%:
- Consider using `CalibratedClassifierCV` with more splits
- Or adjust regression weights in high-confidence region
- This is low priority unless model is used for position sizing decisions

## Previous Proposed Workstreams (Archived—Now Complete)

## Milestones

### ✅ Milestone 1: Safe Model Repair (COMPLETE)
- ✅ Implemented time-aligned MTF via `get_closed_candles()`
- ✅ Unified feature schema with `build_meta_features()` (14 FEATURE_SCHEMA fields)
- ✅ Replaced `StratifiedKFold(shuffle=True)` with `TimeSeriesSplit(n_splits=5)`
- ✅ Added temporal 80/20 holdout with separate evaluation
- Deliverable: `train_report.json` with CV=0.6361, holdout=0.6408

### ⚠️ Milestone 2: Runtime Verification (IN PROGRESS)
- Verify `signal_score.py` loads adaptive model with correct features
- Confirm no runtime feature misalignment
- Optional: recalibrate drift detection threshold
- Optional: investigate zero-importance features
- Deliverable: validated end-to-end pipeline

### 📋 Milestone 3: Production Monitoring (RECOMMENDED)
- Add shadow logging of meta model predictions
- Monitor calibration error rates over time
- Establish alerts for drift detection
- Quarterly retraining with updated holdout evaluation
- Deliverable: monitoring dashboard and retraining procedures

## Risks and Mitigations
- **Risk:** Runtime feature mismatch if adaptive_model.joblib has different feature names than FEATURE_SCHEMA
  - Mitigation: Verify saved model features match FEATURE_SCHEMA in next review
- **Risk:** Zero-importance features may indicate data quality issues or schema misalignment
  - Mitigation: Check `adaptive_signals.json` for NULL values in volume_ratio, fear_greed
- **Risk:** Meta model calibration errors at high probabilities could cause aggressive position sizing
  - Mitigation: Use capped position sizing or recalibrate with more data

## Next Actions

### Immediate (1-2 hours)
1. Load `logs/adaptive_model.joblib` and verify `model_bundle["features"]` == `FEATURE_SCHEMA` (14 fields)
2. Trace `features_from_analysis()` to confirm all 14 canonical fields are present at runtime
3. Check `logs/adaptive_signals.json` for NULL values in volume_ratio and fear_greed

### Short-term (optional, 1-2 weeks)
1. Run continuous_learning on historical windows to recalibrate drift threshold
2. Add monitoring dashboard showing holdout performance over time
3. Establish quarterly retraining schedule with holdout validation

### Long-term (after verification)
1. Archive old training reports and keep only current best model
2. Document feature schema and keep immutable (new features → new model version)
3. Implement automated calibration checks as part of retraining pipeline
