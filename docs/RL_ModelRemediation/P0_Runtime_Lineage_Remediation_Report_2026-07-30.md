# P0 Runtime Lineage Remediation — Implementation Report

**Project:** `besttime-crypto`  
**Module:** `btc_scraper.ml_engine` and the production paper-trading lifecycle  
**Report date:** 2026-07-30  
**Scope:** Commit 1–3 — prediction envelope propagation, single inference owner, and production-path E2E evidence  
**Status:** Implemented and regression-tested  

## 1. Executive summary

The immediate production-readiness blocker was runtime lineage, not model
training quality. The runtime could create predictions and decisions, but it
did not reliably preserve a single prediction identity through execution,
position tracking, and outcome persistence. It also allowed multiple
components to invoke the meta model independently.

This remediation establishes the following canonical lifecycle:

```text
Market analysis
→ AgentOrchestrator
→ one deterministic signal_id
→ InferenceCoordinator.predict_once()
→ one prediction_id
→ one final decision
→ AutoTrader
→ reservation
→ paper execution/fill
→ position
→ position close
→ one SQLite outcome link
```

The new production path preserves the same lineage envelope across every
material lifecycle object:

```text
signal_id
prediction_id
model_version
model_artifact_sha256 / artifact_sha256
feature_schema_version
deployment_id
decision_context
caller_context
```

Model retraining, model promotion, risk-policy changes, legacy trainer
lockdown, v3 feature parity, and RL/causal cleanup were deliberately excluded
from this implementation.

## 2. Baseline findings

The pre-remediation assessment found:

| Finding | Observed baseline |
|---|---:|
| Runtime predictions inspected | 25,128 |
| Runtime final decisions inspected | 4,378 |
| Runtime outcome links | 0 |
| Predictions with null `signal_id` | All inspected rows |
| Predictions with `symbol=UNKNOWN` | 16,165 |
| Deployment lineage mismatch | Present across inspected rows |
| Duplicate inference path | Signal scoring and causal decision path |

The primary failure chain was:

1. Meta-model inference created a prediction event.
2. `score_signal()` retained probability but dropped the prediction envelope.
3. The causal decision path could call the meta model again.
4. `AutoTrader` consumed analysis-level fields that no longer had a reliable
   `prediction_id`.
5. Positions were therefore commonly opened without prediction lineage.
6. `PositionTracker` only writes outcome evidence for model-linked positions.
7. The runtime evidence store accumulated predictions and decisions but no
   usable closed-trade outcome evidence.

## 3. Implemented architecture

### 3.1 Immutable prediction envelope

A frozen `MetaPrediction` contract now represents one inference result:

```python
@dataclass(frozen=True)
class MetaPrediction:
    signal_id: str
    prediction_id: str
    symbol: str
    decision_context: str
    caller_context: str
    probability: float
    model_version: str
    artifact_sha256: str
    feature_schema_version: str
    deployment_id: str
    feature_hash: str
```

`signal_id` is deterministic from the deployment, symbol, timeframe,
observation boundary, signal, and decision context. Production entry inference
fails when no observation boundary is available instead of inventing an
unstable identifier.

### 3.2 Single entry inference owner

`InferenceCoordinator` is now the entry inference owner.

The coordinator:

- creates or reuses a deterministic `signal_id`;
- checks durable evidence before invoking the model;
- serializes in-process inference through a lock;
- calls the meta model only when no matching persisted prediction exists;
- validates all required lineage fields before returning;
- returns a frozen `MetaPrediction`;
- reuses the persisted prediction on restart or replay.

The idempotency key is:

```text
{signal_id}:{model_version}:{decision_context}
```

`SignalGeneratorAgent` requests the prediction once and passes the resulting
envelope to signal scoring and causal decision logic. `score_signal()` and the
causal bridge no longer create a second entry prediction.

### 3.3 Storage-layer idempotency

Runtime evidence schema version was raised to version 3. A dedicated
`prediction_idempotency` table enforces:

```text
idempotency_key PRIMARY KEY
prediction_id UNIQUE
prediction_id FOREIGN KEY → predictions.prediction_id
```

A separate table was selected instead of a JSON expression index so corrupt
JSON payloads can still be injected, detected, and quarantined by evidence
health checks.

Prediction IDs derived from an idempotency key are deterministic UUIDv5
values. Repeated writes return the canonical persisted event and do not append
duplicate JSONL compatibility records.

### 3.4 End-to-end envelope propagation

The envelope is propagated through:

| Runtime object | Lineage behavior |
|---|---|
| Analysis result | Receives the coordinator envelope |
| Signal score | Returns prediction identity and model/deployment metadata |
| Causal decision input | Consumes the precomputed prediction |
| Final decision | References exactly one known prediction |
| `EntryDecision` | Carries prediction and model/deployment context |
| Execution signal | Carries the full envelope |
| Execution record | Persists the envelope with the order attempt |
| Reservation | Stores the envelope in SQLite |
| Position | Stores prediction, model, schema, deployment, and contexts |
| Closed outcome | Inherits the position envelope |
| Outcome link | References the original prediction in runtime evidence SQLite |

The reservation schema migration is safe when multiple recovery processes
initialize the same database concurrently.

### 3.5 Caller and decision contexts

The following runtime contexts are now explicit:

| Caller | `decision_context` | `caller_context` |
|---|---|---|
| Production agent entry | `entry` | `agent_orchestrator` |
| AutoTrader MTF entry | `entry` | `auto_trader_mtf` |
| Position re-evaluation | `exit_recheck` | `position_tracker` |
| Dashboard preview | `ui_preview` | `ui_dashboard` |
| Unclassified direct runtime call | `unclassified` | `direct_runtime` |

Only new runtime predictions with `entry` or `shadow_entry` context are
eligible for the entry shadow gate. UI, exit, backtest, offline, test, and E2E
callers do not contribute to entry evidence.

### 3.6 Invalid lineage handling

New `prediction_created` records are contract-validated for:

```text
prediction_id
signal_id
symbol
decision_context
caller_context
deployment_id
model_version
artifact_sha256
feature_schema_version
feature_hash
```

Persisted production prediction events with missing lineage or
`symbol=UNKNOWN` are quarantined during evidence verification. Quarantined
predictions are excluded from shadow evidence and cause evidence health to
degrade.

This hardening was included because it is an explicit acceptance criterion for
the Commit 1–3 production lineage path. It does not implement the broader
health-rate policies planned for Commit 4.

## 4. Production-path E2E evidence

The new E2E test starts at the real `AgentOrchestrator` boundary. Unrelated
market collection, portfolio, risk, and RL dependencies are isolated so the
test remains deterministic, while the following production components remain
real:

```text
AgentOrchestrator.run_cycle()
→ SignalGeneratorAgent
→ InferenceCoordinator
→ meta-model prediction logger
→ signal scoring
→ causal decision / final decision persistence
→ AutoTrader
→ ExecutionEngine.submit_paper()
→ ReservationStore
→ FillTracker
→ PositionTracker.add_position()
→ RuntimeEvidenceStore restart
→ PositionTracker.close_position()
→ RuntimeEvidenceStore.append_outcome_link()
→ SQLite evidence query
```

The test does not inject a `prediction_id` between lifecycle stages.

It asserts:

- `signal_id` and `prediction_id` are non-null;
- exactly one prediction is persisted;
- exactly one final decision references that prediction;
- order and reservation reference the same prediction;
- position carries the complete envelope;
- the evidence store can be reopened before close;
- close creates exactly one outcome link;
- duplicate close does not create another outcome;
- replay after store restart reuses the same prediction;
- replay does not invoke the model a second time.

## 5. Acceptance criteria

| Criterion | Status | Evidence |
|---|---|---|
| New production prediction has non-null `signal_id` | PASS | Contract plus coordinator validation |
| New production prediction has non-null `deployment_id` | PASS | Runtime path metadata and contract |
| No `UNKNOWN` symbol on production entry path | PASS | Coordinator supplies normalized symbol |
| Paper position has `prediction_id` | PASS | Production-path E2E |
| Position close creates an outcome link | PASS | Production-path E2E |
| One prediction per signal/model/context | PASS | Coordinator lookup, lock, deterministic ID, SQLite unique key |
| One final decision per prediction | PASS | Existing unique constraint plus E2E assertion |
| Replay does not create another prediction | PASS | Restart/replay test |
| Duplicate close does not create another outcome | PASS | Duplicate-close test |
| Invalid production lineage is quarantined | PASS | Evidence health test |
| Invalid lineage is excluded from shadow evidence | PASS | Shadow evidence test |
| UI and exit prediction are not entry evidence | PASS | Context eligibility test |
| Full non-network suite has zero failures | BLOCKED outside scope | One pre-existing frozen RL mapping failure |

## 6. Validation results

### 6.1 Focused validation

The final focused suite covering production lineage, evidence storage, shadow
eligibility, recovery concurrency, and alternative-reference integration
passed:

```text
25 passed
```

