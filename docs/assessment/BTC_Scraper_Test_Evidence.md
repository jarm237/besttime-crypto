# BTC Scraper Test Evidence

Initial evidence: 2026-07-27
Latest verification: 2026-07-29

Source under test:

```text
base_commit=2e5770e1c7ab6da0c8d9556aa17e00a4eeb3edf5
code_test_lock_patch_sha256=bcbc855bd575df07484e2d75ac0fd059c8d89a13ec0a348d580e911c1334f30f
```

The patch hash covers `btc_scraper/collectors/parsebot_farside_collector.py`,
`tests/test_paths_and_macro_freshness.py`, and `requirements-lock.txt`. Record
the final commit SHA here after the remediation is committed.

## Current Baseline

The local `.venv` is usable and contains `pytest`.

```bash
.venv/bin/python -m pytest --version
```

Result:

```text
pytest 9.0.3
```

Full repository compile now passes:

```bash
.venv/bin/python -m compileall -q btc_scraper main.py main_live.py api scripts
```

Result: `PASS`.

The dependency environment is reproducible from the project lock:

```bash
python3 -m venv /tmp/btc-clean-env/venv
/tmp/btc-clean-env/venv/bin/python -m pip install -r requirements-lock.txt
/tmp/btc-clean-env/venv/bin/python -m pip check
BTC_DISABLE_TEST_RUNTIME_GUARD=1 \
  /tmp/btc-clean-env/venv/bin/python -m pytest -q
```

Result:

```text
requirements-lock.txt: 29/29 direct requirements present, 130 packages locked
fresh-venv install: PASS
pip check: PASS
pytest collection: 754 tests
full assertion suite: PASS (exit 0)
```

The guard is disabled only for the in-place clean-environment assertion run
because the already-running production process still has the pre-fix
Parse.bot module loaded. The same patched source was then tested in an isolated
source snapshot, with the guard enabled:

```bash
env -u BTC_DISABLE_TEST_RUNTIME_GUARD .venv/bin/python -m pytest -q
```

Result:

```text
pytest collection: 754 tests
full assertion suite plus runtime artifact guard: PASS (exit 0)
```

## Remediation Evidence

| Item | Previous status | Current status | Evidence |
|---|---|---|---|
| Test environment | `pytest` missing from system Python | PASS from clean venv | The regenerated Linux/Python 3.12 lock installs in a fresh venv, `pip check` passes, and the 754-test assertion suite exits 0. |
| Full repo compile | FAIL | PASS | `compileall` over `btc_scraper`, `main.py`, `main_live.py`, `api`, and `scripts` exits 0. |
| Script compile blocker | FAIL | FIXED | `scripts/backtest_eval.py` indentation at line 165 corrected. |
| Prediction contract | Incomplete | HARDENED | `tests/ml/test_data_contracts.py` validates required lineage fields and rejects missing artifact hash. |
| Execution dispatch fidelity | Mismatch | HARDENED | `tests/test_phase1_execution_pipeline_integration.py::TestSubmitLiveWithMockAdapter` proves selected LIMIT dispatches through limit adapter and TWAP live dispatch rejects fail-closed. |
| Runtime/lifecycle evidence | Not executable | PASS | Runtime evidence, paper lifecycle, linkage calibration, phase10 execution and live guard tests pass. |
| Test/runtime artifact isolation | Runtime artifacts polluted repo roots | PASS for patched code in isolated full-suite proof; deployment pending | Parse.bot ETF cache and quota state now use the owned log root. `tests/conftest.py` guards repo runtime roots, and the isolated guard-enabled 754-test suite exits 0. Restart the production process to load the fix before claiming the equivalent in-place rehearsal. |
| Restart/replay evidence | Scenario matrix missing | PASS | `tests/recovery/` covers prediction→decision, decision→reservation, reservation→submit, ambiguous submit reconciliation, partial fill replay, fill→position projection, position→outcome, outcome revision conflicts, and multi-restart idempotency. |
| Live exchange outage drills | Not verified | PASS for deterministic baseline | `tests/live_outage/` covers submit-timeout attach/defer/quarantine, rate-limit backoff and priority, REST/WS outage taxonomy, WS/REST conflict storage, child-order restart/partial-fill/quantity invariant, cancel/replace ambiguity, late fill accounting, and operator quarantine resolution. |
| Runtime ownership / process isolation | Shared repo roots | PASS for code/test baseline | `tests/test_runtime_ownership.py` covers deployment-scoped roots, runtime identity metadata, per-deployment lock conflict, stale-lock recovery audit, subprocess path isolation, guard fingerprint owner reporting, and privileged lock-bypass policy. |

## Targeted Test Runs

Contract and execution dispatch:

```bash
.venv/bin/python -m pytest \
  tests/ml/test_data_contracts.py \
  tests/ml/test_prediction_traceability.py \
  tests/test_execution_reservation_concurrency.py \
  tests/test_phase1_execution_pipeline_integration.py::TestSubmitLiveWithMockAdapter \
  tests/test_phase6_live_production.py::TestExecutionEngineLiveGuardIntegration -q
```

