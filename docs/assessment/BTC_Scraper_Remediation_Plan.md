# BTC Scraper Remediation Plan

Initial assessment: 2026-07-27
Evidence updated: 2026-07-29

## P0 - Safety / Correctness Blockers

No confirmed live-trading P0 was proven in this static pass because live is already fail-closed through `main_live.py` and `LiveExecutionGuard`. P0 status should be re-evaluated after the full test suite and an E2E paper replay can run.

Immediate P0 acceptance gate for future live work:

- No live order can bypass `ExecutionEngine.submit_live()`.
- No entry order can pass without Phase 5 gate, live flag, kill switch, hard risk, system health, execution risk, reservation, prediction lineage, and idempotency key.
- Corrupt evidence store, unknown model artifact, or schema mismatch blocks new entries.

## P1 - Production Blockers

1. Restore test environment.
   - Status: `DONE`.
   - Acceptance: `python3 -m pytest` runs in a clean venv from `requirements-lock.txt`.
   - Evidence: `requirements-lock.txt` contains all 29 direct requirements and 130 locked packages; a fresh Python 3.12 venv installs the lock, passes `pip check`, collects 754 tests, and completes the full assertion suite with exit 0.

2. Fix script compile blocker.
   - Status: `DONE`.
   - File: `scripts/backtest_eval.py`.
   - Acceptance: full `compileall` over `btc_scraper`, `main.py`, `main_live.py`, `api`, and `scripts` passes.
   - Evidence: `.venv/bin/python -m compileall -q btc_scraper main.py main_live.py api scripts` exits 0.

3. Harden prediction contract.
   - Status: `DONE`.
   - Add required fields: `artifact_sha256`, `feature_snapshot_id`, `symbol`, `timeframe`, `side`, `predicted_at`, `valid_until`.
   - Reject null artifact hashes for production predictions.
   - Acceptance: contract tests fail on missing fields and pass on complete envelope.
   - Evidence: `tests/ml/test_data_contracts.py` and `tests/ml/test_prediction_traceability.py` pass.

4. Fix live order type dispatch.
   - Status: `DONE`.
   - Ensure selected order type is actually submitted as MARKET, LIMIT, or TWAP.
   - Acceptance: E2E tests prove selected order type equals submitted order type; TWAP is either fully dispatched or disabled.
   - Evidence: selected LIMIT dispatches through limit adapter; selected TWAP rejects fail-closed until live TWAP child-order recovery has E2E coverage.

5. Isolate test/runtime artifacts.
   - Status: `DONE` for code and isolated test proof; production process rollout/rehearsal remains pending.
   - Writable runtime roots are redirected by pytest to `/tmp/btc-scraper-tests/<run-id>/`.
   - Required test metadata is attached to runtime evidence where supported: `environment=test`, `evidence_eligible=false`, `paper_run_id=<run-id>`.
   - Acceptance: full pytest passes with an artifact guard that fails if repo runtime roots are modified.
   - Evidence: Parse.bot ETF cache and request quota state now resolve through the owned log root, with regression coverage in `tests/test_paths_and_macro_freshness.py`. A source snapshot isolated from the running production process collects 754 tests and completes the full suite with the guard enabled and exit 0. The current production process still has the pre-fix module loaded and must be restarted before the same in-place proof is claimed.

6. Prove restart/replay idempotency.
   - Status: `DONE` for baseline recovery matrix.
   - Acceptance: scenarios after prediction, decision, reservation, fill, and close are replayed without duplicate orders or conflicting outcomes.
   - Evidence: `tests/recovery/` passes with 13 tests covering persisted restart/replay boundaries and multi-restart idempotency.

7. Prove live exchange outage behavior.
   - Status: `DONE` for deterministic adapter baseline; live exchange/testnet drill still required before production.
   - Acceptance: submit timeout, rate limit, REST/WS outage, child-order replay, cancel/replace ambiguity, WS/REST disagreement, and operator quarantine are covered without duplicate logical orders or silent state mutation.
   - Evidence: `tests/live_outage/` passes with 13 tests and the current 754-test full assertion suite completes with exit 0.

8. Add runtime ownership and process isolation.
   - Status: `DONE` for code/test baseline and isolated full-suite guard proof; in-place production rehearsal remains pending.
   - Acceptance: every runtime has environment/deployment/runtime identity, default roots are deployment-scoped, reservation/evidence stores do not share SQLite by default, same-deployment second process is refused, stale locks are audited, lock bypass is forbidden in live and critical-degraded elsewhere, and the runtime guard reports hashes plus suspected owner metadata.
   - Evidence: `tests/test_runtime_ownership.py` passes; the current 754-test suite completes with exit 0 in a fresh dependency environment and with the artifact guard enabled in an isolated source snapshot.

## P2 - Quality / Observability

1. Add failure taxonomy.
   - Classify broad fallback handlers as continue/degrade/fallback/block/quarantine/shutdown.

2. Add point-in-time feature tests.
   - Prove rolling/MTF/alternative/regime features at time T use only data available at or before T.

3. Add score semantics matrix.
   - Cover BUY/SELL symmetry, raw score vs display score vs strength, and threshold behavior.

4. Add provider replay fixtures.
   - Each collector should have successful, stale, missing, rate-limited, malformed, and disabled fixtures.

5. Improve dashboard health.
   - Show model version, artifact hash, fallback, calibration drift, prediction failures, open risk, execution status, and stale markers.

## P3 - Maintainability

1. Split large rule surfaces.
   - Gradually extract `analysis/core.py` sections into smaller strategy/signal modules.

2. Consolidate training scripts.
   - Define canonical training pipeline and mark experiments as research.

3. Normalize path ownership.
   - Deprecate package-local runtime state under `btc_scraper/logs` and `btc_scraper/data` unless intentionally scoped.

4. Document supported entry points.
   - Every `__main__` module should be labeled supported, research, migration, or deprecated.

## Execution Order

```text
1. Feature point-in-time fixtures
2. Collector fixtures and stale handling
3. Failure taxonomy for broad fallback paths
4. Broader data/log lifecycle taxonomy beyond runtime ownership
5. Runtime migration preflight before/after proof with `scripts/runtime_migration_preflight.py`
6. Restart the running production process to load the Parse.bot owned-path fix, then repeat the in-place guard-enabled full-suite run
7. Real exchange/testnet outage drill and operator runbook rehearsal
8. UI/Telegram operational hardening
```