Additional focused regression runs covering contracts, decision engine,
AutoTrader, reservations, causal bridge, and paper lifecycle also passed.

`compileall` and `git diff --check` passed for the affected source and test
trees.

### 6.2 Full non-network suite

Collected non-network tests:

```text
813
```

Result:

```text
812 passed
1 failed
```

The sole failure is the pre-existing RL regime mapping:

```text
tests/test_rl_env.py::test_trade_exit_env_spaces
actual:   RANGING_ZONE → STRONG_TREND
expected: RANGING_ZONE → MEAN_REVERSION
```

The RL mapping belongs to Commit 8 and was intentionally not changed while
Commit 1–3 remain the active scope.

## 7. Files changed

### Core inference and evidence

- `btc_scraper/ml_engine/inference_coordinator.py`
- `btc_scraper/ml_engine/meta_model.py`
- `btc_scraper/ml_engine/prediction_logger.py`
- `btc_scraper/ml_engine/runtime_evidence_store.py`
- `btc_scraper/ml_engine/data_contracts.py`
- `btc_scraper/ml_engine/shadow_validation.py`

### Decision pipeline

- `btc_scraper/ml_engine/signal_score.py`
- `btc_scraper/ml_engine/multi_agent.py`
- `btc_scraper/ml_engine/causal_context_bridge.py`
- `btc_scraper/ml_engine/decision_engine.py`

### Execution and outcome propagation

- `btc_scraper/trading/auto_trader.py`
- `btc_scraper/trading/decision_types.py`
- `btc_scraper/trading/position_tracker.py`
- `btc_scraper/execution/execution_engine.py`
- `btc_scraper/execution/fill_tracker.py`
- `btc_scraper/execution/reservation_store.py`
- `btc_scraper/ui/dashboard.py`

### Tests

- `tests/ml/test_production_lineage_path.py`
- `tests/ml/test_runtime_evidence_store.py`
- `tests/ml/test_shadow_validation.py`
- `tests/ml/test_data_contracts.py`
- `tests/ml/test_prediction_traceability.py`
- related causal, recovery, and integration tests

## 8. Residual risks and exclusions

The following remain intentionally unresolved:

1. Risk evaluation still requires the planned fail-closed remediation.
2. Legacy trainer production-write restrictions are not part of this change.
3. Candidate v3 remains unpromoted and runtime feature parity is unproven.
4. RL `RANGING_ZONE` mapping remains incorrect.
5. Partial-fill-to-close lineage does not yet have a new dedicated P0 E2E
   scenario, although existing execution partial-fill behavior remains covered
   by its own tests.
6. A global unique key across daily SQLite partitions is implemented through
   coordinator lookup plus per-partition uniqueness. A simultaneous
   cross-process write exactly across the UTC partition boundary remains an
   edge case for later evidence-store hardening.
7. Existing historical evidence remains contaminated by null lineage and
   `UNKNOWN` symbols and must not be mixed with the new evidence epoch.

## 9. Operational decision

```text
Commit 1 — Prediction envelope propagation: COMPLETE
Commit 2 — Single inference owner: COMPLETE
Commit 3 — Production-path E2E evidence: COMPLETE

Automated live entry: REMAINS BLOCKED
Paper/shadow execution: ALLOWED under existing controls
Candidate v3 promotion: BLOCKED
RL promotion: BLOCKED
Historical evidence reuse: NOT ALLOWED
```

No model was retrained or promoted as part of this remediation.

## 10. Recommended next actions

Before restarting shadow accumulation:

1. Review and merge the Commit 1–3 source changes.
2. Deploy them under a new controlled deployment identifier.
3. Reset the evidence window or open a new evidence epoch.
4. Do not import the 25,128 historical predictions into the new eligibility
   cohort.
5. Confirm production health reports:
   - 100% non-null `signal_id`;
   - 100% non-null `deployment_id`;
   - zero eligible `UNKNOWN` symbols;
   - one prediction per signal/model/context;
   - non-zero linked paper outcomes.
6. Implement Commit 4 evidence hardening and Commit 5 risk fail-closed before
   authorizing live entry.
7. Address the frozen RL mapping only when Commit 8 is explicitly opened.

## 11. Conclusion

The runtime has moved from disconnected prediction and execution components to
a testable, durable prediction-to-outcome evidence path. A single production
entry inference now owns the prediction, and every downstream lifecycle object
retains the same identity through close and SQLite outcome linkage.

This resolves the minimum structural blocker for collecting new shadow
evidence. It does not, by itself, authorize model promotion or automated live
trading.
