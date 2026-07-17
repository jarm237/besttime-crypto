# ML Runtime Outcome Linkage & Calibration Implementation Report

**Date:** 2026-07-16  
**Plan implemented:** `docs/ML_RUNTIME_OUTCOME_LINKAGE_CALIBRATION_PLAN_v1_1.md`  
**Status:** implementation foundation passed; producer integration and runtime evidence remain pending.

```text
Governance framework: COMPLETE
Code foundation: PASSED
Full regression: PASSED
Lifecycle framework: IMPLEMENTED
Operational health foundation: IMPLEMENTED
Producer migration: STARTED (covered paper path includes reservation/order/fill)
Paper lifecycle happy path: PASSED
Reservation continuity: PASSED
Timeout/retry recovery: PASSED
Crash-after-fill recovery: PASSED
Partial-fill cancellation: PASSED
Duplicate idempotency replay: PASSED
Ledger-level fill-before-order: PASSED
Calibration amendment active-view: PASSED
Linker amendment/quarantine evidence: PASSED
Full-chain producer replay on covered paper path: PASSED
Runtime mixed-metadata quarantine proof: PASSED
Operational position restart continuity: PASSED on covered paper path
Recovery/out-of-order evidence: PASSED on covered paper path
Lifecycle recovery E2E with runtime data: COVERED PAPER PATH PASSED
Operational Gate A evidence tooling: IMPLEMENTED
Operational Gate A evidence from paper runtime: PENDING
Trade provenance taxonomy: IMPLEMENTED
Manual/system paper distinction: IMPLEMENTED
WLD manual signal correction: APPLIED
Shadow evidence window: NOT STARTED
Runtime calibration readiness: BLOCKED
Meta promotion readiness: BLOCKED
```

Shadow window governance status:

```text
Shadow window start governance: PASSED
Gate A enforcement: PASSED
Lifecycle E2E prerequisite: IMPLEMENTED
Persistence and reset audit: PASSED
Shadow window evidence collection: NOT STARTED
```

## Summary

Implemented the concrete runtime linkage, calibration, governance, and traceability primitives required by the v1.1 remediation plan. This should be read as:

> Runtime linkage and calibration framework implemented; producer adoption and operational validation pending.

The implementation does not retrain or auto-promote Meta Model artifacts. Runtime calibration and promotion remain blocked until linked runtime samples provide sufficient evidence.

Operational safety flags remain:

```text
META_RECALIBRATION_AUTO_PROMOTE=false
LIVE_TRADING_ENABLED=false
PHASE5_LIVE_READINESS_GATE=false
```

Tail sizing clamp remains enabled until tail buckets have enough linked runtime samples across evaluation windows.

Operational update on 2026-07-17:
- normalized order provenance now distinguishes `system + paper_runner` from `user + telegram/ui/cli`;
- Telegram `/positions` and CLI position listing expose a human-readable source label;
- legacy backfill support can populate the same provenance fields for historical records;
- duplicate open WLD was removed and the prior WLD closed trade was corrected to a manual Telegram trade following a system signal;
- this operator correction does not start Gate A or shadow evidence collection.

## WS0 / PR0 - Data Contract Registry

Implemented `btc_scraper/ml_engine/data_contracts.py`.

Delivered:
- Versioned `DataContractRegistry`.
- Stable reject reason codes:
  - `unknown_event_type`
  - `schema_version_mismatch`
  - `missing_required_field`
  - `empty_business_key`
  - `empty_idempotency_scope`
- Fail-closed event validation.
- Default runtime contracts for:
  - `prediction_created`
  - `entry_decision_created`
  - `reservation_created`
  - `order_submitted`
  - `fill_recorded`
  - `position_closed`
  - `calibration_sample_created`
- Unit coverage in `tests/ml/test_data_contracts.py`.

Prediction audit logging now stamps and validates `prediction_created` events before append in `btc_scraper/ml_engine/prediction_logger.py`.

## WS1 - Stable IDs & Lifecycle Contract

Implemented `btc_scraper/ml_engine/trade_lifecycle.py`.

Delivered:
- Canonical `TradeLifecycleContext`.
- Schema version `trade-lifecycle-v1`.
- Stable ID fields:
  - `prediction_id`
  - `signal_id`
  - `entry_decision_id`
  - `reservation_id`
  - `idempotency_key`
  - `client_order_id`
  - `exchange_order_id`
  - `fill_id`
  - `position_id`
  - `outcome_id`
