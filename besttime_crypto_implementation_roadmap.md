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
