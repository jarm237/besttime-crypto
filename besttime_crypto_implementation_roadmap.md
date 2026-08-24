# besttime-crypto — Implementation Roadmap After H14 Closeout

## 1. Context and Governance Boundary

H14 is closed and must remain immutable.

```text
H14 Status              CLOSED
Verdict                 RESEARCH_HARD_STOP
Failure Class           INFEASIBLE_RESEARCH_DESIGN
H14.3                   BLOCKED_FINAL
Collection              DISABLED_BY_GOVERNANCE
Activation              NOT_ARMED
Transition              ABSENT
Successor Research      NOT_AUTHORIZED
```

This roadmap does **not** reopen H14.

The next work is split into two chapters:

```text
CHAPTER A — PLATFORM / EXPERIMENTAL SUBSTRATE
P0  Freeze baseline & contracts
P1  EV + decision-gate correctness
P2  Explicit inference contracts
P3  Pure scoring + side semantics
P4  Risk/sizing/gating cleanup
P5  Common live/historical evaluator
P6  Artifact + warm-up + full regression
P7  Governed paper-canary activation
             ↓
      SUBSTRATE_READY
             ↓
CHAPTER B — SUCCESSOR RESEARCH
R0  Research preflight
R1  Candidate implementation
R2  Outcome-blind feasibility replay
R3  A/A shadow
R4  A/B shadow
R5  Freeze prospective contract
R6  Prospective accumulation
R7  Quality unlock — separately authorized
```

---

# Chapter A — Platform / Experimental Substrate

## P0 — Freeze Baseline and Contracts

### Objective

Freeze the current system state before changing runtime behavior so every remediation can prove:

```text
fix intended behavior
AND
no unrelated behavioral drift
```

### Freeze

- Current release SHA.
- Current production artifact hashes.
- Current feature schema and model metadata.
- Current decision contract.
- Current S3 threshold contract.
- Current EV semantics.
- Current targeted-test baseline.
- Current full-suite failure fingerprints.
- Current live/historical parity baseline.
- Current scoring and sizing fixtures.

Also freeze:

```text
live_real_money_allowed = false
H14_reopening_allowed   = false
```

### Deliverables

```text
runtime_remediation_baseline.json
runtime_remediation_contract_v1.md
```

### Exit Gate

```text
P0_BASELINE_FROZEN = PASS
```

---

## P1 — Economic and Final-Decision Correctness

This phase addresses the highest-severity runtime contract issues.

## P1.1 — Normalize Expected Value Units

### Problem

The current system mixes percentage-point and fraction semantics for `expected_return`.

Canonicalize the contract to:

```text
expected_return = fraction

0.0005 = 5 bps
0.0010 = 10 bps
0.0100 = 1%
```

### Requirements

- One canonical internal unit.
- Explicit conversion helpers only at system boundaries.
- No field whose unit changes by caller.
- Version the EV contract.

Recommended helpers:

```python
def fraction_to_bps(value: float) -> float:
    return value * 10_000

def bps_to_fraction(value: float) -> float:
    return value / 10_000
```

### Mandatory Boundary Tests

```text
4.99 bps  → reject
5.00 bps  → exact contract-defined boundary behavior
5.01 bps  → accept

BUY economic EV positive       → eligible for EV gate
SELL economic EV positive      → eligible for EV gate
negative economic EV           → reject
```

---

## P1.2 — Enforce S3 Thresholds in Production

### Objective

Symbol-specific S3 thresholds must be enforced in the actual final-decision path rather than only in replay/parity scripts.

The final decision should receive explicit:

```text
symbol
meta_probability
s3_threshold
s3_pass
threshold_contract_version
```

Example:

```text
symbol           ETHUSDT
meta_probability 0.7900
s3_threshold     0.828073...
s3_pass          false
final_action     IGNORE
```

### Requirements

- Fail closed if threshold cannot be resolved.
- Log threshold, probability and gate result.
- No hidden fallback to global zero thresholds.
- Production and replay must use the same threshold resolver.

### Exit Gate

```text
EV_UNIT_CONTRACT             PASS
S3_RUNTIME_ENFORCEMENT       PASS
DECISION_BOUNDARY_TESTS      PASS
```

No successor research is allowed before P1 passes.

---

# P2 — Explicit Inference Contracts

## P2.1 — Make Symbol an Explicit Input

Remove:

```text
stack inspection
caller-frame inference
mutable current_symbol dependency
```

Target API:

```python
prediction = predict(
    symbol=symbol,
    features=features,
    artifact=artifact,
)
```

### Required Flow

```text
market observation
    ↓
feature generation
    ↓
explicit symbol
    ↓
model inference
    ↓
decision
```

### Required Tests

- BTC/ETH/BNB concurrent inference.
- Async execution does not cross-route symbols.
- Refactors/caller-variable renames do not affect model routing.
- Missing symbol fails closed.

---

## P2.2 — Propagate Artifact Identity

Every prediction should carry:

```text
symbol
artifact_version
artifact_hash
feature_schema_hash
model_family
prediction
```

### Exit Gate

```text
EXPLICIT_SYMBOL_ROUTING      PASS
NO_STACK_ROUTING             PASS
ARTIFACT_IDENTITY_PROPAGATED PASS
CONCURRENCY_TEST             PASS
```

---

# P3 — Pure Scoring and Side Semantics

This is the highest blast-radius refactor and should only begin after P1/P2 are stable.

## P3.1 — Separate Pure Scoring from Orchestration

Target architecture:

```text
CanonicalAnalysis
      ↓
PureSignalScore
      ↓
MetaDecision
      ↓
RiskGate
      ↓
PositionSizing
      ↓
FinalDecision
      ↓
Telemetry / Persistence
```

Target scoring API:

```python
score = score_signal_pure(
    analysis=analysis,
    context=context,
)
```

The pure scorer must not:

```text
write logs
write evidence
call risk manager
mutate model state
perform position sizing
perform order planning
```

Same input + same contract must always return the same result.

---

## P3.2 — Make Context Adjustments Side-Aware

Current scoring axis:

```text
0   = strong SELL
50  = neutral
100 = strong BUY
```

Generic `+x/-x` modifiers are unsafe because the same arithmetic changes BUY and SELL quality in opposite ways.

### Correct Principle

```text
good BUY evidence  → move farther above neutral
bad BUY evidence   → move toward neutral

good SELL evidence → move farther below neutral
bad SELL evidence  → move toward neutral
```

A low-quality signal must not accidentally strengthen the opposite side.

Example:

```text
BUY score = 70
low-quality penalty
→ 55 or neutral-ish

NOT:
70 - 40 = 30
→ accidental SELL
```

### Exit Gate

```text
PURE_SCORING              PASS
SIDE_SYMMETRY             PASS
ONE_SCORING_PASS          PASS
NO_SCORING_SIDE_EFFECT    PASS
```

### Implementation Progress — 2026-08-21

```text
P2_COMMIT_BOUNDARY        PASS
P2 close commit           869b18cb0d59fc6e6153ee7e2731224beb6bac51
P2 tree                   710b195b13dd229120c2e87288e70bb812ede870

SCORING_SURFACE_INVENTORIED    PASS
CURRENT_SCORING_FLOW_MAPPED    PASS
P3_BEHAVIORAL_BASELINE_FROZEN  PASS

PURE_SCORING              PASS
SIDE_SYMMETRY             PASS
ONE_SCORING_PASS          PASS
NO_SCORING_SIDE_EFFECT    PASS

P1_DECISION_REGRESSION_LOCK    PASS
P2_INFERENCE_REGRESSION_LOCK   PASS
NO_NEW_FULL_SUITE_REGRESSION   PASS
RESEARCH_ARTIFACT_INTEGRITY    PASS

P3                        CLOSED
Runtime semantics changed YES — scoring semantics only
Successor research        NOT_AUTHORIZED
Next authorized scope     P4 — Risk, Gating, and Position Sizing
```

Implemented contract and evidence:

