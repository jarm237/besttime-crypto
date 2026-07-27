# 05 ML Runtime And Inference

Status: production-ready candidate for runtime evidence; system production remains blocked.

## Positive Findings

- `prediction_logger.append_prediction()` writes prediction and feature snapshot evidence to SQLite and mirrors to JSONL.
- Prediction envelopes now require `artifact_sha256`, `feature_snapshot_id`, `symbol`, `timeframe`, `side`, `predicted_at`, and `valid_until`.
- `RuntimeEvidenceStore` enforces prediction/snapshot identity, foreign keys, payload hashes, one final decision per prediction, and outcome revision uniqueness.
- `decision_engine` persists final decisions when a prediction exists.
- `position_tracker` appends outcome links for model-linked positions.
- Shadow validation and runtime outcome linkage modules exist.
- `tests/recovery/` now proves persisted restart/replay boundaries from prediction through outcome revision conflicts.
- P1.7 keeps outage/quarantine audit events append-only through `RuntimeEvidenceStore` and preserves runtime path isolation for test-controlled writers.
- P1.8 adds `deployment_id`, `runtime_id`, `process_id`, `hostname`, and `started_at` metadata to runtime evidence and prediction JSONL mirrors.

## Gaps

- Need production-cycle evidence that every live runtime cycle has at most one production prediction and exactly one final decision when actionable.
- Need exchange-integrated outage evidence beyond deterministic fake-adapter drills.
- Need a clean guard-enabled full-suite run after the legacy repo-root runtime process is restarted on owned roots.

## Classification

`PRODUCTION_READY_CANDIDATE` for local runtime evidence mechanics, blocked from system production until exchange-integrated live recovery and operational evidence gaps close.
