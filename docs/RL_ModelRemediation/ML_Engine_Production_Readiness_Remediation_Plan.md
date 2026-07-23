# ML Engine Production Readiness Remediation Plan

> **Project:** `besttime-crypto`  
> **Scope:** `btc_scraper/ml_engine/` and related runtime integrations  
> **Current assessment:** 6/10  
> **Initial status:** Production readiness blocked  
> **Target:** Restore decision correctness, calibration validity, governed artifact loading, RL environment correctness, process-safe governance, transactional runtime evidence, deterministic reporting, and observable degradation.

> **Implementation status (2026-07-23):** Waves 0–10 implemented. Gates A, B-code, C, and E pass offline validation. Gate D remains blocked pending RL retraining; Gate F remains blocked pending shadow evidence and explicit manual reauthorization. Automated live entry is fail-closed in `config/ml_engine_readiness.json`.

---

## 1. Executive Summary

The current `ml_engine` has good foundations in inference separation, causal context, RL, calibration, lifecycle, model registry, artifact hashes, schema validation, circuit breakers, outcome linkage, time-ordered splitting, and walk-forward validation.

However, the following issues block automated live trading:

1. Context hard-risk decisions can be overwritten by posterior-based action recomputation.
2. `decide_with_provider()` performs inference twice.
3. Calibration method selection uses the final test set.
4. Calibration buckets report bucket midpoints instead of actual mean predicted probabilities.
5. Runtime meta-model inference bypasses artifact registry, metadata, schema, and hash checks.
6. RL multi-trade state is not fully reset.
7. Gymnasium `terminated`/`truncated` semantics are inconsistent.
8. Model registry updates are vulnerable to inter-process lost updates.
9. Prediction and feature evidence are not persisted transactionally.
10. Runtime calibration tests depend on wall-clock time.
11. Broad silent exceptions can hide loss of governance or audit evidence.

Operational posture until completion:

```text
Automated live entry: BLOCKED
Paper/shadow execution: ALLOWED
Offline retraining: ALLOWED
Existing calibration evidence: REVALIDATION REQUIRED
Existing RL policies: ENVIRONMENT REASSESSMENT REQUIRED
```

---

## 2. Remediation Principles

```text
Hard safety > governance > context risk > model action > sizing
```

Mandatory invariants:

- One `signal_id` produces one base inference, one prediction record, and one final decision.
- A final holdout set is never used for calibration method, threshold, or model selection.
- Every runtime model is resolved and verified before deserialization.
- Governance failures fail closed.
- Missing audit evidence degrades health and emits metrics.
- Exit and emergency-exit paths are never blocked by optional ML components.
- Every time-dependent report accepts an explicit clock or `generated_at`.

---

# Wave 0 — Freeze, Baseline, and Evidence Preservation

## Tasks

1. Create source tag:

```text
ml-engine-pre-remediation-YYYYMMDD
```

2. Archive:

```text
production registry
artifact metadata and hashes
current calibration reports
runtime calibration reports
RL policy artifacts
prediction logs
feature snapshots
promotion decisions
```

3. Record baseline:

```bash
python -m compileall btc_scraper/ml_engine
pytest tests/ml_engine -q
pytest tests -m "not network" -q
```

4. Create blocker register:

```text
docs/remediation/ML_Engine_Blocker_Register.md
```

Required fields:

```text
issue_id
severity
affected_files
failure_mode
regression_test
owner
status
release_gate
```

## Exit Criteria

- Source and evidence are preserved.
- Current production slot is documented.
- No promotion occurs during remediation without an explicit override.
- Live entry remains blocked.

---

# Wave 1 — Hard Risk Gate Correctness

## Affected Files

```text
btc_scraper/ml_engine/decision_engine.py
tests/test_decision_engine.py
tests/test_ml_context_integration.py
```

## Target Flow

```text
base inference
→ context adjustment
→ proposed action
→ final hard-risk gate
→ immutable final decision
```

## Required Action Contract

```python
from enum import Enum


class DecisionAction(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"
    BLOCK_ENTRY = "BLOCK_ENTRY"
    ALLOW_REDUCE_ONLY = "ALLOW_REDUCE_ONLY"
    ALLOW_EXIT_ONLY = "ALLOW_EXIT_ONLY"
```

## Final Gate