- `lifecycle_hash` metadata for traceability.
- Required-field validation for rollout migration.

Execution records now include lifecycle ID fields in `btc_scraper/execution/fill_tracker.py` while staying backward-compatible with existing callers.

## WS2 - Prediction, Signal, Decision Linkage

Delivered:
- `prediction_created` event contract requires stable prediction metadata.
- `entry_decision_created` event contract requires `prediction_id`, `signal_id`, and `entry_decision_id`.
- Runtime linker rejects missing stable linkage instead of timestamp joining.

Current integration state:
- Existing prediction audit writes `prediction_id` and optional `signal_id`.
- Full producer-side migration of every decision caller is now unblocked by the contract and lifecycle modules.

## WS3 - Execution, Fill, Position Linkage

Delivered:
- `order_submitted` and `fill_recorded` event contracts.
- Execution records extended with lifecycle IDs and order IDs.
- Runtime linker can consume `position_id`, `signal_id`, or `prediction_id` from outcome/fill records.

Current integration state:
- The low-level fill record structure can now carry full lifecycle metadata.
- Exchange-specific producers still need field population during live/paper execution rollout.

## WS4 - Closed Outcome Recorder

Delivered:
- `position_closed` contract requires `position_id`, `closed_at`, `net_pnl_pct`, and `outcome_revision`.
- Linker excludes `synthetic`, `debug`, `test`, and `replay` sources from runtime evidence.
- Duplicate `(position_id, outcome_revision)` outcomes are counted and excluded.
- Amendment-ready revision semantics are represented through `outcome_revision`.

## WS5 - Runtime Outcome Linker

Implemented `btc_scraper/ml_engine/runtime_outcome_linker.py`.

Delivered:
- Stable-ID join priority:
  1. `prediction_id`
  2. `signal_id`
  3. `position_id`
- No timestamp-nearest production join.
- Immutable `CalibrationSample`.
- Deterministic unique sample key from `prediction_id + position_id + outcome_revision`.
- Append-only JSONL writer for calibration sample events.
- Orphan taxonomy support:
  - `prediction_without_signal`
  - `signal_without_decision`
  - `eligible_decision_without_reservation`
  - `reservation_without_order`
  - `submitted_order_without_fill`
  - `fill_without_position`
  - `closed_position_without_outcome`
  - `outcome_without_prediction`
  - `prediction_without_outcome`
- Orphan action fields:
  - `first_seen`
  - `last_seen`
  - `retry_count`
  - `status`
  - `severity`
  - `owner`
- Health states:
  - `HEALTHY`
  - `DEGRADED_LINKAGE`
  - `INSUFFICIENT_OUTCOMES`
  - `SCHEMA_MISMATCH`
- Runtime metrics:
  - `actionable_prediction_to_trade_rate`
  - `closed_trade_prediction_to_outcome_rate`
  - `prediction_to_outcome_link_rate` as backward-compatible alias for `closed_trade_prediction_to_outcome_rate`
  - orphan counts
  - orphan counts by category
  - duplicate outcome count
  - quarantined sample count
  - mixed artifact/schema count
  - excluded debug/synthetic counts

Amendment and quarantine behavior:
- duplicate `(position_id, outcome_revision)` outcomes are counted separately from amendments;
- higher `outcome_revision` supersedes earlier revisions for calibration sample creation;
- runtime calibration reports materialize only the latest `(prediction_id, position_id)` revision, so revision 1 remains auditable without staying active after revision 2;
- model version, artifact hash, or feature schema mismatches are quarantined and excluded from usable calibration samples;
- runtime mixed-metadata quarantine is covered separately for `model_version_mismatch`, `artifact_hash_mismatch`, and `feature_schema_mismatch`;
- outcome-before-prediction cases remain pending with `waiting_for_prediction` and can resolve when the prediction audit row appears.

Denominator clarification:
- `closed_trade_prediction_to_outcome_rate` uses closed traded predictions as the denominator.
- Rejected predictions and predictions that never opened a position do not dilute outcome-linkage coverage.
- `actionable_prediction_to_trade_rate` is tracked separately to measure conversion from actionable prediction to trade.

Calibration sample JSONL shadow writing now uses:
- single-file lock where supported by the OS;
- rebuilt dedup index on append;
- business-level uniqueness by `prediction_id + position_id + outcome_revision`;
- corrupt trailing-line recovery by skipping invalid JSONL rows.