- Canonical scorer: `btc_scraper/ml_engine/pure_scoring.py`, contract `pure-scoring/v1`.
- Legacy `score_signal` is now orchestration and invokes the pure scorer exactly once.
- Adjustments are semantic `STRENGTHEN` / `WEAKEN`; weakening clamps at neutral and cannot create the opposite side.
- Pure scorer has no I/O, logging, risk, sizing, order, clock, random, or model-mutation dependency.
- P3 suite: `32/32 PASS`; combined targeted suite: `231/231 PASS`.
- Full suite: `1179/1183 PASS`; the four failures are the unchanged frozen P0/P2 fingerprints, with zero new unrelated failures.
- Closure evidence: `runtime_remediation_p3_report.json`, `runtime_remediation_p3_scoring_manifest.json`, and `runtime_remediation_p3_behavioral_baseline.json`.

Explicit caveats retained:

```text
selected_runtime_release = UNRESOLVED / NOT_APPLICABLE_CURRENTLY
reason = no active runtime/evidence epoch
```

GitNexus post-refresh analysis remained `CRITICAL` and over-attributed direct callers/processes to the new scoring symbols. Source inspection, targeted tests, and the full suite bound the semantic change; the graph relationship anomaly remains recorded in the P3 report and must not be interpreted as substantive changes to execution, fills, ledger, training, risk policy, or sizing policy.

---

# P4 — Risk, Gating, and Position Sizing

## P4.1 — Canonical Non-Actionable Invariant

Enforce:

```text
if final_action in {NEUTRAL, BLOCKED, IGNORE}:
    position_size = 0
```

If risk rejects an otherwise actionable signal:

```text
gated = true
position_size = 0
```

No neutral/fallback state may expose a non-zero tradable size.

---

## P4.2 — Make Sizing Lineage Explicit

Separate fields:

```text
kelly_fraction
raw_position_size
risk_adjusted_size
final_position_size
```

Do not expose `kelly_fraction` as though it determines the final size if another method actually overrides it.

### Exit Gate

```text
NON_ACTIONABLE_SIZE_ZERO  PASS
RISK_REJECTION_GATED      PASS
SIZING_LINEAGE            PASS
KELLY_SEMANTICS           PASS
```

### Implementation Progress — 2026-08-21

```text
P3_COMMIT_BOUNDARY        PASS
P3 close commit           b15a942ce643a49bf79eb1cbe098ffaad6493e65
P3 tree                   8757f5fe2d7123465d62a0e7956f388699ab7719

NON_ACTIONABLE_SIZE_ZERO  PASS
RISK_REJECTION_GATED      PASS
SIZING_LINEAGE            PASS
KELLY_SEMANTICS           PASS

POSITIVE_MINIMUM_SEMANTICS    PASS
ORDER_FINAL_SIZE_BOUNDARY     PASS
P1_DECISION_REGRESSION_LOCK   PASS
P2_INFERENCE_REGRESSION_LOCK  PASS
P3_SCORING_REGRESSION_LOCK    PASS
NO_NEW_FULL_SUITE_REGRESSION  PASS
RESEARCH_ARTIFACT_INTEGRITY   PASS

P4                        CLOSED
Runtime semantics changed YES — risk/gating/final sizing only
Successor research        NOT_AUTHORIZED
Next authorized scope     P5 — Unified Live / Historical Evaluator
```

Implemented contract and evidence:

- Canonical risk/sizing finalizer: `btc_scraper/trading/risk_sizing_contract.py`, contract `risk-sizing/v1`.
- `final_position_size` is authoritative; `position_size` remains only a compatibility alias to that value.
- Non-actionable and risk-rejected decisions expose zero final size; risk rejection is explicitly gated.
- Sizing lineage separates Kelly recommendation, raw size, risk-adjusted size, and final size.
- Positive actionable minimum and maximum constraints remain intact; zero exposure is never raised by a floor.
- The order-planning handoff consumes `EntryDecision.final_position_size`.
- P4 suite: `44/44 PASS`; combined targeted suite: `275/275 PASS`.
- Full suite: `1223/1227 PASS`; the four failures are unchanged frozen fingerprints, with zero new unrelated failures.
- Closure evidence: `runtime_remediation_p4_report.json`, `runtime_remediation_p4_risk_sizing_manifest.json`, and `runtime_remediation_p4_behavioral_baseline.json`.

Explicit caveats retained:

```text
selected_runtime_release = UNRESOLVED / NOT_APPLICABLE_CURRENTLY
reason = no active runtime/evidence epoch
```

GitNexus post-rebuild change detection is `MEDIUM`, while `_process_signal` and `score_signal` retain `HIGH` upstream impact because they are shared production boundaries. The implementation and regression evidence bound P4 to risk/gating/final-sizing semantics; no P5/P6, execution, fills, ledger, or successor-research work is included.

---

# P5 — Unified Live / Historical Evaluator

## Objective

Remove semantic drift between live analysis and historical/backtest analysis.

Target architecture:

```text
Canonical Candle Window
        ↓
evaluate_market()
        ↓
 ┌──────┴────────┐
 ↓               ↓
live adapter     historical adapter
```

Live and historical paths may differ only in:

```text
data source
clock/replay source
persistence adapter
```

They must not differ in decision semantics.

## Required Full-Parity Assertions

Compare at least:

```text
technical state
regime
raw score
final score
meta posterior
eligibility
S3 threshold
S3 gate result
final action
TP
SL
risk gate
position sizing
feature snapshot hash
artifact hash
decision contract hash
```

### Exit Gate

```text
COMMON_EVALUATOR             PASS
LIVE_REPLAY_SIGNAL_PARITY    PASS
LIVE_REPLAY_SCORE_PARITY     PASS
LIVE_REPLAY_DECISION_PARITY  PASS
```

No successor feasibility replay should be trusted before this phase passes.

## Implementation Progress

P5 is closed on the frozen P4 boundary. The production order-planning path and
the canonical historical path now enter the same `EvaluationPipeline` through
thin live and replay adapters. Final eligibility and position sizing each run
exactly once inside that evaluator; `AutoTrader._process_signal` only supplies
runtime state and consumes the resulting entry decision. The legacy bulk
historical evaluator is explicitly non-authoritative and cannot execute.

```text
P4_COMMIT_BOUNDARY                 PASS
P5_FOUNDATION_FROZEN               PASS
COMMON_EVALUATOR                   PASS
COMMON_EVALUATOR_PRODUCTION_REACHABLE PASS
LIVE_REPLAY_SIGNAL_PARITY          PASS
LIVE_REPLAY_SCORE_PARITY           PASS
LIVE_REPLAY_DECISION_PARITY        PASS
ONE_DECISION_PASS                  PASS
ONE_RISK_SIZING_PASS               PASS
CROSS_SYMBOL_ISOLATION             PASS
LEGACY_EVALUATOR_QUARANTINE        PASS
RESEARCH_ARTIFACT_INTEGRITY        PASS

P5                                 CLOSED
Runtime semantics changed          NO — ownership/orchestration unified
Successor research                 NOT_AUTHORIZED
Next authorized scope              P6
```

Verification evidence:

- P5 foundation: `34/34 PASS`.
- Production migration: `7/7 PASS`.
- P1–P5 and decision-path targeted regression: `282/282 PASS`.
- Full suite: `1264/1268 PASS`; the remaining four failures match the frozen
  baseline and no new regression was introduced.
- Research artifact tree hash was restored unchanged after the full suite:
  `7b8f036d19cfa45d2b3412e20504cf5cdbddbbdc04755fc4454cc418f92f20d7`.

Explicit release caveat:

```text
selected_runtime_release = UNRESOLVED / NOT_APPLICABLE_CURRENTLY
reason = no active runtime/evidence epoch
```

Release/artifact selection must become explicit and deterministic before any
remediation is used for a real runtime epoch.

---

# P6 — Artifact, Schema, Warm-Up, and Regression Closure

## P6.1 — Correct Artifact Metadata and Registry Lineage

Every production model artifact must accurately describe:

```text
model version
model family
actual feature count
feature schema
training contract
calibration contract
artifact hash
```