```python
def apply_final_risk_gate(
    proposed_action: DecisionAction,
    risk_level: str,
    stop_processing: bool,
) -> tuple[DecisionAction, tuple[str, ...]]:
    if not stop_processing:
        return proposed_action, ()

    if risk_level == "CRITICAL":
        return DecisionAction.ALLOW_EXIT_ONLY, (
            "critical_context_hard_stop",
        )

    if risk_level == "HIGH" and proposed_action in {
        DecisionAction.BUY,
        DecisionAction.SELL,
    }:
        return DecisionAction.BLOCK_ENTRY, (
            "high_context_entry_block",
        )

    return proposed_action, ()
```

## Required Tests

```text
critical stop cannot return BUY
critical stop cannot return SELL
high-risk stop cannot be overwritten
exit remains allowed
posterior recomputation cannot bypass final gate
reason codes are persisted
```

## Exit Criteria

- Hard gate is applied last.
- HIGH/CRITICAL semantics are explicit.
- No exposure-increasing action survives a critical stop.
- Final decisions are immutable and audited.

---

# Wave 2 — One Inference per Decision

## Refactor

```python
base_decision = self.decide(...)
context = provider.get_context(...)
final_decision = self.apply_context(
    base_decision=base_decision,
    context=context,
)
```

`apply_context()` must not call `decide()`.

## Identity Contract

Every final decision must contain:

```text
signal_id
prediction_id
decision_id
context_snapshot_id
model_version
artifact_sha256
```

## Tests

```text
model predict called exactly once
one prediction audit per decision
context references the same base prediction
provider failure does not trigger reinference
base/final posterior lineage is preserved
```

## Exit Criteria

- One inference per signal.
- One prediction record per decision.
- No duplicated latency or duplicate audit writes.

---

# Wave 3 — Calibration Correctness

## Affected Files

```text
btc_scraper/ml_engine/meta_model_v3.py
btc_scraper/ml_engine/calibration.py
tests/test_meta_model_v3.py
tests/test_calibration.py
```

## Split Contract

```text
TRAIN
CALIBRATION or INNER TIME-SERIES CV
FINAL HOLDOUT
```

The final holdout must not influence:

```text
calibration method
threshold
hyperparameters
promotion choice
```

## Correct Flow

```python
base_model.fit(X_train, y_train)

sigmoid = fit_sigmoid(base_model, X_calib, y_calib)
isotonic = fit_isotonic(base_model, X_calib, y_calib)

selected = choose_on_calibration_set(
    sigmoid=sigmoid,
    isotonic=isotonic,
    X_calib=X_calib,
    y_calib=y_calib,
)

holdout_probs = selected.predict_proba(X_holdout)
final_metrics = evaluate_once(holdout_probs, y_holdout)
```

## Required Metadata

```json
{
  "calibration_method": "isotonic",
  "calibration_selection_split": "CALIBRATION",
  "final_evaluation_split": "FINAL_HOLDOUT",
  "holdout_used_for_selection": false,
  "split_manifest_sha256": "..."
}
```

## Calibration Bucket Fix

```python
@dataclass
class CalibrationBucket:
    probabilities: list[float]
    labels: list[int]

    @property
    def predicted_probability(self) -> float | None:
        if not self.probabilities:
            return None
        return sum(self.probabilities) / len(self.probabilities)

    @property
    def observed_rate(self) -> float | None:
        if not self.labels:
            return None
        return sum(self.labels) / len(self.labels)
```

Expected calibration error:

```python
ece += (
    bucket_count / total_count
    * abs(bucket.observed_rate - bucket.predicted_probability)
)
```

## Evidence Invalidation

Tag existing reports as applicable:

```text
INVALIDATED_HOLDOUT_SELECTION_LEAKAGE
INVALIDATED_CALIBRATION_BUCKET_BUG
```

## Tests

```text
calibrator selection never reads holdout
holdout evaluated exactly once
bucket predicted probability uses actual mean
ECE fixture matches a reference calculation
probability boundaries 0 and 1
empty bucket handling
time ordering preserved
```

## Exit Criteria

- Holdout isolation is proven.
- ECE/Brier reports are regenerated.
- Invalid historical evidence is marked.
- Promotion evidence includes split lineage.

---

# Wave 4 — Unified Governed Artifact Loader

