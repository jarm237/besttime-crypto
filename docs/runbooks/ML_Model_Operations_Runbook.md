# ML Model Operations Runbook

## Health

Call `GET /api/models/health`. A model is usable only when its configured artifact is present, hash/schema validation is healthy and registry status permits its mode.

## Immediate containment

Set `RL_EXIT_MODE=disabled` to disable RL inference, or `RL_EXIT_MODE=shadow` to preserve audit-only recommendations. Keep `RL_EXIT_ALLOW_LIVE_ACTION=false` unless a recorded promotion authorizes active mode.

For an artifact hash mismatch, do not replace the file in place. Mark the registry record unhealthy, restore the previous archived artifact through a new registry promotion/rollback record, and retain the incident evidence.

## Rollback

Use `ModelRegistry.rollback(model_name, version)` only for an existing registered immutable version. Verify `/api/models/health`, then replay a feature snapshot and retain the promotion/rollback record.

## Drift or calibration alert

For PSI >0.20 or ECE >0.10, stop sizing changes from the affected model, inspect missing features and feature snapshots, and run a real-only recalibration evaluation. Do not promote a calibrator solely on in-sample metrics.

## Incident evidence

Preserve prediction ID, feature hash/snapshot, artifact SHA, registry record, configuration, latency, signal/order/fill IDs and outcome. Prediction metadata is retained for at least 180 days and snapshots for 90 days.

## Inference timeout or circuit breaker

The RL breaker opens after three failed or over-SLA (>150 ms by default) inferences and holds the model disabled for five minutes. Keep the effective action at HOLD, capture the exception/latency, inspect CPU/GPU health and only restart the process after the artifact hash and observation contract have been verified.

## Disk or registry write failure

Treat a failed audit/registry write as an operational incident. Do not promote a model, overwrite an artifact or delete a prior record. Restore writable storage, validate the JSON registry, then perform a dry-run promotion against a copied artifact.

## Missing metadata or schema mismatch

The resolver fails closed. Leave the model disabled, compare SHA/schema against the registry record, create new metadata for the immutable artifact if appropriate, and register a new version rather than editing a production record.

## Artifact corruption

Quarantine the corrupt file, select a previously registered version, use rollback, verify `/api/models/health`, and run replay against a retained feature snapshot. Never use an arbitrary file with a similar model filename.

## Synthetic-data incident

If synthetic records appear in a production test/evaluation set, invalidate that evaluation, identify the dataset ID and generator provenance, rebuild a real-only test split, and keep the candidate blocked.