Result:

```text
23 passed
```

Runtime and lifecycle:

```bash
.venv/bin/python -m pytest \
  tests/ml/test_runtime_evidence_store.py \
  tests/ml/test_paper_lifecycle_e2e.py \
  tests/ml/test_runtime_linkage_calibration.py \
  tests/test_phase10_execution_pipeline.py \
  tests/test_live_execution_guard.py -q
```

Result:

```text
85 passed
```

AutoTrader regression isolation:

```bash
.venv/bin/python -m pytest tests/test_auto_trader.py -q
```

Result:

```text
21 passed
```

Runtime artifact isolation:

```bash
.venv/bin/python -m pytest \
  tests/test_paths_and_macro_freshness.py \
  tests/ml/test_runtime_evidence_store.py \
  tests/ml/test_prediction_traceability.py \
  tests/test_phase1_execution_pipeline_integration.py::TestSubmitLiveWithMockAdapter \
  tests/test_execution_reservation_concurrency.py \
  tests/test_phase5_paper_trading_validation.py -q
```

Result:

```text
29 passed
```

Restart/replay recovery matrix:

```bash
.venv/bin/python -m pytest tests/recovery -q
```

Result:

```text
13 passed
```

Live exchange outage drill matrix:

```bash
.venv/bin/python -m pytest tests/live_outage -q
```

Result:

```text
13 passed
```

Runtime/recovery regression group:

```bash
.venv/bin/python -m pytest \
  tests/ml/test_runtime_evidence_store.py \
  tests/ml/test_paper_lifecycle_e2e.py \
  tests/test_execution_reservation_concurrency.py \
  tests/test_reservation.py -q
```

Result:

```text
32 passed
```

P1.7 regression group:

```bash
.venv/bin/python -m pytest \
  tests/recovery \
  tests/ml/test_paper_lifecycle_e2e.py \
  tests/test_execution_reservation_concurrency.py -q
```

Result:

```text
28 passed
```

P1.8 runtime ownership/isolation:

```bash
.venv/bin/python -m pytest \
  tests/test_runtime_ownership.py \
  tests/test_phase4_operational_resilience.py \
  tests/test_paths_and_macro_freshness.py \
  tests/ml/test_runtime_evidence_store.py -q
```

Result:

```text
25 passed
```

P1.8 migration preflight tooling:

```bash
.venv/bin/python -m pytest tests/test_runtime_migration_preflight.py -q
.venv/bin/python scripts/runtime_migration_preflight.py --pid 115043
```

Result:

```text
2 passed
preflight report generated successfully
```

Observed preflight state:

```text
process=python3 main.py
cwd=/home/tran-huynh/Workspaces/Personal/besttime-crypto
ownership_env={}
clean_guard_full_suite_ready=false
legacy_roots_fingerprint_recorded=true
```

## Warning Summary

The full test suite still emits warnings that should be tracked as P2/P3 quality work:

- `datetime.utcnow()` deprecation in alternative data tests.
- Pandas fragmentation warnings in alternative feature generation.
- Legacy `should_trade()` deprecation warnings in AutoTrader tests.
- Adaptive RF disabled warning due `sha256_mismatch`.
- scikit-learn feature-name warnings for LightGBM test predictions.
- `tests/test_stage1_pipeline.py` returns `bool` instead of asserting.
- `np.datetime64` timezone representation warning in triple barrier tests.

## Operational Note

Pytest isolates runtime writes under `/tmp/btc-scraper-tests/<run-id>/` via `BTC_DATA_DIR`, `BTC_LOG_DIR`, `BTC_MODEL_DIR`, `BTC_STATE_DIR`, `BTC_EXECUTION_DATA_DIR`, `BTC_PREDICTION_AUDIT_DIR`, `BTC_RUNTIME_EVIDENCE_PATH`, `BTC_RESERVATION_DB_PATH`, `CATBOOST_INFO_DIR`, and `BTC_REMEDIATION_DOCS_DIR`. Runtime records created during tests are tagged with `environment`, `deployment_id`, `runtime_id`, `process_id`, `hostname`, `started_at`, `evidence_eligible`, and `paper_run_id` where the writer supports runtime metadata. P1.8 adds default deployment-scoped runtime roots under `runtime/<environment>/<deployment-id>/`, a per-deployment `state/runtime.lock`, stale-lock audit, hash-based guard reporting, and a hardened `BTC_DISABLE_RUNTIME_LOCK` policy: forbidden in `live`, critical-audited outside live, readiness-degrading, and evidence-ineligible. `scripts/runtime_migration_preflight.py` provides a read-only migration proof helper for process inventory, legacy-root fingerprinting, runtime lock/evidence/reservation snapshots, and before/after legacy-root comparison.

The 2026-07-29 in-place guard run identified the remaining legacy writers as
Parse.bot ETF cache files and `parsebot_request_usage.json`. Their code now
resolves through `build_logs_path()`, and the isolated guard-enabled full suite
passes. The existing production process was deliberately not interrupted
during remediation; it must be gracefully restarted to load this fix before
the final in-place operational rehearsal.