## New File

```text
btc_scraper/ml_engine/governed_artifact_loader.py
```

## Required Load Sequence

```text
resolve deployment slot
→ require metadata
→ verify registry permission
→ verify lifecycle state
→ verify SHA-256
→ verify feature schema
→ verify runtime compatibility
→ deserialize
→ emit load audit
```

## Interface

```python
@dataclass(frozen=True)
class LoadedArtifact:
    model: object
    artifact_id: str
    artifact_sha256: str
    model_version: str
    feature_schema_version: str
    lifecycle_status: str


class GovernedArtifactLoader:
    def load_production(
        self,
        model_family: str,
        expected_schema_version: str,
    ) -> LoadedArtifact:
        ...
```

## Fail-Closed Conditions

```text
registry unavailable
metadata missing
artifact not promoted
hash mismatch
schema mismatch
unsupported runtime contract
artifact path outside approved root
```

## Migration Order

```text
meta model
adaptive signal model
causal model
RL policy
future crowding/portfolio ML models
```

## Static CI Rule

Direct model deserialization is allowed only in the governed loader.

Scan for:

```text
joblib.load
pickle.load
torch.load
stable_baselines load
```

## Tests

```text
unpromoted artifact rejected
tampered artifact rejected before deserialize
hash mismatch rejected
missing metadata rejected
schema mismatch rejected
approved production artifact loads
rollback artifact resolves correctly
```

## Exit Criteria

- No runtime direct model load remains.
- Prediction records include artifact lineage.
- All model families use the same governance path.

---

# Wave 5 — RL Environment Correctness

## Affected Files

```text
btc_scraper/ml_engine/rl_trading_env.py
tests/test_rl_trading_env.py
tests/test_rl_multi_trade.py
```

## Central Reset

Create one reset function for all trade-local state:

```python
def _reset_trade_state(self, trade) -> None:
    self.current_step = 0
    self.entry_price = trade.entry_price
    self.prev_pnl = 0.0
    self.max_pnl = 0.0
    self.min_pnl = 0.0
    self.current_drawdown = 0.0
    self.holding_steps = 0
    self.last_action = None
    self.trade_done = False
```

Review and reset:

```text
trailing stop
peak equity
reward accumulator
position state
last action
holding duration
drawdown
```

## Gymnasium Semantics

```python
terminated = terminal_condition
truncated = (
    self.current_step >= self.max_episode_steps
    and not terminated
)
```

## Existing Policy Policy

Tag current policies:

```text
REQUIRES_ENVIRONMENT_REVALIDATION
```

Decision:

```text
minor metric drift → re-evaluate
material reward/state drift → retrain
confirmed cross-trade leakage during training → retrain required
```

## Tests

```text
trade B starts with clean state
first reward of B is independent of A
drawdown does not leak
time-limit only returns truncated
real terminal condition returns terminated
observation and action contracts unchanged
```

## Exit Criteria

- No cross-trade state leakage.
- Gymnasium contract is correct.
- Existing policies are re-evaluated or retrained.
- New evaluation evidence is stored.

---

# Wave 6 — Process-Safe Model Registry

## Affected File

```text
btc_scraper/ml_engine/model_registry.py
```

## Transaction

```text
acquire inter-process lock
→ reload latest registry
→ validate expected state
→ apply mutation
→ write temp
→ fsync temp
→ os.replace
→ fsync parent directory
→ release lock
```

Use Linux `fcntl.flock` or a tested cross-process lock library.

## Compare-and-Set Promotion

```python
promote(
    candidate_id,
    expected_current_production_id,
)
```

A changed production slot must raise:

```text
RegistryConflictError
```

## Invariants

```text
one production artifact per family/slot
valid lifecycle transitions only
rollback target must exist
retired artifact cannot silently return to production
```

## Tests

```text
two concurrent registrations preserve both
concurrent promotions conflict safely
rollback vs promotion conflict
crash does not leave partial registry
lock releases after exception
single production invariant
```

## Exit Criteria

- No lost update.
- Promotion uses CAS.
- Registry survives concurrent writers and crash scenarios.

---

# Wave 7 — Transactional Prediction Evidence

## Preferred Design

Use SQLite append-only runtime evidence:

```text
predictions
feature_snapshots
final_decisions
outcome_links
audit_events
```

