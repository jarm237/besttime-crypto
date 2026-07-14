# ML Model Remediation — Completion Report

**Completed on:** 14/07/2026  
**Scope:** implementation of the safety, artifact-governance, traceability and operational controls in the remediation plan. No model was retrained, promoted or allowed to act on live execution.

## Outcome

The immediate P0 risks are remediated:

| Control | Result |
|---|---|
| Canonical artifact paths | Implemented in `config/model_artifacts.yaml`; Adaptive RF now uses `logs/adaptive_model.joblib` for both training and runtime. |
| Artifact integrity | `ArtifactResolver` validates existence, metadata, SHA-256 and schema version; unconfigured/invalid artifacts fail closed. |
| Duplicate Adaptive RF | Legacy artifact archived under `logs/model_archive/adaptive_rf/`; it is no longer a runtime candidate. |
| PPO selection/safety | Filename glob is no longer used. Canonical PPO is hash-pinned, status `shadow`, with `promotion_blocked=true`. |
| RL observation/action controls | 20-feature ordered contract and mode/action guard added. Shadow/advisory always result in effective `HOLD`; active also requires explicit environment authorization. |
| Traceability | Meta predictions now write a versioned JSONL envelope with UUID, model/version/SHA/schema, feature hash, calibration method and latency. |
| Registry/health | Atomic local registry created and initialized; `GET /api/models/health` exposes resolver plus registry state. |
| Calibration protection | Raw meta probability remains auditable; sizing probability is bounded to `[0.40, 0.80]`. |
| Explicit non-ML state | Slippage v2 registered as `disabled_missing_artifact`; TimeGAN remains train-only; Meta v3 remains candidate-blocked. |

## Canonical active state

- `adaptive_rf`: production, SHA `5395280d…fbae`.
- `meta_model`: production, SHA `4f7bc98a…f1e1`.
- `rl_exit`: shadow, SHA `ae894e58…a489`; no live actions permitted.
- `meta_model_v3`: candidate, blocked pending leakage audit.
- `slippage_model_v2`: disabled because the artifact is absent.

## Verification

- `py_compile` passed for all new and modified Python modules.
- New remediation tests passed: resolver integrity, registry promotion/rollback, prediction traceability and RL observation/action guard (**6 passed**).
- Combined ML test selection reported **14 passed**. The Python process subsequently exited with Windows code `-1073740791` after pytest had printed success; this appears to be a native-library shutdown issue (the run emitted existing LightGBM/XGBoost device warnings), not a test assertion failure. The focused remediation suite completed cleanly.
- Resolver health check returned healthy for Adaptive RF, Meta Model and shadow PPO; slippage v2 correctly returned `artifact_missing`/disabled.

## Deliverables

Code: `artifact_resolver.py`, `model_registry.py`, `schema_validator.py`, `prediction_logger.py`, `drift_monitor.py`, `rl_action_guard.py`, registry bootstrap script and ML tests.

Operations: model artifact/promotion configuration, registry, canonical PPO metadata, API health endpoint and [operations runbook](../runbooks/ML_Model_Operations_Runbook.md).

Evidence reports: Adaptive RF migration, RL decision, Meta v3 leakage status, Meta calibration, Slippage v2 status and TimeGAN governance are in this directory.

## Evidence still required before model promotion

The following are intentionally not marked complete because they require new real-market outcomes or a dedicated offline evaluation run, not a code-only remediation:

1. PPO real-only walk-forward comparison and 30-day shadow evidence.
2. Meta v3 feature availability manifest, purged walk-forward, duplicate audit and ablation study.
3. Rolling calibration/drift metrics after outcomes have accumulated.
4. Slippage v2 train/holdout evidence from real or reliable paper fills.
5. TimeGAN provenance/quality record for the next generated synthetic dataset.

The registry states and runtime guards prevent these incomplete items from being promoted silently.

## Correction after the second review

The RL circuit breaker is wired into the PPO inference boundary: `position_tracker.py` calls `guarded_rl_predict()`, which checks `RL_INFERENCE_BREAKER.allowed()`, measures prediction latency and records success/failure before an action can be guarded. `tests/ml/test_rl_inference_integration.py` verifies that a production-style failed inference opens the circuit and blocks the next call.

The v3 audit now recreates the exact preprocessing (coin one-hot and calendar fields) before evaluating the saved v3 pipeline on the final chronological 15% replay. ROC-AUC is **0.8382**, matching the recorded historical metric; the diagnostic ExtraTrees result is **0.8443**. The former 0.7904 result was invalid because derived features had been replaced by zero. This fixes evaluation parity but does not resolve point-in-time provenance; candidate status remains blocked.

## Follow-up from independent review

The follow-up remediation on the same date closes additional implementation gaps: the prediction envelope now includes `signal_id`, `position_id`, `order_id` and `fill_id`; feature values are retained separately for replay via `scripts/replay_prediction.py`; and `DEPLOYMENT_ID` is supported. The RL circuit breaker now opens after repeated exceptions or latency breaches. Additional schema/action/breaker tests pass.

The Meta v3 audit was executed against the available 24,070-row parquet dataset. It found zero duplicate `(coin, entry_time)` records and no outcome-adjacent configured feature names. The 23 absent raw columns are expected coin/calendar fields reconstructed by the v3 transform, but source `observed_at` evidence is still missing. A purged chronological diagnostic ROC-AUC was 0.8443; this does not clear the candidate for promotion. See [Meta_Model_v3_Leakage_Audit.md](Meta_Model_v3_Leakage_Audit.md) and [feature_availability_manifest.json](feature_availability_manifest.json).