Requirements:

- No stale `v3.1 / 43-feature` metadata for a V5 4-feature model.
- Registry updates go through the canonical registry API.
- Avoid duplicate archive records created by direct mutation.
- Runtime must verify artifact/schema compatibility before inference.

---

## P6.2 — Freeze Warm-Up Contract

Directional inference must be forbidden until required history is available.

Example:

```text
required_history =
max(
    SMA200 lookback,
    ADX lookback,
    ATR lookback,
    feature-specific lookbacks,
    MTF requirements
)
```

If incomplete:

```text
warmup_complete = false
action          = NEUTRAL
position_size   = 0
gated           = true
```

---

## P6.3 — Full Regression Closure

Before declaring the substrate ready:

```text
targeted suite      PASS
full suite          PASS
git diff --check    PASS
determinism         PASS
parity suite        PASS
```

Known stale fixtures must be corrected to the frozen contract, not hidden with `xfail`.

## P6 Implementation Progress

```text
P6-G0 BASELINE PIN                 PASS
P6-G1 CONTRACT INVENTORY           PASS
P6 ARTIFACT/SCHEMA/WARMUP FOUNDATION PASS
P6-PROV PROVENANCE RECOVERY        PROVENANCE_RECOVERED
P6-PRE-PD0 BASELINE DETERMINISM    CLOSED
P6-PROV-DATA                       DATASET_PROVENANCE_RECOVERED
P6-G2 ARTIFACT CONTRACT CLOSURE    PASS
P6-G3 SCHEMA CONTRACT CLOSURE      PASS
P6-G4 WARM-UP/READINESS CLOSURE    PASS
P6-G5 REGRESSION CLOSURE           PASS
P6                                 CLOSED
```

The canonical `meta_model` wrapper is byte-reproducible and its model/scaler
parameters reproduce exactly from the V5 D2 source. Its sidecar `v3.1 / 43f`
identifiers are classified as `LEGACY_UNVERIFIED_METADATA`; calibration is
proven not applicable because the frozen model uses direct `LogisticRegression`
probabilities without an embedded or external calibrator.

P6-PROV-DATA recovered immutable training-dataset identity. A git-anchored
historical manifest at commit `5550d408473885c0a79d0815ea2ed42f8db100cc`
records the exact raw SHA256 values for the BTC/ETH/BNB CSVs used by the V5
candidate consumer. The V5 training path was then reconstructed from those
candidate files, producing exact model and preprocessing parameters and a
deterministic recovered training-matrix identity. The producer remains a live
Binance historical API path, but producer reconstruction is no longer the
identity anchor because raw CSV identity is proven by the historical manifest.

P6-G2 is closed. The immutable compatibility manifest at
`config/artifact_compatibility/meta_model.compatibility.json` pins the
canonical artifact SHA, 4-feature ordered schema, recovered D3 dataset
identities, observed V5 wrapper metadata, per-symbol preprocessing contract,
and `PROVEN_NOT_APPLICABLE` calibration contract. `GovernedArtifactLoader`
now validates the manifest and artifact identity before production `meta_model`
inference can proceed; incompatible artifacts surface explicitly as
`INCOMPATIBLE_ARTIFACT`, never as HOLD/NEUTRAL/warm-up substitution.

G2R regression evidence: focused artifact compatibility `19/19 PASS`, P6
foundation plus G2R `25/25 PASS`, P5/P6 focused `56/56 PASS`,
AutoTrader/probability `26/26 PASS`, seal-critical expanded `103/103 PASS`,
P1-P5 targeted `147/147 PASS`, and full suite returns the exact four approved
frozen failures with zero new failures. The full-suite JUnit is
`/tmp/besttime-p6-g2r-full.xml` with SHA256
`8ff916c7b7d35b089bac4c2ec0d41ef0ddfd79db70818c6133078b6282af66d6`.

P6-G3 is closed. Runtime schema contracts now explicitly define the canonical
candle/window boundary and the production `meta_model` 4-feature vector:
`return_8`, `return_32`, `return_72`, `abs_move_72`. The model feature-vector
schema fingerprint is
`408a240e4e502100191dcd7cb488cea064e0187149b65e15df174ec703d31770`; its
feature-order hash is
`b866c5e78d7f6f02cb74fe52cbe1d8a5f69752d60acc2c5fe2e5ddf6e5fbc0dc`, matching
the G2 artifact manifest order identity. `predict_meta_confidence` now validates
that canonical features are present and finite before calling model inference;
missing/malformed schema returns an explicit pre-inference failure and does not
invoke inference, scoring, decision, or sizing.

G3 regression evidence: G3 focused plus P2 smoke `30/30 PASS`, P6/G2/G3
`37/37 PASS`, P5/P6/G3 plus non-evidence smoke `83/83 PASS`,
AutoTrader/probability `26/26 PASS`, seal-critical expanded `103/103 PASS`,
P1-P5 targeted `147/147 PASS`, and full suite returns the exact four approved
frozen failures with zero new failures. The full-suite JUnit is
`/tmp/besttime-p6-g3-full.xml` with SHA256
`71478be9e45daa288f98516352054f26b0d662485a671db4b423ea24cc7b8b38`.

P6-G4 is closed. Runtime readiness is now an explicit pre-semantic contract:
the canonical 15m model path derives its required history from the actual V5
feature dependencies (`return_8`, `return_32`, `return_72`, `abs_move_72`),
where the 72-bar dependency requires 73 completed observations. `READY` is
emitted only for structurally valid, contiguous, closed, point-in-time windows
with sufficient canonical history. Short-but-valid windows return
`WARMING_UP`; gaps, duplicate/out-of-order observations, partial candles, and
future observations return explicit `INVALID_INPUT` diagnoses. The common
live/replay evaluator runs this readiness gate before technical/features,
inference, scoring, decision, or sizing, and the production live/historical
entrypoints use the same canonical contract. `WARMING_UP` is not substituted
with HOLD/NEUTRAL and does not create an economic decision.

G4 regression evidence: baseline full suite returned the exact four approved
frozen failures with zero new failures; the baseline JUnit is
`/tmp/besttime-p6-g4-baseline-full.xml` with SHA256
`5176650a1d18499fce20ed737d304b1e7653337a7985f72a51f0608bb42f3c82`.
Focused G4/P5/P6 readiness coverage is `72/72 PASS`, P5/P6/G4 plus artifact,
schema and non-evidence smoke is `99/99 PASS`, seal-critical expanded is
`119/119 PASS`, P1-P5 targeted is `150/150 PASS`, the portfolio sizing fixture
correction is `1/1 PASS`, and the post-change full suite returns the same exact
four frozen failures with zero new failures. The post-change full-suite JUnit is
`/tmp/besttime-p6-g4-full.xml` with SHA256
`1471164b86a9102404c17b042e05550fee1964f3c41aea26a699b3a90a35529b`. The
detailed evidence report is `runtime_remediation_p6_g4_readiness_report.json`.

P6-G5 is closed. Regression closure now freezes the exact four full-suite
baseline failure identities from `/tmp/besttime-p6-g4-full.xml` rather than
checking only failure count. The frozen baseline is recorded in
`runtime_remediation_p6_g5_regression_baseline.json`, and
`scripts/compare_p6_g5_junit.py` compares node identity, failure category, and
stable signatures while ignoring volatile traceback details. G5 also adds
contract-composition tests that lock precondition precedence before readiness,
assert no downstream calls on artifact/schema/readiness failure, verify the
0/1/8/9/32/33/71/72/73/74/100 readiness matrix, lock completed-candle
semantics, and prove live/replay parity and determinism at the first ready
point.