## WS6 - Runtime Calibration Pipeline

Implemented `btc_scraper/ml_engine/runtime_calibration.py`.

Delivered:
- Rolling windows: 7, 14, 30, 90 days.
- Metrics:
  - Brier score
  - ROC-AUC
  - PR-AUC
  - ECE
  - maximum calibration error
  - reliability buckets
  - win rate / net PnL by bucket
  - symbol/regime/side breakdowns
  - prediction distribution summary
- Bucket evidence states:
  - `<30`: `insufficient`
  - `30-99`: `provisional`
  - `>=100`: `usable`
- Report writer for `logs/runtime_calibration/runtime_calibration_YYYY-MM-DD.json`.

## WS7 - Recalibration Promotion Governance

Implemented `btc_scraper/ml_engine/recalibration_governance.py`.

Delivered:
- `RecalibrationCandidate` enforces:
  - `status = candidate`
  - `auto_promote = false`
- Direct `candidate -> production` transition is rejected.
- Shadow evaluation requires paired production/candidate samples.
- Gates implemented:
  - Brier delta improvement
  - bootstrap 95% CI upper bound <= `+0.002`
  - ECE non-regression
  - ROC-AUC non-regression
  - tail calibration regression check for usable buckets
- Inconclusive or insufficient evidence returns:
  - `status = insufficient_evidence`
  - `action = remain_shadow`

## WS8 - Adaptive RF Traceability

Updated `btc_scraper/ml_engine/adaptive_scoring.py`.

Delivered:
- Adaptive outcome records now preserve:
  - `prediction_id`
  - `signal_id`
  - `position_id`
  - `outcome_id`
  - `model_version`
  - `artifact_sha256`
  - `feature_schema_version`
  - `dataset_manifest_hash`
- Records with full stable IDs are marked `runtime_linked`.
- Legacy records without full stable IDs are marked `offline_only`.
- Only `runtime_linked` records are marked `runtime_calibration_eligible`.

## WS9 - Observability & Health

Delivered through `LinkageReport`, `lifecycle_observability.py`, `runtime_health.py`, `shadow_evidence_window.py`, and runtime calibration reports:
- Linkage coverage.
- Producer-level lifecycle ID coverage.
- Producer/order provenance coverage:
  - `order_creator`;
  - `order_channel`;
  - `is_system_order`;
  - `is_user_order`;
  - `is_system_paper_order`;
  - `is_user_telegram_order`;
  - `is_user_ui_order`.
- Orphan counts.
- Orphan owner/actionability.
- Duplicate outcome count.
- Excluded debug/synthetic counts.
- Calibration sample count.
- Calibration evidence/freshness state.
- Shadow evidence window state:
  - `shadow_window_started_at`;
  - `shadow_window_valid`;
  - `shadow_window_reset_reason`.
  - `last_evaluated_at`;
  - `consecutive_valid_days`;
  - `linker_schema_version`;
  - `calibration_schema_version`;
  - `producer_contract_version`.
- Operational health actions:
  - freeze promotion;
  - keep sizing clamp;
  - mark calibration degraded;
  - mark calibration stale;
  - freeze calibration;
  - quarantine samples.

Producer coverage is reported separately for:
- Prediction
- Entry decision
- Reservation
- Submitted order
- Fill
- Open position
- Closed outcome

Operational alert inputs:
- `critical_orphan > 0`
- `duplicate_outcome > 0`
- `mixed_artifact_schema > 0`
- `closed_trade_prediction_to_outcome_rate < 90%`
- stale calibration report
- producer coverage below floor

These conditions do not stop Meta scoring runtime by themselves. They block promotion, keep the sizing clamp, and mark calibration degraded/stale.

Shadow evidence window resets if any of the following occurs:
- producer coverage drops below Gate A;
- closed-position outcome coverage drops below Gate A;
- duplicate outcome appears;
- mixed artifact/schema sample appears;
- unresolved critical orphan appears;
- linker logic/schema changes;
- calibration data is backfilled or changed incompatibly.

Shadow evidence window state is persisted so process restarts continue the same valid window when schema versions remain compatible. Reset history is append-only and records:

