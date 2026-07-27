# 01 Core And Contracts

Status: requires remediation.

## Positive Findings

- `btc_scraper/core/paths.py` centralizes repo/data/log/script paths.
- `btc_scraper/core/utils.py` provides atomic file writes.
- `btc_scraper/core/world_state.py` defines layered market state dataclasses.
- `btc_scraper/core/event_bus.py` and `core/feature_snapshot.py` provide event/snapshot primitives.
- `btc_scraper/ml_engine/data_contracts.py` defines event contracts and stable rejection reasons.
- `btc_scraper/trading/decision_types.py` defines canonical trade action, rejection, authorization, status, breakdown, sizing and entry-decision types.

## Gaps

- Domain model ownership is split between `core`, `trading`, `execution`, and `ml_engine`.
- Prediction contract is weaker than the desired production minimum.
- Timestamps are often ISO strings, but event/observed/available/generated semantics are not enforced globally.
- Prices, quantities and fees are mostly `float`, not `Decimal`.
- Error taxonomy is local rather than universal; many broad exception handlers exist.

## Required Contract Change

`prediction_created` must require:

```text
prediction_id
model_name
model_version
artifact_sha256
feature_schema_version
feature_snapshot_id
symbol
timeframe
side
raw_probability
calibrated_probability
predicted_at
valid_until
```

## Classification

`REQUIRES_REMEDIATION`