G5 regression evidence: focused G5/P6/P5 suite `116/116 PASS`
(`/tmp/besttime-p6-g5-focused.xml`, SHA256
`523bab30cd198751ea9aaed551d27e37827e96c2b4e473b4ec5f07e8b4bbb798`);
seal-critical expanded `136/136 PASS` (`/tmp/besttime-p6-g5-seal-critical.xml`,
SHA256 `135ad6dfa5e2ac86141aeb30e55c353f588038b2efe358b4e51238e7d82df38e`);
P1-P5 targeted `150/150 PASS` (`/tmp/besttime-p6-g5-p1-p5.xml`, SHA256
`1dab800c848a0aebae5cb38c5dd96bd6fdac592b6be801202e731e74b9680f4e`);
portfolio fixture regression `1/1 PASS` (`/tmp/besttime-p6-g5-portfolio.xml`,
SHA256 `995e3c6fc749766488e65403123ce37c86571daca8208e8cc0030bea36360c7f`);
and full suite returns the same exact four frozen failures with zero new or
replacement failures (`/tmp/besttime-p6-g5-full.xml`, SHA256
`b76ad35ba66601b03dd8bd71a30c4a74d5dfd8caed2b1bf4ac61ea0eba5392e4`).
The full-suite comparison artifact is
`/tmp/besttime-p6-g5-full-comparison.json` with status `PASS`. The detailed
closure report is `runtime_remediation_p6_g5_regression_report.json`.

A trial fail-closed integration correctly exposed four P1–P5 fixture/runtime
contract gaps. Per stop condition SC-4, those integration edits were rolled
back and the affected P5/canary/AutoTrader regression set returned to
`98/98 PASS`.

P6-PRE-PD0 closed an accidental seal-baseline dependency on ambient MongoDB
risk availability. The affected AutoTrader and probability-contract tests now
declare deterministic risk state at the test boundary, while a dedicated
fail-closed test preserves `risk DB unavailable -> NEUTRAL + position size 0`.
The expanded seal-critical set is `103/103 PASS` with Mongo unavailable, and
full-suite status is back to the exact four frozen failures with no new
regressions.

The reusable P6 contract foundation is now production-authoritative for the
closed G2/G3/G4 boundaries: artifact compatibility, canonical schema, and
canonical 15m readiness. P6 regression closure is sealed by G5; P6 is closed.

```text
selected_runtime_release = UNRESOLVED / NOT_APPLICABLE_CURRENTLY
reason = no active runtime/evidence epoch
successor research = NOT_AUTHORIZED
```

---

# P7 — Governed Paper-Canary Activation

## P7 Implementation Progress

```text
P7-G0 SCOPE & SEAL-POINT FREEZE          PASS
P7-G1 RUNTIME RELEASE RESOLUTION         PASS
P7-G2 ARTIFACT/RUNTIME CONTRACT          PASS
P7-G3 DEPLOYMENT MANIFEST                PASS
P7-G4 PINNED RUNTIME ENVIRONMENT         PASS
P7-G5 ACTIVATION PREFLIGHT               PASS
P7-G5A SAFE LAUNCHER CONTRACT            PASS
P7-G6 ACTIVATION AUTHORIZATION FREEZE    ARMED_CONSUMED
P7-G7 CONTROLLED PAPER-CANARY START      PASS_SPAWNED_ONCE
P7-G8 POST-START READ-BACK               PASS_ACTIVE_IMMEDIATE_NOT_SUSTAINED
P7-R1 EARLY CHILD EXIT FORENSICS         PASS_OPERATIONAL_PRECONDITION
P7-R2 EVIDENCE EPOCH PROVISIONING        PASS_OPERATIONAL_STATE_PROVISIONED
P7-R3 POST-EPOCH STARTUP EXIT FORENSICS  PASS_OBSERVABILITY_GAP_CLASSIFIED
P7-R3A SUPERVISED EXIT OBSERVABILITY     PASS_SUPERVISED_EXIT_OBSERVABILITY
P7-G6#3 FRESH PREFLIGHT                  PASS_READY_FOR_G6_AUTHORIZATION_3
P7-G6#3 AUTHORIZATION                    CONSUMED_FAILED
P7-G7#3 CONTROLLED SUPERVISED START      PASS_SPAWNED_ONCE
P7-G8-A IDENTITY ESTABLISHMENT           PASS_IDENTITY_ESTABLISHED
P7-G8-B SUSTAINED SEMANTIC LIVENESS      FAIL_NOT_SUSTAINED
P7-R4 UNSUPPORTED RUNTIME SYMBOL         PASS_FORENSICS_PREFLIGHT_GATE_ADDED
P7-G9 FIRST-CYCLE SEMANTIC VALIDATION    BLOCKED_NOT_ACTIVE
P7-G10 OBSERVATION HANDOFF               BLOCKED_NOT_ACTIVE
P7                                     BLOCKED_AFTER_ACTIVATION_ATTEMPT_3
```

P7 has pinned the runtime release to the P6 canonical seal:

```text
release_commit = 5e8d798e4d06d6abd21ade99c79caaa93307dd5b
release_tree   = 48ef10b27488468d294a5e223cb95a4aebfc3f01
source         = P6_CANONICAL_SEAL
```

The pinned worktree is `runtime/worktrees/pinned-5e8d798`, verified at the
release commit/tree with a clean worktree. The current runtime artifact bytes
were provisioned into that pinned worktree without regeneration:
`logs/meta_model.joblib` SHA256
`dbf0a08241dae01241539ef3f48c6a0b13da9b13a5b128de259aac06d267241c`.

P7 preflight verified pinned imports resolve from the pinned worktree, the
canonical 4-feature vector is exactly `return_8`, `return_32`, `return_72`,
`abs_move_72`, readiness returns `WARMING_UP` at 72 completed 15m observations
and `READY` at 73, and explicit inference smoke returns a bounded prediction
for `BTC` from the pinned artifact. The deployment manifest is
`runtime_activation_p7_manifest.json` with SHA256
`9140dc0c501349988aae1ff9547e671517f3253545344c506567df56c4c88894`.

P7 remains deliberately not armed, but the activation-mechanics blocker has
been closed by P7-G5A. The existing `scripts/activate_v5_canary.py` remains
disqualified for governed P7 activation because it mutates
`logs/meta_model.joblib`, `logs/meta_model.json`, `logs/model_registry.json`,
and deletes/recreates a fixed evidence epoch. That would violate P7's
no-retraining/no-artifact-regeneration/no-implicit-activation boundary.

P7-G5A introduced an external governance launcher,
`scripts/p7_safe_paper_canary_launcher.py`, with contract
`paper-canary-launcher/v1` and SHA256
`1d6fe208a6c527529be71fa1216f78ed51f3e24db893838ad45616c6797a1f90`. The
launcher consumes the frozen P7 manifest and pinned runtime worktree, validates
release/artifact/manifest/registry identity, enforces paper-only child
environment, blocks duplicate runner/deployment/epoch state, and permits only
deployment-specific operational writes. It does not mutate canonical inputs.
Validate-only evidence is `/tmp/p7-g5a-launcher-validate.json` with SHA256
`e8619312a8044103b8938a9aa246bb68406955db0c3fbdd3dea9b460cd6879b4`, and the
launcher contract tests are `14/14 PASS`.

The current status is therefore:

```text
ready_to_arm           false
activation_authorized  consumed_success_attempt_2
runtime_activation     NOT_SUSTAINED_AFTER_G8
paper_canary           NOT_ACTIVE
real_money_production  NOT_AUTHORIZED
successor_research     NOT_AUTHORIZED
```

P7-G6 authorization is implemented as a read-only snapshot generator,
`scripts/p7_g6_authorization_snapshot.py`, with tests in
`tests/ml/test_p7_g6_authorization_snapshot.py`. The generator re-verifies the
governance checkout identity, pinned runtime identity, immutable input hashes,
process-conflict snapshot, paper-only child argv/env, and launcher
`--validate-only` before writing a canonical
`runtime_activation_p7_g6_authorization.json` plus `.sha256` sidecar. It does
not call `launch()` and must not spawn a child process.

Important governance nuance: the authorization artifact binds to the current
governance `HEAD` and tree. Therefore the tooling/roadmap checkpoint is
committed first, and the G6 authorization artifact is generated after that
commit. Committing the generated authorization artifact would change
governance `HEAD` and make that authorization stale; it is operational
evidence for the next P7-G7 launch seam rather than a runtime-release change.

