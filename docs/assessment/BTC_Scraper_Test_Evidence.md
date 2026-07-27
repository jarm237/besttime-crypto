# BTC Scraper Test Evidence

Date: 2026-07-27

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

Full pytest now passes:

```bash
.venv/bin/python -m pytest
```

Result:

```text
713 passed, 118 warnings, 5 subtests passed in 187.05s (0:03:07)
```

## Remediation Evidence

| Item | Previous status | Current status | Evidence |
|---|---|---|---|
| Test environment | `pytest` missing from system Python | PASS via `.venv` | `.venv/bin/python -m pytest --version` returns `pytest 9.0.3`. |
| Full repo compile | FAIL | PASS | `compileall` over `btc_scraper`, `main.py`, `main_live.py`, `api`, and `scripts` exits 0. |
| Script compile blocker | FAIL | FIXED | `scripts/backtest_eval.py` indentation at line 165 corrected. |
| Prediction contract | Incomplete | HARDENED | `tests/ml/test_data_contracts.py` validates required lineage fields and rejects missing artifact hash. |
| Execution dispatch fidelity | Mismatch | HARDENED | `tests/test_phase1_execution_pipeline_integration.py::TestSubmitLiveWithMockAdapter` proves selected LIMIT dispatches through limit adapter and TWAP live dispatch rejects fail-closed. |
| Runtime/lifecycle evidence | Not executable | PASS | Runtime evidence, paper lifecycle, linkage calibration, phase10 execution and live guard tests pass. |
| Test/runtime artifact isolation | Runtime artifacts polluted repo roots | PASS | `tests/conftest.py` redirects writable runtime roots to `/tmp/btc-scraper-tests/<run-id>/` and fails the session if repo `data/`, `logs/`, `catboost_info/`, or `btc_scraper/logs/` are modified. Full pytest passes with the guard enabled. |

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

Pytest now isolates runtime writes under `/tmp/btc-scraper-tests/<run-id>/` via `BTC_DATA_DIR`, `BTC_LOG_DIR`, `BTC_MODEL_DIR`, `BTC_EXECUTION_DATA_DIR`, `BTC_PREDICTION_AUDIT_DIR`, `BTC_RUNTIME_EVIDENCE_PATH`, `CATBOOST_INFO_DIR`, and `BTC_REMEDIATION_DOCS_DIR`. Runtime records created during tests are tagged `environment=test`, `evidence_eligible=false`, and `paper_run_id=<run-id>` where the writer supports runtime metadata.
