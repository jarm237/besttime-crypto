# Slippage Model v2 Validation Report

**State:** `disabled_missing_artifact`.

No configured `logs/slippage_model_v2.joblib` exists. The registry records the state explicitly and the production resolver reports it unhealthy; therefore the LightGBM v2 model is not described as active. Runtime continues with the documented rule-based v1 predictor.

Before activation, real or reliable paper fills must demonstrate better holdout and walk-forward MAE/P95/bias than v1, with identical 12-feature train/inference schema and explicit fallback telemetry.