P7-G7 consumed authorization SHA256
`6978972d7b026598cf82a4f4bc0949ded78464430cabfc0bf960755507bfb150` exactly
once. The launcher returned `SPAWNED` with child PID `611136`, spawn attempts
`1`, automatic retries `0`, and immutable runtime inputs unchanged. G7 evidence
is `runtime_activation_p7_g7_invocation.json` with SHA256
`9dfc0ccdff14eedbac4b731200394f905a09949af5d4c0b64f5d96443da3e661`.

P7-G8 authoritative read-back found `active_runner_count = 0`; the child had
already exited by read-back time. Immutable inputs remained unchanged and no
second launch was attempted. The resulting decision-matrix verdict is
`ACTIVATION_FAILED`, with `runtime_activation = NOT_ESTABLISHED` and
`paper_canary = NOT_ACTIVE`. G8 evidence is
`runtime_activation_p7_g8_readback.json` with SHA256
`2cf2341b3994275ebe146943ac318f60fda9646ca32f94dd59d5adb27bc7240c`.

Observed operational state from the pinned runtime shows the child acquired and
released the paper runtime lock for deployment `paper-canary-20260824-01`
within the same startup attempt. No retry is authorized under the consumed G6
authorization. The next valid step is forensic/remediation planning followed by
a new G6 authorization if another attempt is desired.

P7-R1 completed the early child-exit forensic classification without a second
runtime activation. Attempt #1 is frozen as non-retriable and authorization
`6978972d7b026598cf82a4f4bc0949ded78464430cabfc0bf960755507bfb150` remains
permanently `CONSUMED`.

R1 startup timeline:

```text
T0 launcher invoked                         CONFIRMED
T1 validation PASS                          CONFIRMED
T2 spawn syscall succeeded                  CONFIRMED
T3 child PID existed transiently            CONFIRMED_TRANSIENT
T4 Python entrypoint entered                INFERRED
T5 runtime lock acquisition attempted       INFERRED
T6 runtime lock acquired                    CONFIRMED
T7 runtime evidence epoch setup             FIRST_FAILED_OR_REJECTED_STAGE
T8 runtime pause state initialized          NOT_REACHED
T9 async_main entered                       NOT_REACHED
T10 sustained scheduler loop entered        NOT_REACHED
T11 lock released                           CONFIRMED
T12 process exited                          CONFIRMED
T13 G8 observed runner_count = 0            CONFIRMED
```

The failure class is:

```text
failure_class                 STARTUP_PRECONDITION_REJECTION
remediation_boundary          OPERATIONAL
runtime_release_change_needed false
P6 seal                       REMAINS_APPLICABLE
P7-G5A safe launcher          REMAINS_PASS
```

Supporting evidence: pinned `main.py` acquires `RuntimeLock`, then calls
`get_runtime_evidence_store().assert_runtime_epoch_ready(require_active=
runtime_evidence_eligible())` before `asyncio.run(async_main())`. The G7 child
environment set `BTC_EVIDENCE_ELIGIBLE=true`, making an ACTIVE runtime evidence
epoch mandatory. The paper deployment logs contain no runtime evidence SQLite
partition/ACTIVE epoch, while the runtime lock was acquired and released within
the same startup attempt. This places the first failed/missing stage before
`async_main()` and before the scheduler loop, not in model artifact loading,
decision semantics, or launcher immutability.

R1 evidence:

```text
runtime_activation_p7_r1_startup_timeline.json
sha256 = 9948ac1f95619fd88b0bbb9e08ccdc70bf6c9fbf901b21afaae23d563f60e698

runtime_activation_p7_r1_failure_classification.json
sha256 = a231d56a3697dd19903d34571da9273b9be082e91815ae8833cb4a94e8ee053f

runtime_activation_p7_r1_remediation_report.json
sha256 = c25cda589d593e41eb80e3e4fd5a5ddc7875161df21c19f45c481040e745c983
```

P7-R2 provisioned the deployment-specific ACTIVE evidence epoch required by
pinned `main.py` when `BTC_EVIDENCE_ELIGIBLE=true`. The remediation used the
pinned runtime release modules from `runtime/worktrees/pinned-5e8d798` and
wrote only deployment-specific operational evidence state:

```text
runtime/paper/paper-canary-20260824-01/logs/global_evidence_index.sqlite
runtime/paper/paper-canary-20260824-01/logs/runtime_evidence_2026-08-24.sqlite
```

R2 authoritative read-back:

```text
evidence_epoch                      ACTIVE
active_epoch_count                  1
epoch_id                            canary-p6-sealed-v1-20260824-01
deployment_id                       paper-canary-20260824-01
paper_run_id                        paper-canary-20260824-01
runtime_release                     5e8d798e4d06d6abd21ade99c79caaa93307dd5b
runtime_release_tree                48ef10b27488468d294a5e223cb95a4aebfc3f01
artifact_sha256                     dbf0a08241dae01241539ef3f48c6a0b13da9b13a5b128de259aac06d267241c
execution_mode                      PAPER
evidence_eligible                   true
startup_precondition_probe          PASS
immutable_inputs                    UNCHANGED
runtime_activation                  NOT_PERFORMED_AFTER_R2
```

R2 did not change the pinned runtime source, the manifest, the artifact, the
artifact sidecar, the model registry, thresholds, schema, or policy. P6 remains
applicable and P7-G5A remains PASS. The old authorization remains consumed and
cannot be reused.

R2 evidence:

```text
runtime_activation_p7_r2_dry_run_report.json
sha256 = 9909b1e6ac3b8471ae09090bc5d2ba33ff9fb8fe4a2fc746401728053582992c

runtime_activation_p7_r2_provisioning_report.json
sha256 = f4b2527f760edfee0eaa730a7f17d1a2a0e534b7001ee63080475037c8a3a186
```

Any second activation attempt still requires a fresh P7 preflight and a new G6
authorization SHA.

Fresh preflight and controlled activation attempt #2 completed after R2. The
attempt #2 preflight proved the intended delta from attempt #1 was limited to
the ACTIVE evidence epoch remediation:

```text
attempt_1 active evidence epoch       absent
attempt_1 startup precondition        FAIL
attempt_1 result                      ACTIVATION_NOT_ESTABLISHED

attempt_2 active evidence epoch       present
attempt_2 startup precondition        PASS
attempt_2 active runner before launch 0

unchanged                             runtime release, runtime tree, artifact,
                                      sidecar, registry, manifest, launcher,
                                      execution_mode = PAPER
```

G6 authorization #2 was generated as a distinct single-use authorization:

```text
authorization_sha256 =
22792ca76f119230e5f3ee8c9de77caec6b41a46733111bc36c8d31d10ed73a8

activation_attempt = 2
spawn_budget       = 1
automatic_retry    = false
previous_attempt   = ACTIVATION_NOT_ESTABLISHED
```

G7 attempt #2 consumed that authorization exactly once. The launcher returned
`SPAWNED` with child PID `839623`, spawn attempts `1`, and automatic retries
`0`. Immediate G8 authoritative read-back found:

```text
active_runner_count        1
runner_pid                 839623
epoch_identity             PASS
runtime_identity           PASS
immutable_inputs           UNCHANGED
decision_matrix_verdict    ACTIVATION_PASS
runtime_activation         ACTIVE
paper_canary               ACTIVE
```

The active runner command is the pinned release entrypoint:

```text
/home/tran-huynh/Workspaces/Personal/besttime-crypto/.venv/bin/python
/home/tran-huynh/Workspaces/Personal/besttime-crypto/runtime/worktrees/pinned-5e8d798/main.py
```

No G9 synthetic cycle was run. The next valid gate is P7-G9: observe the first
natural scheduler cycle and validate lineage/readiness/decision semantics.

However, the post-G8 liveness check before checkpoint commit found PID `839623`
was no longer active. Runtime lock events show attempt #2 acquired and released
the paper runtime lock:

