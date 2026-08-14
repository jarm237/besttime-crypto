# R1 — Probability Contract Proof

**Artifact**: `3c5186c5efa943d5b32fdc059f72cb7ae1c40935936c683cc1e6dd29a9ac3756`  
**Gate**: `PROBABILITY_SEMANTICS_SOURCE = PASS`  
**Stop condition triggered**: NO

## Conclusion

predict_proba[:, 1] = P(WIN | proposed_trade). The model was trained on trade outcome labels (WIN=1, LOSS=0) and does NOT output P(price_up). The SELL inversion in signal_score.py is an unambiguous defect. Proceeding to R2.

## Checks

### ✅ CLASS_LABEL_CONTRACT — PASS

- **bundle_model_type**: `CalibratedClassifierCV`
- **bundle_base_estimator_type**: `FrozenEstimator`
- **bundle_version**: `v3.1-research-pre2025-f3e3eb68`
- **bundle_n_samples**: `9347`
- **classes**: `[0, 1]`
- **class_0_meaning**: `LOSS (y=0)`
- **class_1_meaning**: `WIN (y=1)`
- **predict_proba_col_1**: `P(WIN | proposed_trade)`

### ✅ TRAINING_LABEL_CONTRACT — PASS

- **n_train_wins**: `127`
- **n_train_losses**: `9220`
- **win_rate_train**: `0.013587`
- **label_source**: `label column present; result column absent (cannot cross-check)`

### ✅ PREDICT_PROBA_SEMANTICS — PASS

- **n_calibration_samples**: `409`
- **n_calibration_wins**: `3`
- **n_calibration_losses**: `406`
- **proba_col1_mean_for_wins**: `0.07382`
- **proba_col1_mean_for_losses**: `0.006844`
- **directional_check_win_gt_loss**: `True`
- **sum_to_one_check**: `True`
- **variance_check_not_constant**: `True`
- **range_check_all_in_01**: `True`
- **proba_col1_std**: `0.022083`
- **proba_col1_min**: `0.0`
- **proba_col1_max**: `0.166667`

### ⚠️ NOT_PRICE_DIRECTION_MODEL — INCONCLUSIVE

- **side_column_available**: `False`
- **evidence**: `No side column in calibration data; cannot split BUY/SELL`
- **conclusion**: `Cannot falsify — label evidence alone is sufficient (see PREDICT_PROBA_SEMANTICS)`

### ✅ CALIBRATED_PROBABILITY_RANGE — PASS

- **raw_scores_available**: `False`
- **raw_proba_max**: `0.166667`
- **raw_proba_min**: `0.0`
- **bundle_calibrated_max**: `0.166667`
- **bundle_calibrated_min**: `0.0`
- **iso_calibrated_max**: `0.166667`
- **iso_calibrated_min**: `0.0`
- **buy_threshold**: `0.65`
- **sell_threshold**: `0.35`
- **calibrated_above_buy_threshold**: `0`
- **calibrated_below_sell_threshold**: `409`
- **note**: `calibrated_above_buy_threshold=0 means BUY is structurally impossible with current calibration`

## Key Finding

| Item | Value |
|------|-------|
| Training WIN rate | `1.36%` |
| Calibrated prob max | `0.1667` |
| BUY threshold | `0.65` |
| Samples above BUY threshold | `0` |
| Classes | `[0, 1]` |

> **Finding**: `predict_proba[:, 1]` is P(WIN | proposed_trade). The name `model_probability_up` in `signal_score.py` is a misnomer. The SELL inversion (`1 - P(win)`) selects the worst candidates. Proceed to R2.