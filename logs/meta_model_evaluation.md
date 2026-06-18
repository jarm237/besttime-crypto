# Meta Model Evaluation Report

## Summary

- Model version: v3.0
- n_samples: 21482
- n_features: 41
- CV AUC (mean ± std): 0.6277 ± 0.0117
- CV Accuracy: 0.5865
- Ensemble CV AUC: 0.6265
- Ensemble CV Accuracy: 0.5879
- Calibration: isotonic (selected)
- Calibrated: true

## Label distribution

- WIN: 10187
- LOSS: 11295

## Key metrics (walk-forward)

- Fold 1: ROC AUC = 0.6385, Accuracy = 0.5916
- Fold 2: ROC AUC = 0.6388, Accuracy = 0.5950

## Calibration buckets (summary)

- 0.0-0.4: count=925, actual_wr=31.6, predicted_wr=20.0, error=11.6 (not calibrated)
- 0.4-0.6: count=1858, actual_wr=48.9, predicted_wr=50.0, error=-1.1 (calibrated)
- 0.6-0.7: count=229, actual_wr=66.8, predicted_wr=65.0, error=1.8 (calibrated)
- 0.7-0.8: count=147, actual_wr=74.1, predicted_wr=75.0, error=-0.9 (calibrated)
- 0.8-1.0: count=64, actual_wr=73.4, predicted_wr=90.0, error=-16.6 (not calibrated)

## Top feature importance (top 10)

1. rsi: 0.0850
2. distance_resistance_pct: 0.0602
3. macd_hist: 0.0505
4. return_1d: 0.0446
5. mfi: 0.0436
6. roc_14: 0.0429
7. mtf_alignment: 0.0403
8. adx: 0.0396
9. return_15m: 0.0377
10. ema_distance_zscore: 0.0363

## Observations

- Model performance (AUC ~0.63) is modest but above random; useful for signal ranking rather than deterministic trade decision.
- Calibration is acceptable in middle buckets but poor at extremes (especially high-confidence 0.8-1.0).
- Feature importances indicate momentum and volatility features dominate; regime flags have little weight.

## Recommendations

1. Improve calibration for extreme high-confidence bucket (0.8-1.0): collect more calibration samples or apply isotonic with larger calibration set.
2. Explore class-balanced ensemble or cost-sensitive training to improve accuracy.
3. Consider stacking a lightweight neural net on top for non-linear combinations.
4. Monitor live performance and adapt weights with recent data (online reweighting).
5. Add uncertainty estimates (prediction intervals) and more robust backtesting on recent out-of-sample periods.

## Next steps

- Run an offline evaluation script to compute precision/recall, Brier score, and PR-AUC on recent holdout.
- Measure inference latency by loading `logs/meta_model.joblib` and timing predictions on sample batch.

---
Report generated automatically from `logs/meta_model.json` and `logs/meta_feature_importance.json`.