```text
runtime_id = 20260824T064257Z-839623
lock_acquired_at = 2026-08-24T06:43:09.500367+00:00
lock_released_at = 2026-08-24T06:43:09.510542+00:00
```

Therefore the refined activation state is:

```text
immediate_g8_verdict        ACTIVATION_PASS
post_g8_liveness            ACTIVATION_NOT_SUSTAINED_AFTER_G8
current_active_runner_count 0
runtime_activation          NOT_SUSTAINED_AFTER_G8
paper_canary                NOT_ACTIVE
authorization_2             CONSUMED_FAILED
```

This proves R2 crossed the attempt #1 blocker, because the ACTIVE epoch
precondition passed and the child reached runtime lock acquisition. The new
failure is later in startup lifecycle, after the evidence epoch gate. Do not
retry authorization #2. The next valid gate is P7-R3 post-epoch startup exit
forensics.

Evidence artifacts:

```text
runtime_activation_p7_release.json
runtime_activation_p7_manifest.json
runtime_activation_p7_preflight.json
runtime_activation_p7_readback.json
runtime_activation_p7_first_cycle.json
runtime_activation_p7_report.json
runtime_activation_p7_g5a_launcher_report.json
runtime_activation_p7_g6_authorization.json
runtime_activation_p7_g6_authorization.json.sha256
runtime_activation_p7_g7_invocation.json
runtime_activation_p7_g7_invocation.json.sha256
runtime_activation_p7_g8_readback.json
runtime_activation_p7_g8_readback.json.sha256
runtime_activation_p7_r1_startup_timeline.json
runtime_activation_p7_r1_startup_timeline.json.sha256
runtime_activation_p7_r1_failure_classification.json
runtime_activation_p7_r1_failure_classification.json.sha256
runtime_activation_p7_r1_remediation_report.json
runtime_activation_p7_r1_remediation_report.json.sha256
runtime_activation_p7_r2_dry_run_report.json
runtime_activation_p7_r2_dry_run_report.json.sha256
runtime_activation_p7_r2_provisioning_report.json
runtime_activation_p7_r2_provisioning_report.json.sha256
runtime_activation_p7_attempt2_preflight_delta.json
runtime_activation_p7_attempt2_preflight_delta.json.sha256
runtime_activation_p7_attempt2_preflight.json
runtime_activation_p7_attempt2_preflight.json.sha256
runtime_activation_p7_g6_attempt2_authorization.json
runtime_activation_p7_g6_attempt2_authorization.json.sha256
runtime_activation_p7_g7_attempt2_invocation.json
runtime_activation_p7_g7_attempt2_invocation.json.sha256
runtime_activation_p7_g8_attempt2_readback.json
runtime_activation_p7_g8_attempt2_readback.json.sha256
runtime_activation_p7_attempt2_report.json
runtime_activation_p7_attempt2_report.json.sha256
runtime_activation_p7_attempt2_post_g8_liveness.json
runtime_activation_p7_attempt2_post_g8_liveness.json.sha256
```

The next authorized step is not another launch. Authorization #2 is consumed.
The next step is P7-R3 post-epoch startup exit forensics. Do not force a
synthetic cycle, lower thresholds, inject a trade, or retry without a new
forensic/remediation gate and fresh G6 authorization.

P7-R3 completed post-epoch startup exit forensics without a restart and without
minting or consuming authorization #3. Attempt #2 remains frozen as
`CONSUMED_FAILED`.

R3 refined startup trace:

```text
T0 launcher validation and spawn           CONFIRMED
T1 immediate G8 active runner identity     CONFIRMED
T2 post-G8 active runner count             0 CONFIRMED
T3 runtime lock acquired                   CONFIRMED
T4 runtime lock released                   CONFIRMED
T5 ACTIVE epoch gate                       INFERRED_PASSED
T6 pause policy construction               PASS_ISOLATED_PROBE
T7 RuntimePauseController init             PASS_ISOLATED_PROBE
T8 RuntimePauseController.mark_running     PASS_ISOLATED_PROBE
T9 runtime_pause_state persisted attempt2  MISSING
T10 async_main entered                     UNOBSERVED
T11 scheduler loop sustained               NOT_CONFIRMED
```

The critical R3 finding is that the post-R2 ACTIVE epoch blocker from R1 was
crossed, but the attempt #2 evidence does not include child stdout, stderr,
exit code, or stage-level startup markers. A temporary-root pinned-release
probe using copied attempt #2 evidence databases passed
`assert_runtime_epoch_ready`, `RuntimePausePolicy.from_mapping`,
`RuntimePauseController` initialization, and `mark_running` persistence. That
means current evidence is insufficient to assign a specific runtime-code root
cause to the child exit.

R3 classification:

```text
failure_class                 OBSERVABILITY_GAP_AFTER_ACTIVE_EPOCH
remediation_boundary          TOOLING_OBSERVABILITY
runtime_release_change_needed false
P6 seal                       REMAINS_APPLICABLE
P7-G5A safe launcher          REMAINS_PASS
authorization_2               CONSUMED_FAILED
authorization_3               NOT_AUTHORIZED
runtime_activation            NOT_SUSTAINED_AFTER_G8
paper_canary                  NOT_ACTIVE
```

Unsupported claims remain explicitly blocked:

```text
specific runtime exception caused exit     UNSUPPORTED
async_main failed before scheduler         UNSUPPORTED
scheduler loop failed after entry          UNSUPPORTED
artifact/decision/threshold caused exit    UNSUPPORTED
```

Before any third activation attempt, P7 requires a new observability seam,
`P7-R3A SUPERVISED EXIT OBSERVABILITY`, that captures child stdout, stderr,
exit code, and stage-level startup markers, and separates immediate identity
read-back from a sustained-liveness window. Only after that seam passes may a
fresh preflight and new single-use P7-G6 authorization #3 be considered.

R3 evidence:

```text
runtime_activation_p7_r3_startup_trace.json
sha256 = ad66e155d8c7b1e7a4bec66efda8760e9c49ee79adef62201f8f42a606f2a1b7

runtime_activation_p7_r3_failure_classification.json
sha256 = b5864639967bb0b09aee71d1b5de9501b905983f6960baa22a6ab162aa4cd01f

runtime_activation_p7_r3_remediation_report.json
sha256 = 6a46e0f2cdb26556145ed1312d79b2c6ff365223d7bb87b9028b8facb8658d71
```

P7-R3A closed the observability gap identified by R3 without changing pinned
runtime semantics and without launching attempt #3. The new supervisor is
external governance tooling, `scripts/p7_r3a_supervised_child.py`, with
contract `p7-supervised-child/v1` and SHA256
`d9f012bce258483cd54894d0b0d18734c122c0de0e1ffeb67eda08ef971183ea`.

R3A supervision contract:

```text
spawn_budget        1
restart_budget      0
automatic_retry     false
stdout_capture      direct_file_redirection
stderr_capture      direct_file_redirection
exit_code_capture   true
signal_capture      true
lifecycle_timestamps true
startup_stage_model external_observation_only
real_runtime_spawn_count 0
```

R3A also splits the old G8 read-back into:

```text
G8-A Identity Establishment
  child spawned exactly once
  expected PID/runtime identity observed
  expected epoch/deployment/release/artifact observed
  immutable inputs unchanged

G8-B Sustained Liveness
  semantic progress marker required
  transient process survival is not sufficient
```

Attempt #2 is therefore retained historically as:

```text
immediate G8 identity        PASS
retrospective G8-A           PASS
retrospective G8-B           FAIL
overall                      ACTIVATION_NOT_SUSTAINED
```

It is not rewritten into a simple G8 failure, because the race between identity
establishment and sustained liveness is the important finding.

R3A validation:

```text
R3A supervisor dummy matrix        12/12 PASS
P7 seal-critical regression subset 32/32 PASS

clean exit 0                       PASS
nonzero exit                       PASS
uncaught exception stderr capture  PASS
SIGTERM classification             PASS
fast-exit race capture             PASS
long-running child observation     PASS
large stdout/stderr capture        PASS
exact argv/env preservation        PASS
no retry                           PASS
no restart                         PASS
transient G8 not ACTIVE            PASS
sustained semantic progress ACTIVE PASS
```

