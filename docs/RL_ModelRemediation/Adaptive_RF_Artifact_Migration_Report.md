# Adaptive RF Artifact Migration Report

**Completed:** 2026-07-14

- Canonical production artifact: `logs/adaptive_model.joblib`.
- SHA-256: `5395280db76329ad16d79694ee2cc718fd47e22ce8c87ce18be8ac6449c5fbae`.
- Metadata: `logs/adaptive_model.metadata.json`; schema: `adaptive-rf-v2`.
- Legacy duplicate moved intact to `logs/model_archive/adaptive_rf/adaptive_model_20260628_165224.joblib`.
- Runtime loader now resolves only `adaptive_rf` from `config/model_artifacts.yaml`; it does not inspect `btc_scraper/logs` or fall back to any unconfigured artifact.

Verification: resolver hash checks pass and `tests/ml/test_artifact_resolver.py` covers healthy and mismatched artifacts.