```json
{
  "reset_event_id": "...",
  "reset_at": "...",
  "previous_started_at": "...",
  "previous_valid_days": 4,
  "reason": "duplicate_outcome",
  "hard_reset": true,
  "linkage_rate": 0.94,
  "producer_coverage": {},
  "outcome_coverage": 0.98,
  "duplicate_outcomes": 1,
  "critical_orphans": 0,
  "linker_schema_version": "...",
  "calibration_schema_version": "...",
  "producer_contract_version": "...",
  "metrics_snapshot": {},
  "schema_versions": {}
}
```

Shadow persistence invariants:
- `last_evaluated_at >= shadow_window_started_at`;
- `reset_at >= previous_started_at`;
- `consecutive_valid_days >= 0`;
- timestamp rollback is rejected;
- `consecutive_valid_days` is derived from elapsed real time and floored, not incremented per evaluation;
- state JSON is written through temporary file, flush, fsync, and atomic rename;
- reset history append is file-locked, flushed, fsynced, and deduplicated by deterministic `reset_event_id`;
- schema version changes hard-reset the active window before evidence can continue.

Hard reset reasons:
- duplicate outcome;
- mixed artifact/schema;
- linker/schema logic change;
- incompatible backfill;
- critical data integrity violation.

Temporary invalidation/pause may be introduced later for transient producer coverage drops, stale reports, pending grace-period events, or temporary storage/collector outages. For the initial rollout, any Gate A violation resets the window conservatively.

## WS10 - Naming & Documentation

Delivered:
- Runtime modules use the plan’s naming:
  - Meta Prediction Audit
  - Meta Outcome Linkage
  - Runtime Calibration
  - Periodic Recalibration Candidate
  - RL Exit Shadow
- This report separates runtime calibration from offline continuous learning.

## Verification

Commands executed:

```bash
.venv/bin/pytest tests/ml/test_data_contracts.py tests/ml/test_prediction_traceability.py tests/ml/test_runtime_linkage_calibration.py -q
```

Result:

```text
14 passed
```

```bash
.venv/bin/pytest tests/test_ml_models.py -q
```

Result:

```text
6 passed
```

Additional focused command after observability hardening:

```bash
.venv/bin/pytest tests/ml/test_data_contracts.py tests/ml/test_prediction_traceability.py tests/ml/test_runtime_linkage_calibration.py tests/test_ml_models.py -q
```

Result:

```text
22 passed
```

Additional focused command after denominator clarification:

```bash
.venv/bin/pytest tests/ml/test_runtime_linkage_calibration.py -q
```

Result:

```text
passed
```

Additional focused command after operational health gates:

```bash
.venv/bin/pytest tests/ml/test_runtime_linkage_calibration.py -q
```

Result:

```text
passed
```

Additional focused command after shadow evidence window state:

```bash
.venv/bin/pytest tests/ml/test_runtime_linkage_calibration.py -q
```

Result:

```text
passed
```

Additional focused command after shadow persistence/reset history:

```bash
.venv/bin/pytest tests/ml/test_runtime_linkage_calibration.py -q
```

Result:

```text
passed
```

Additional focused command after shadow persistence invariants:

```bash
.venv/bin/pytest tests/ml/test_runtime_linkage_calibration.py -q
```

Result:

```text
passed
```

Additional focused command after GateSnapshot start API:

```bash
.venv/bin/pytest tests/ml/test_runtime_linkage_calibration.py -q
```

Result:

```text
passed
```

Additional focused command after GateSnapshot stale/idempotency guard:

```bash
.venv/bin/pytest tests/ml/test_runtime_linkage_calibration.py -q
```

Result:

```text
passed
```

Full repository test command:

```bash
.venv/bin/pytest tests/ -q --tb=short
```

Result:

```text
passed
```

Observed warnings were non-blocking and pre-existing in broad areas such as alternative feature DataFrame fragmentation, legacy `should_trade()` deprecations, sklearn feature-name warnings, and pytest return-value warning in `test_stage1_pipeline`.

Compile check:

```bash
.venv/bin/python -m compileall -q \
  btc_scraper/ml_engine/data_contracts.py \
  btc_scraper/ml_engine/trade_lifecycle.py \
  btc_scraper/ml_engine/runtime_outcome_linker.py \
  btc_scraper/ml_engine/runtime_calibration.py \
  btc_scraper/ml_engine/recalibration_governance.py \
  btc_scraper/ml_engine/prediction_logger.py \
  btc_scraper/execution/fill_tracker.py \
  btc_scraper/ml_engine/adaptive_scoring.py
```

Result: passed.

## Remaining Rollout Work