Immutable runtime verification after R3A:

```text
runtime_release_head  5e8d798e4d06d6abd21ade99c79caaa93307dd5b
runtime_release_tree  48ef10b27488468d294a5e223cb95a4aebfc3f01
manifest_sha256       9140dc0c501349988aae1ff9547e671517f3253545344c506567df56c4c88894
artifact_sha256       dbf0a08241dae01241539ef3f48c6a0b13da9b13a5b128de259aac06d267241c
runtime_lock_events   unchanged at 4 lines
active_pinned_runner  0
authorization_3       NOT_CREATED
attempt_3             NOT_AUTHORIZED
paper_canary          NOT_ACTIVE
```

R3A evidence:

```text
runtime_activation_p7_r3a_observability_contract.json
sha256 = e574bcecdbdfb2ecc87266cab3216beccb65d872fd158567e395eacdbe29c8b0

runtime_activation_p7_r3a_observability_report.json
sha256 = 08a4866efd0fc796dfea9f421ddef18edc38f8e8bc3dc1ff13ea7400aec3ef3e
```

The next valid step is not G7. It is fresh P7 preflight #3, which must add:

```text
OBSERVABILITY_SUPERVISOR_READY
STDOUT_CAPTURE_READY
STDERR_CAPTURE_READY
EXIT_STATUS_CAPTURE_READY
SIGNAL_CAPTURE_READY
G8_SUSTAINED_LIVENESS_CONTRACT
```

Only after those gates pass may a new single-use P7-G6 authorization #3 be
generated. Authorization #1 and #2 remain consumed.

Fresh preflight #3 completed read-only and is bound to the R3A governance seal:

```text
governance_commit = a8358102b8ec18557e14fd547397acd224c41961
governance_tree   = c68fde9ccfa3f4a7ed9ec1fb18f80a47cec15dd8
```

The preflight did not create authorization #3 and did not spawn a runtime.

Preflight #3 result:

```text
verdict             PASS_READY_FOR_G6_AUTHORIZATION_3
authorization_3     NOT_CREATED
runtime_spawn_count 0
paper_canary        NOT_ACTIVE
runtime_runner      NONE
```

Gate results:

```text
governance_identity       PASS
runtime_release           PASS
immutable_inputs          PASS
evidence_epoch            PASS
startup_precondition      PASS
runtime_conflict          PASS
safe_launcher             PASS
r3a_supervisor_readiness  PASS
attempt3_evidence_paths   PASS
g8_a_contract             PASS
g8_b_contract             PASS
attempt2_regression       PASS
```

G8-B semantic liveness for attempt #3 is explicitly bound to the strongest
existing runtime semantic marker: `RuntimePauseController.heartbeat()` persisted
to runtime pause state/events after scheduler loop entry. This is not an
arbitrary process-survived-N-seconds gate. G8-A remains identity establishment
only and cannot mark `runtime_activation = ACTIVE` by itself.

Attempt #3 evidence paths are predeclared and non-colliding:

```text
runtime/worktrees/pinned-5e8d798/runtime/paper/paper-canary-20260824-01/
  activation_attempt_3/
    child.stdout.log
    child.stderr.log
    supervision.json
    g8_identity_readback.json
    g8_liveness_readback.json
```

Preflight #3 evidence:

```text
runtime_activation_p7_attempt3_preflight.json
sha256 = 3a7b239460fb2d8836576e2cd7fbc135e6285561110213dc9eed00e771ae6f9a
```

The next valid seam is to mint P7-G6 authorization #3 as a separate
single-use authorization bound to the R3A governance commit/tree, pinned runtime
release, launcher SHA, supervisor SHA, manifest/artifact hashes, ACTIVE epoch,
attempt #3 evidence paths, G8-A/G8-B contracts, `spawn_budget = 1`,
`restart_budget = 0`, and `automatic_retry = false`. Do not combine
authorization minting with G7 launch.

P7-G6 authorization #3 was minted and consumed by exactly one supervised
activation attempt. The activation plumbing worked: the child spawned once,
acquired the runtime lock, and passed G8-A identity establishment. G8-B failed
because no persisted `RuntimePauseController.heartbeat()` was observed before
the child exited.

Attempt #3 final state:

```text
authorization_3        CONSUMED_FAILED
P7-G7#3                PASS_SPAWNED_ONCE
P7-G8-A                PASS_IDENTITY_ESTABLISHED
P7-G8-B                FAIL_NOT_SUSTAINED
runtime_activation     NOT_ACTIVE
paper_canary           NOT_ACTIVE
spawn_attempt_count    1
restart_count          0
automatic_retry        0
immutable_inputs       UNCHANGED
P7-G9                  BLOCKED_NOT_ACTIVE
P7-G10                 BLOCKED_NOT_ACTIVE
```

The concrete startup exception captured by supervised stderr was:

```text
RuntimeError: inference_symbol_unsupported:SOL
```

P7-R4 traced this from the pinned runtime release:

```text
DEFAULT_ANALYSIS_UNIVERSE
  -> main.RUNTIME_UNIVERSE.analysis_symbols
  -> MarketAnalystAgent / SignalGeneratorAgent
  -> InferenceCoordinator.predict_once(symbol="SOL")
  -> predict_meta_confidence
  -> V5FilterModelClassifier.predict_proba(symbol="SOL")
  -> inference_symbol_unsupported:SOL
```

The full symbol compatibility matrix showed that the runtime universe contains
22 symbols, artifact metadata advertises those 22 symbols, but the actual V5
model route supports only:

```text
BTC
ETH
BNB
```

Unsupported runtime symbols by actual model route:

```text
AEVO
AR
AVAX
DOGE
ENA
IOTA
NEAR
SOL
SOPH
TAO
TRB
TRUMP
TRX
WLD
XAUT
XLM
XPL
XRP
ZEC
```

R4 classification:

```text
failure_class              INFERENCE_SYMBOL_COVERAGE_GAP
remediation_boundary       MODEL_ARTIFACT_RUNTIME_CONTRACT
runtime_release_fix_needed true
operational_config_only    false
implicit_fallback_allowed  false
```

This is not a one-symbol SOL typo and not an observability gap. R3A remains
`PASS_SUPERVISED_EXIT_OBSERVABILITY`; stderr captured the concrete exception.

R4 added a preflight gate:

```text
RUNTIME_SYMBOL_UNIVERSE_COMPATIBILITY
```

The gate requires:

```text
runtime_symbols ⊆ actual_model_route_supported_symbols
unsupported_symbols = []
```

If unsupported symbols are present, preflight returns:

```text
BLOCKED_INFERENCE_SYMBOL_UNSUPPORTED
```

and no activation authorization may be minted.

R4 evidence:

```text
runtime_activation_p7_r4_symbol_compatibility.json
sha256 = b910b69f4cb15d4d5e81aed82324b14f7e7838bc997984f3e997afcf3e61d843

runtime_activation_p7_r4_failure_classification.json
sha256 = 90a90711f65bdf231162b0ae551edfb6e66949d4c7c73f7e81e49d969f05cf91
```

No attempt #4 is authorized. A future remediation must either align the runtime
universe with the actual model route under an explicit contract or provide
explicit model/artifact routes for every runtime symbol. It must not silently
fallback unsupported symbols to another model.

---

# Platform Gate — EXPERIMENTAL_SUBSTRATE_READY

```text
EXPERIMENTAL_SUBSTRATE_READY =
    EV_UNIT_CONTRACT_PASS
AND S3_RUNTIME_ENFORCEMENT_PASS
AND EXPLICIT_SYMBOL_ROUTING_PASS
AND ARTIFACT_IDENTITY_PASS
AND PURE_SCORING_PASS
AND SIDE_SEMANTICS_PASS
AND RISK_SIZING_PASS
AND COMMON_EVALUATOR_PASS
AND FULL_PARITY_PASS
AND ARTIFACT_SCHEMA_LINEAGE_PASS
AND WARMUP_CONTRACT_PASS
AND FULL_TEST_SUITE_PASS
```

