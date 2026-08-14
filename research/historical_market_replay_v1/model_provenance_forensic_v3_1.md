# HMR-V1.2 Model Provenance Forensic

Artifact: `meta_model v3.1`

Artifact SHA-256: `4f7bc98a6c18d04d7853a180c4f68763298580128a206bf159f4d16c956cf1e1`

Replay start: `2025-01-01T00:00:00Z`

## Decision

```text
CLASSIFICATION             UNKNOWN
MODEL_TEMPORAL_VALIDITY    FAIL
HMR-V1.3 EFFICACY          BLOCKED
HMR-V1.4 3-MONTH REPLAY    BLOCKED
```

The bounded forensic is closed. No authoritative training run manifest binds the exact artifact to a dataset hash, training cutoff, calibration cutoff, and training run ID.

## Evidence

| Field | Result |
| --- | --- |
| model_version | `v3.1` |
| artifact_sha256 | `4f7bc98a6c18d04d7853a180c4f68763298580128a206bf159f4d16c956cf1e1` |
| training_run_id | `UNKNOWN` |
| authoritative training_data_max_timestamp | `UNKNOWN` |
| authoritative calibration_data_max_timestamp | `UNKNOWN` |
| artifact-introducing commit | `f6d49d5d3ad598c48c78dc324c50aca95f7405b8` |

Repository evidence strongly indicates that the artifact is post-window:

| Candidate source boundary | Timestamp |
| --- | --- |
| training entry max | `2025-12-21T10:00:00Z` |
| training label available max (`exit_time`) | `2025-12-23T05:30:00Z` |
| calibration fit available max | `2026-03-18T17:00:00Z` |
| calibration method-selection available max | `2026-06-15T10:45:00Z` |

The candidate input has exactly `24,070` rows, matching the artifact's embedded `n_samples`; the training code hardcodes that input path, and the artifact plus metadata changed in the same Git commit. This remains non-authoritative because the artifact contains neither a dataset hash nor a training run ID.

## Stop Rule

The following layers were checked once: training/dataset manifests, model registry, training logs, calibration provenance, embedded artifact metadata, and Git history. The search stops here.

## Next Action

Create a research-only historical artifact with both training and calibration ending no later than `2024-12-31T23:59:59Z`, persist the complete provenance contract, then rerun the unchanged seven-day fixture. The current `5 trades / 20% WR / -15.77 net PnL` remains diagnostic only.