The remediation foundation is implemented, but production maturity still requires producer rollout:

1. Populate lifecycle IDs in every live/paper decision, reservation, order, fill, position, and outcome producer.
2. Run the linker in shadow until linkage reaches at least 90%.
3. Generate daily runtime calibration reports from linked samples.
4. Keep Meta Model promotion frozen until:
   - linked runtime coverage meets the plan gates,
   - duplicate outcomes are zero,
   - mixed schema/artifact samples are zero,
   - synthetic/debug promotion samples are zero,
   - candidate passes shadow governance.

Highest-priority next work:
1. Complete producer migration across prediction -> decision -> reservation -> order -> fill -> position -> outcome.
2. Add lifecycle E2E/recovery validation for outcome-before-prediction-flush, fill-before-order, restart, duplicate replay, partial-fill cancel, amendment outcome, mixed artifact/schema quarantine, and linker rerun idempotency.
3. Wire operational health actions to Telegram/alerting, health endpoint, dashboard, promotion scheduler, and runbook incident flow.
4. Start the 7-day shadow evidence window only after producer ID coverage >= 99%, closed outcome coverage >= 98%, duplicate outcomes = 0, mixed schema/artifact = 0, and critical orphan = 0.

Do not retrain Meta Model at this phase. Retraining would not solve producer adoption or outcome linkage, and it would add model version/artifact/schema combinations before runtime evidence is clean enough.

Shadow governance is feature-complete for rollout framework purposes. Remaining blockers are producer adoption, lifecycle recovery E2E, operational alert wiring, and Gate A runtime verification.

Shadow window start is API-gated through `GateSnapshot` and `ShadowEvidenceWindowStore.start(...)`. The store refuses to start if Gate A or lifecycle E2E/recovery evidence is missing:

```python
result = window_store.start(gate_snapshot)
assert not result.started
assert result.reason == "producer_coverage_below_gate_a"
```

This prevents manual shadow-window starts before producer adoption and recovery evidence are proven.

`GateSnapshot` is immutable and includes:

```python
producer_coverage: dict[str, float]
closed_outcome_coverage: float
duplicate_outcomes: int
mixed_artifact_schema_samples: int
unresolved_critical_orphans: int
lifecycle_e2e_passed: bool
recovery_tests_passed: bool
evaluated_at: datetime
```

Start refusal reason precedence:

```text
duplicate_outcome
mixed_artifact_schema
critical_orphan_unresolved
lifecycle_e2e_not_passed
recovery_tests_not_passed
producer_coverage_below_gate_a
outcome_coverage_below_gate_a
gate_snapshot_stale
```

Gate snapshots older than 15 minutes are refused with `gate_snapshot_stale`. Calling `start()` repeatedly with the same still-valid snapshot preserves the original `shadow_window_started_at` and does not reset evidence time.

At start, the persisted window records:

```json
{
  "start_gate_snapshot_hash": "...",
  "start_gate_evaluated_at": "...",
  "start_gate_metrics": {}
}
```

Shadow window start gate:
- producer ID coverage >= 99%;
- closed outcome coverage >= 98%;
- duplicate outcomes = 0;
- mixed artifact/schema = 0;
- unresolved critical orphan = 0;
- full lifecycle E2E/recovery tests passed.

Shadow window completion gate:
- real elapsed duration from `shadow_window_started_at` >= 7 consecutive days;
- `shadow_window_valid = true`;
- `closed_trade_prediction_to_outcome_rate >= 90%`;
- unresolved critical orphan = 0;
- daily calibration reports complete;
- report freshness <= 24h;
- no hard reset during the window.

## Phase Status

| Workstream | Status |
| --- | --- |
| WS0 Contracts | Done foundation |
| WS1 Stable IDs | Done foundation, producer migration ongoing |
| WS2 Prediction linkage | Paper path passed for covered E2E |
| WS3 Execution linkage | Paper reservation/order/fill path passed for covered E2E |
| WS4 Outcome recorder | Paper closed outcome path passed for covered E2E |
| WS5 Runtime linker | Implemented, shadow evidence pending |
| WS6 Calibration | Implemented, insufficient runtime samples |
| WS7 Governance | Framework complete, not yet exercised with runtime evidence |
| WS8 Adaptive traceability | Implemented for new records |
| WS9 Observability | Health foundation complete; external alert wiring pending |
| WS10 Documentation | Done for framework state |

## Rollout Gates