Important:

```text
EXPERIMENTAL_SUBSTRATE_READY
≠
LIVE_READY
```

It only means the platform is safe enough to begin a new controlled research successor.

---

# Chapter B — Successor Research

No successor is automatically authorized by completion of Chapter A.

---

# R0 — Research Preflight

Before implementation, freeze:

```text
research question
population
candidate contrast axis
primary feasibility estimand
future quality estimand
minimum meaningful effect
alpha
power
inference unit
maximum calendar horizon
outcome firewall
```

Recommended first contrast to preflight:

```text
same market observation
same feature universe
same forecast horizon

Candidate A:
directional posterior

Candidate B:
economic-hurdle posterior
```

The candidate pair must differ in a meaningful research axis, not merely in labels or symbol membership.

### Exit Gate

```text
RESEARCH_PREFLIGHT_PASS
```

If preflight fails, stop before implementation.

---

# R1 — Candidate Pair Implementation

Target API:

```python
pair = evaluate_pair(
    observation=observation,
    candidate_a=candidate_a,
    candidate_b=candidate_b,
)
```

Output should include:

```text
canonical_observation_key

candidate_a_hash
candidate_b_hash
candidate_a_schema_hash
candidate_b_schema_hash

posterior_a
posterior_b

action_a
action_b

A_ONLY
B_ONLY
OPPOSITE_ACTION
SHARED_SAME_ACTION
NEITHER
```

Constraints:

```text
no outcome
no PnL
no execution
no mutable hidden routing
```

---

# R2 — Outcome-Blind Feasibility Replay

Historical replay is allowed only to answer:

```text
Can this experimental design produce enough independent contrast?
```

It must not answer:

```text
Which candidate historically made more money?
```

## Outcome Firewall

Replay reader must not expose:

```text
future return
PnL
MFE
MAE
win/loss
trade outcome
historical candidate quality summary
```

## Collect Only

```text
actionable/day
disagreement/day
A-only/day
B-only/day
opposite-action/day
zero-event-day rate
symbol concentration
regime concentration
daily clustering
autocorrelation
overdispersion
```

Use UTC day as the inference cluster.

Prefer whole-day stationary/block bootstrap for calendar feasibility rather than treating every 15-minute cycle as an independent sample.

### Exit

One of:

```text
STRUCTURALLY_FEASIBLE
VOLUME_FEASIBLE
STATISTICALLY_FEASIBLE
```

or:

```text
RESEARCH_HARD_STOP
```

The main H14 lesson is moved here:

> Hard-stop an infeasible experiment before prospective activation.

---

# R3 — A/A Shadow

Run the same frozen candidate under two identities.

Expected:

```text
posterior divergence = 0
decision divergence  = 0
pair completeness    = 100%
```

Any A/A disagreement is an infrastructure defect.

### Exit Gate

```text
A_A_SHADOW_PASS
```

---

# R4 — A/B Shadow

Run the actual candidate pair through the intended future runtime path.

Every row must be:

```text
mode                   = SHADOW
authoritative_evidence = false
trade_execution        = false
outcome_access         = false
```

Measure only:

```text
pair completeness
timestamp/provenance integrity
candidate hash correctness
runtime event rate
runtime-vs-replay rate consistency
latency/resource behavior
lineage violations
```

Do not inspect profitability or winner/loser quality.

### Exit Gate

```text
A_B_SHADOW_PASS
```

---

# R5 — Freeze Prospective Contract

Only after R0–R4 pass, freeze:

```text
research_id
candidate A exact definition
candidate B exact definition
artifact hashes
feature schema hashes
decision rules
thresholds
eligibility
population
forecast horizon
power contract
quarantine rules
future effective_at
```

Mandatory:

```text
effective_at > contract_commit_time
retroactive_application = false
```

Then:

```text
activation = ARMED
```

---

# R6 — Prospective Accumulation

At the frozen effective timestamp:

```text
ARMED
→ ACTIVE
→ ACCUMULATING
```

Operational checkpoints may inspect only:

```text
integrity
coverage
elapsed UTC days
actionable count
disagreement count
A-only count
B-only count
information sufficiency
```

They may not inspect:

```text
PnL
win rate
candidate winner
quality ranking
```

---

# R7 — Quality Unlock

Passing the prospective sufficiency gate must not automatically expose outcomes.

Required sequence:

```text
prospective sufficiency PASS
        ↓
QUALITY_ELIGIBLE
        ↓
separate explicit governance authorization
        ↓
unlock predefined outcome endpoint
```

Only the endpoint, hypothesis and statistical test frozen in R0/R5 may be evaluated.

---

# Recommended Implementation Batches

## Batch A — Decision Correctness

```text
P0 Baseline
P1 EV contract
P1 S3 enforcement
P2 Explicit symbol routing
P2 Artifact identity
```

### Batch A Exit

```text
DECISION_CORRECTNESS_PASS
```

---

## Batch B — Scoring / Risk Semantics

```text
P3 Pure scoring
P3 Side-aware modifiers
P4 Gating cleanup
P4 Position-sizing semantics
```

### Batch B Exit

```text
SCORING_RISK_SEMANTICS_PASS
```

---

## Batch C — Parity and Lineage

```text
P5 Common evaluator
P5 Full live/replay parity
P6 Artifact/schema correction
P6 Warm-up contract
P6 Full regression closure
```

### Batch C Exit

```text
EXPERIMENTAL_SUBSTRATE_READY
```

---

## Batch D — Successor Research Preflight

```text
R0 Research preflight
R1 Candidate pair implementation
R2 Outcome-blind feasibility replay
```

### Batch D Exit

Either:

```text
SUCCESSOR_FEASIBLE
```

or:

```text
RESEARCH_HARD_STOP
```

No prospective experiment is armed in this batch.

---

## Batch E — Shadow and Prospective Activation

Only if Batch D passes:

```text
R3 A/A shadow
R4 A/B shadow
R5 Freeze prospective contract
R6 Prospective accumulation
```

Quality evaluation remains separately gated under R7.

---

# Dependency Graph

```text
P0
 ↓
P1 ──────────────┐
 ↓               │
P2               │
 ↓               │
P3               │
 ↓               │
P4               │
 ↓               │
P5               │
 ↓               │
P6               │
 ↓               │
EXPERIMENTAL_SUBSTRATE_READY
 ↓
R0
 ↓
R1
 ↓
R2
 ├── FAIL → RESEARCH_HARD_STOP
 └── PASS
       ↓
      R3
       ↓
      R4
       ↓
      R5
       ↓
      R6
       ↓
   SUFFICIENCY
       ↓
      R7
```

---

# Non-Negotiable Governance Rules

```text
1. H14 remains CLOSED.
2. H14 raw evidence is never rewritten.
3. No H14-R1 / G9 / G5 v2 is created.
4. No successor is authorized implicitly.
5. No real-money live trading is enabled by this roadmap.
6. No outcome/PnL is used during successor preflight or feasibility work.
7. Candidate disagreement is a feasibility signal, not an optimization target.
8. One scientific contrast axis per experiment.
9. Runtime and historical replay must share the same pure evaluator.
10. Every substantive model/config change after activation requires a new contract/epoch.
```

---

# Final Readiness Hierarchy

```text
CURRENT
  ↓
PLATFORM_REMEDIATION
  ↓
EXPERIMENTAL_SUBSTRATE_READY
  ↓
SUCCESSOR_RESEARCH_PREFLIGHT
  ↓
BLIND_FEASIBILITY_PASS
  ↓
A/A_SHADOW_PASS
  ↓
A/B_SHADOW_PASS
  ↓
ARMED
  ↓
PROSPECTIVE_ACCUMULATION
  ↓
QUALITY_ELIGIBLE
  ↓
SEPARATE QUALITY AUTHORIZATION
  ↓
LIVE-READINESS REVIEW
```

`LIVE-READINESS REVIEW` is intentionally outside the scope of this roadmap. Passing research validation does not automatically authorize real-money execution.
