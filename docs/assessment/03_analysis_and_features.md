# 03 Analysis And Features

Status: requires remediation.

## Positive Findings

- `analysis/core.py` is the main signal detector.
- `ml_engine/signal_score.py` has explicit score semantics where 0 is strong SELL, 50 is neutral, and 100 is strong BUY.
- `feature_engineering` contains feature store, validators, fractional differencing, labels, triple barrier, alternative, cross-sectional, causal, and regime feature modules.
- Tests exist for feature store, validator, alternative features, dataset builder, label quality, triple barrier, and analysis.

## Gaps

- `analysis/core.py` remains a large behavioral surface and should be split gradually.
- Need a BUY/SELL score matrix to prove raw score, display score, confidence, and strength are never confused.
- Need point-in-time feature fixtures for rolling windows, MTF joins, alternative data, and regime features.
- Need training/runtime feature parity tests to run in the current environment.

## Classification

`REQUIRES_REMEDIATION`

