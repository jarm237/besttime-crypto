# 05 ML Runtime And Inference

Status: paper-ready with baseline recovery evidence.

## Positive Findings

- `prediction_logger.append_prediction()` writes prediction and feature snapshot evidence to SQLite and mirrors to JSONL.
- Prediction envelopes now require `artifact_sha256`, `feature_snapshot_id`, `symbol`, `timeframe`, `side`, `predicted_at`, and `valid_until`.
- `RuntimeEvidenceStore` enforces prediction/snapshot identity, foreign keys, payload hashes, one final decision per prediction, and outcome revision uniqueness.
- `decision_engine` persists final decisions when a prediction exists.
- `position_tracker` appends outcome links for model-linked positions.
- Shadow validation and runtime outcome linkage modules exist.
- `tests/recovery/` now proves persisted restart/replay boundaries from prediction through outcome revision conflicts.

## Gaps

- Need production-cycle evidence that every live runtime cycle has at most one production prediction and exactly one final decision when actionable.
- Need live exchange outage drill evidence beyond the local persisted recovery matrix.

## Classification

`PAPER_READY`, blocked from production until live exchange recovery and operational evidence gaps close.