Persist prediction, snapshot, and decision in one transaction.

## Invariants

```text
prediction has feature snapshot
decision references prediction
outcome references prediction
payload hash matches
duplicate write is idempotent
```

## Temporary JSONL Fallback

If SQLite migration cannot happen immediately:

```text
single writer
inter-process lock
combined evidence envelope
payload SHA-256
fsync
recovery scan
```

## Tests

```text
crash leaves no partial evidence
concurrent writes preserve all records
duplicate writes are idempotent
orphan records detected
corrupt payload quarantined
reopen/replay succeeds
```

## Exit Criteria

- Audit evidence is atomic.
- No prediction/snapshot orphan remains.
- Evidence health is exposed.

---

# Wave 8 — Deterministic Runtime Calibration

## Affected File

```text
btc_scraper/ml_engine/runtime_calibration.py
```

## Contract

```python
def runtime_calibration_report(
    records,
    *,
    generated_at: datetime,
    window_days: int = 7,
):
    ...
```

Production passes `clock.now()`. Tests pass a fixed timestamp.

## Window Semantics

```text
timestamp >= generated_at - window
timestamp <= generated_at
timezone = UTC
```

## Tests

```text
exact lower boundary included
one microsecond before excluded
future record excluded
latest amendment only
fixed-time rerun is identical
timezone normalization
```

## Exit Criteria

- No hidden wall-clock dependency.
- Existing flaky tests are deterministic.
- Boundary semantics are documented.

---

# Wave 9 — Structured Errors, Metrics, and Health

## Replace

```python
except Exception:
    pass
```

with structured handling:

```python
except Exception as exc:
    metrics.increment("prediction_audit_write_failure_total")
    logger.warning(
        "Prediction audit write failed",
        extra={
            "signal_id": signal_id,
            "model_version": model_version,
            "error_type": type(exc).__name__,
        },
    )
```

## Error Policy

| Error | Behavior |
|---|---|
| Inference failure | fail closed or approved fallback |
| Governance failure | fail closed |
| Artifact mismatch | fail closed |
| Audit write failure | continue with degraded health |
| Optional context failure | reduce confidence |
| Calibration report failure | block promotion |
| Registry failure | block load/promotion |

## Health Schema

```json
{
  "ml_inference": "healthy",
  "ml_governance": "healthy",
  "artifact_loader": "healthy",
  "prediction_audit": "degraded",
  "runtime_calibration": "healthy",
  "rl_environment": "healthy"
}
```

## Metrics

```text
ml_inference_failure_total
artifact_load_rejected_total
prediction_audit_write_failure_total
context_provider_failure_total
registry_conflict_total
calibration_report_failure_total
```

## Exit Criteria

- Critical paths contain no silent exception.
- Health reflects audit/governance degradation.
- Structured metrics and reason codes are emitted.

---

# Wave 10 — Architecture Consolidation

## Target Structure

```text
btc_scraper/ml_engine/
├── contracts/
├── inference/
├── training/
├── governance/
├── runtime/
├── rl/
└── causal/
```

Consolidate to:

```text
one decision contract
one calibration reporting standard
one artifact loading standard
one runtime evidence store
clear training/runtime separation
```

Migration method:

```text
introduce new API
→ migrate callers
→ emit deprecation warnings
→ remove legacy paths
```

## Exit Criteria

- `meta_model.py` and `meta_model_v3.py` no longer represent competing runtime standards.
- Legacy direct inference/governance paths are removed.
- Training code is not imported into live inference paths.

---

## 11. Required Test Matrix

### Decision

```text
critical context blocks entry
high risk cannot be overwritten
one inference per signal
one audit record
exit always available
```

### Calibration

```text
holdout isolation
actual mean probability in bucket
reference ECE/Brier
split metadata
invalid evidence tagging
```

### Artifact Governance

```text
unpromoted artifact rejected
hash/schema mismatch rejected
metadata required
rollback tested
direct-load scan clean
```

### RL

```text
complete state reset
no reward/drawdown leakage
correct terminated/truncated semantics
policy revalidation
```

### Concurrency and Evidence

```text
registry concurrent update
promotion CAS conflict
atomic prediction evidence
crash recovery
idempotent replay
```

### Determinism and Observability

```text
fixed-clock reports
window boundary
health degradation
metric counters
structured warnings
```