Gate A - Producer integration complete:
- required lifecycle ID coverage >= 99%;
- closed-position outcome coverage >= 98%;
- duplicate outcomes = 0;
- mixed schema/artifact samples = 0.

Gate B - Shadow linkage stable:
- prediction-to-outcome linkage >= 90%;
- stable for at least 7 days;
- unresolved critical orphan = 0.

Gate C - Calibration ready:
- linkage >= 95%;
- outcome coverage >= 98%;
- report freshness <= 24h;
- minimum sample threshold met.

Gate D - Promotion eligible:
- paired candidate/production comparison;
- statistical gate pass;
- shadow window pass;
- rollback test pass;
- tail evidence sufficient, or tail sizing clamp remains enabled.

## Decision

Governance framework is closed at the framework layer. Do not add more governance abstraction before runtime data exists.

Do not retrain or promote Meta Model from this change alone. The correct next sequence is:

```text
producer migration
→ paper lifecycle E2E
→ timeout/restart/out-of-order/partial-fill recovery tests
→ create GateSnapshot from runtime metrics
→ start shadow window
→ collect 7 consecutive valid evidence days
→ Gate B
→ runtime calibration readiness review
```

Hard gates throughout rollout:

```text
duplicate outcome = 0
mixed artifact/schema sample = 0
```

## Producer Rollout Progress

Initial paper producer migration is now started:

- `prediction_logger.py` emits contract-valid `prediction_created` events.
- `execution_engine.py` paper/live `ExecutionRecord` carries lifecycle IDs from signal payload:
  - `prediction_id`
  - `signal_id`
  - `entry_decision_id`
  - `reservation_id`
  - `idempotency_key`
  - `client_order_id`
  - `exchange_order_id`
  - `position_id`
  - `lifecycle_schema_version`
- `auto_trader.py` passes available prediction/decision lifecycle IDs into execution and position sync.
- `position_tracker.py` persists lifecycle IDs on open positions and closed outcomes.
- Closed outcomes now include `outcome_id`, `outcome_revision`, `closed_at`, and `net_pnl_pct`.
- Paper execution now creates and commits reservation records for entry orders.
- Paper `idempotency_key` is preserved as `client_order_id` unless an explicit client order ID is provided.
- Paper execution has test hooks for timeout-after-reserve, crash-after-fill-before-commit, partial fill, and cancel remaining.
- Paper duplicate idempotency replay reuses the committed reservation and does not simulate a second fill.
- Paper reservations are released on execution risk rejection or order-selection skip.
- Paper recovery simulation flags are rejected by the live execution path.
- `order_fill_ledger.py` persists fills that arrive before orders and reconciles them after restart by `exchange_trade_id`, `exchange_order_id`, and `client_order_id`.
- `order_fill_ledger.py` is explicitly `single_writer_only` for JSON shadow rollout.
- Ambiguous ledger reconciliation is quarantined instead of auto-selecting an order.
- Corrupt ledger state fails closed instead of silently starting from an empty ledger.

Paper lifecycle E2E proof added:

```text
prediction
→ entry decision
→ reservation
→ submitted paper order
→ paper execution/fill
→ open position
→ closed outcome
→ runtime linker
→ calibration sample
```

Verified properties:
- lifecycle IDs remain stable across the chain;
- linker uses stable IDs, not timestamp joins;
- duplicate outcome replay does not create a second sample;
- linker rerun via JSONL sample store does not append duplicate samples;
- producer coverage over actual paper E2E records is 100% for prediction, entry decision, reservation, submitted order, fill, open position, and closed outcome;
- model version, artifact hash, and feature schema remain attached to the calibration sample.

Verification command:

```bash
.venv/bin/pytest tests/ml/test_paper_lifecycle_e2e.py tests/ml/test_runtime_linkage_calibration.py -q
```

Result:

```text
43 passed
```

Recovery/partial-fill focused command:

```bash
.venv/bin/pytest tests/ml/test_paper_lifecycle_e2e.py -q
```

Result:

```text
11 passed
```

