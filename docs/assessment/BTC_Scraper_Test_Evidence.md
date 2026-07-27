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
712 passed, 121 warnings, 5 subtests passed in 262.06s (0:04:22)
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

Some tests write runtime artifacts under `data/execution`, `logs/execution`, `btc_scraper/logs`, model/training cache folders, and data-feature-store paths. This reinforces the data lifecycle remediation item: test/debug/paper/live runtime state needs stronger path isolation and environment tagging.