---

## 12. CI Gates

Required offline jobs:

```bash
python -m compileall btc_scraper/ml_engine
pytest tests/ml_engine -m "not network" -q
pytest tests/test_ml_engine_* -q
```

Static safety checks:

```text
no direct model deserialize outside governed loader
no `except Exception: pass`
no hidden datetime.now in deterministic reporting
no duplicate production artifact per registry slot
```

Scheduled/manual jobs:

```text
network context-provider tests
long-running RL evaluation
multi-process stress tests
artifact tampering tests
```

---

## 13. Release Gates

### Gate A — Decision Correctness

- Hard risk cannot be overwritten.
- One inference per decision.
- Final action invariants pass.
- No duplicate prediction evidence.

### Gate B — Calibration Validity

- Holdout remains independent.
- Calibration bucket is fixed.
- Metrics and promotion evidence are regenerated.
- Invalid historical reports are tagged.

### Gate C — Artifact Trust

- Every runtime model uses the governed loader.
- Registry, hash, metadata, and schema are verified.
- Direct deserialization is removed.

### Gate D — RL Correctness

- Trade state reset passes.
- Gymnasium semantics pass.
- Existing policies are reassessed.
- Retraining is completed when required.

### Gate E — Concurrency and Evidence

- Registry locking and CAS pass.
- Prediction evidence is transactional.
- Reports are deterministic.
- Audit failure is observable.

### Gate F — Live Reauthorization

- Phase 5 live gate remains PASS.
- Full offline regression is green.
- Shadow validation passes.
- No unresolved P0/P1 issue.
- Manual live authorization is renewed.

---

## 14. Shadow Validation

Recommended configuration:

```env
ML_ENGINE_MODE=SHADOW
ML_CONTEXT_GATE_MODE=SHADOW
ML_ARTIFACT_GOVERNANCE_MODE=ENFORCED
```

Minimum evidence:

```text
>= 100 closed paper trades
>= 30 days
>= 3 symbols
>= 3 regimes
0 hard-risk override violations
0 governance bypasses
0 orphan prediction records
```

Compare:

```text
legacy action
remediated action
raw posterior
adjusted posterior
final risk gate
artifact lineage
actual outcome
```

Promotion requirements:

```text
no increase in critical-risk entries
audit completeness = 100%
no duplicate inference
calibration/Brier not worse
no material latency regression
```

---

## 15. Rollback Plan

Configuration rollback:

```env
ML_ENGINE_MODE=SHADOW
ML_CONTEXT_GATE_MODE=OFF
ML_ADAPTIVE_MODEL_ENABLED=false
```

Artifact rollback:

```text
resolve previous production slot
verify registry/hash/schema
load through governed loader
write rollback event
```

Immediate rollback triggers:

```text
hard-risk violation
artifact governance false-negative
prediction evidence loss
production registry conflict
material decision drift
RL runtime instability
```

---

## 16. Implementation Order

```text
Wave 0  Freeze and baseline
Wave 1  Hard risk gate
Wave 2  Single inference
Wave 3  Calibration correctness
Wave 4  Governed artifact loader
Wave 5  RL environment
Wave 6  Registry concurrency
Wave 7  Transactional evidence
Wave 8  Deterministic time
Wave 9  Structured observability
Wave 10 Architecture consolidation
```

Priority:

```text
P0: Waves 1–4
P1: Waves 5–9
P2: Wave 10
```

---

## 17. Definition of Done

The module is production-ready only when:

```text
hard risk constraints cannot be overwritten
one decision uses one inference
final holdout remains independent
calibration metrics are mathematically correct
all artifact loads are governed
RL state is isolated per trade
Gymnasium contract is correct
registry updates are process-safe
prediction evidence is transactional
time-dependent reports are deterministic
silent failures are observable
shadow validation passes
live authorization is explicitly renewed
```

Expected maturity:

| Milestone | Rating |
|---|---:|
| Current | 6/10 |
| Waves 1–4 | 7.5/10 |
| Waves 5–9 | 8.5/10 |
| Shadow validation | 9/10 |
| Controlled live evidence | 9+/10 |

---

## Final Principle

```text
Model output is advisory.
Governance determines what may run.
Hard safety determines what may trade.
Audit evidence determines what may be trusted.
```
