# 09 Observability And Operations

Status: requires remediation.

## Positive Findings

- Prediction audit JSONL files exist under `logs/prediction_audit`.
- Runtime evidence SQLite store has health checks and hash verification.
- Execution logs and fills are split into `logs/execution` and `data/execution/fills`.
- Pytest runtime writes are now isolated under `/tmp/btc-scraper-tests/<run-id>/` and guarded against repo runtime-root mutation.
- Runtime migration preflight tooling can inventory a running process and fingerprint legacy roots before/after migration.
- API exposes readiness/live/dependency/metrics-style endpoints.
- Kill switch, live audit log, live monitor, phase 5 report generator and operational health modules exist.

## Runtime Migration Proof

Use the read-only helper before stopping a legacy runtime process:

```bash
.venv/bin/python scripts/runtime_migration_preflight.py \
  --pid 115043 \
  --output /tmp/btc-runtime-preflight-before.json
```

After graceful shutdown and restart on an owned runtime root, run:

```bash
.venv/bin/python scripts/runtime_migration_preflight.py \
  --pid <new-pid> \
  --compare-before /tmp/btc-runtime-preflight-before.json \
  --expect-legacy-unchanged \
  --output /tmp/btc-runtime-preflight-after.json
```

Acceptance for closing P1.8 clean proof:

```text
legacy_roots_unchanged=true
process.has_owned_runtime_env=true
runtime_lock.exists=true
runtime_lock.owner_pid_alive=true
runtime_evidence.health.status=healthy or store absent before first eligible write
reservations.active_count reviewed
quarantine.unresolved_count=0 or explicitly accepted by operator
```

## Gaps

- Production/paper data-log artifacts remain broad and need lifecycle taxonomy by function and environment.
- Need rotation/retention policy for `data/raw_alternative`, prediction audit and model artifacts.
- Need secret scanning for logs and configs.
- Need correlation IDs consistently visible across prediction, decision, reservation, order, fill, position and outcome.
- Need dashboards for orphan evidence, drift, fallback, stale data and system degradation.

## Classification

`REQUIRES_REMEDIATION`