Covered recovery cases:
- timeout after reservation, restart, and idempotent retry using the same reservation/client order ID;
- fill recorded before reservation commit, restart, and idempotent commit recovery;
- partial fill followed by cancel/release of remaining reservation;
- partial-fill accounting bounds: filled notional does not exceed reserved notional and released notional remains non-negative;
- duplicate idempotency replay after commit does not create a new reservation or second paper fill;
- live execution rejects paper recovery simulation flags;
- fill-before-order is persisted as pending, survives restart, resolves when the order arrives, and remains idempotent under replay;
- ambiguous fill/order reconciliation is quarantined;
- corrupt ledger JSON fails closed;
- full-chain replay on the covered paper path keeps prediction, decision, reservation, order/fill, position, outcome, and active calibration sample counts unchanged;
- operational restart with persisted paper position data closes the existing position, preserves lifecycle IDs, avoids refilling, and writes one active calibration sample;
- linker/sample store rerun idempotency.
- outcome-before-prediction pending-link state and later resolution at linker level;
- outcome amendment revision 2 superseding revision 1 at linker level;
- runtime calibration report uses only the latest active amendment revision;
- mixed artifact/schema mismatch quarantine at linker level;
- runtime mixed-metadata quarantine with separate `model_version`, `artifact_sha256`, and `feature_schema_version` mismatch coverage.

Gate A runtime evidence tooling added:
- `btc_scraper/ml_engine/gate_a_runtime_evidence.py` evaluates only paper-runtime records and excludes legacy, offline-only, synthetic, debug, replay, and test records.
- `scripts/generate_gate_a_runtime_evidence.py` generates a persisted JSON evidence report without starting the shadow window.
- A `GateSnapshot` is returned only if all Gate A blockers are clear and the closed paper position count meets the configured minimum.

Gate A evidence report includes:

```json
{
  "prediction_coverage": 1.0,
  "entry_decision_coverage": 1.0,
  "reservation_coverage": 1.0,
  "submitted_order_coverage": 1.0,
  "fill_coverage": 1.0,
  "open_position_coverage": 1.0,
  "closed_outcome_coverage": 1.0,
  "duplicate_outcomes": 0,
  "mixed_artifact_schema_samples": 0,
  "unresolved_critical_orphans": 0,
  "closed_position_count": 20,
  "gate_a_ready": true
}
```

Example command after paper runner exports fresh runtime records:

```bash
.venv/bin/python scripts/generate_gate_a_runtime_evidence.py \
  --prediction path/to/predictions.jsonl \
  --entry-decision path/to/entry_decisions.jsonl \
  --reservation path/to/reservations.jsonl \
  --submitted-order path/to/orders.jsonl \
  --fill path/to/fills.jsonl \
  --open-position path/to/open_positions.jsonl \
  --closed-outcome path/to/closed_outcomes.jsonl \
  --outcomes path/to/closed_outcomes.jsonl \
  --lifecycle-e2e-passed \
  --recovery-tests-passed \
  --min-closed-positions 20
```

Still pending:
- Gate A verification from paper runtime coverage records.

Compatibility subset:

```bash
.venv/bin/pytest tests/test_trade_provenance.py tests/test_phase1_execution_pipeline_integration.py::TestExecutionEnginePaperMode tests/test_phase10_execution_pipeline.py::TestExecutionEnginePaper -q
```

Result:

```text
11 passed
```

Trade provenance and WLD correction update:

Delivered:
- `position_tracker.py` normalizes order provenance into `order_creator` and `order_channel`;
- `auto_trader.py` marks paper orders as `system + paper_runner`;
- Telegram `/buy` marks user orders as `user + telegram`;
- `scripts/manage_positions.py` marks CLI orders as `user + cli`;
- `/positions` now displays `Nguồn`, for example `System paper mode` or `User via Telegram`;
- `scripts/backfill_trade_provenance.py` can annotate legacy records with the same provenance fields;
- WLD duplicate open position was removed and the prior closed WLD trade was corrected to manual/system-signal provenance.

Corrected WLD record:

```text
id: deadd193-2f1b-4bd1-afef-c75a95d33181
direction: SHORT
entry_price: 0.3978
sell_price: 0.3943
invested_usdt: 500.0
pnl_pct: 0.8798
pnl_usd_actual: 4.40
fee_usd: 1.00
received_usdt: 503.39
r_multiplier: 0.51
result: WIN
trade_origin: manual
manual_decision_basis: system_signal
order_channel: telegram
```

Verification:

```bash
.venv/bin/pytest tests/test_trade_provenance.py tests/ml/test_paper_lifecycle_e2e.py -q
```

Result:

```text
19 passed
```

Operational correction backup:

```text
data/cleanup/wld_manual_signal_correction_backup_2026-07-17.json
```
