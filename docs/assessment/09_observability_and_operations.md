# 09 Observability And Operations

Status: requires remediation.

## Positive Findings

- Prediction audit JSONL files exist under `logs/prediction_audit`.
- Runtime evidence SQLite store has health checks and hash verification.
- Execution logs and fills are split into `logs/execution` and `data/execution/fills`.
- Pytest runtime writes are now isolated under `/tmp/btc-scraper-tests/<run-id>/` and guarded against repo runtime-root mutation.
- API exposes readiness/live/dependency/metrics-style endpoints.
- Kill switch, live audit log, live monitor, phase 5 report generator and operational health modules exist.

## Gaps

- Production/paper data-log artifacts remain broad and need lifecycle taxonomy by function and environment.
- Need rotation/retention policy for `data/raw_alternative`, prediction audit and model artifacts.
- Need secret scanning for logs and configs.
- Need correlation IDs consistently visible across prediction, decision, reservation, order, fill, position and outcome.
- Need dashboards for orphan evidence, drift, fallback, stale data and system degradation.

## Classification

`REQUIRES_REMEDIATION`
