# H13 — Validation Sample Density And Design Research

Status: `H13.6_MARKET_REPLAY_V2_AND_INDEPENDENT_QUALITY_GATES_EXECUTED`

## Lineage Lock

```text
H10 = CLOSED_IMMUTABLE

METHODOLOGY = PASS
POLICY_EVIDENCE = INSUFFICIENT

H10_OUTPUT =
NO_ROBUST_POLICY_CANDIDATE_ESTABLISHED

ROBUST_POLICY_CANDIDATE = NONE
FINAL_H10_WINNER = NOT_SELECTED
```

H10 is complete and must not be reopened. Do not add `H10.10`, reopen folds, lower sample thresholds, or select a best-available candidate.

H10 established this blocker:

```text
278 frozen policy candidates
x 9 expanding research folds
-> 9 research selections
-> 9 untouched validation folds
-> only 2 evaluable folds
-> insufficient cross-fold evidence
```

The active limitation is validation evidence density and stability, not another policy-threshold search.

## Current State

```text
H10 = CLOSED_IMMUTABLE

H11 =
BLOCKED_NO_ROBUST_INPUT_CANDIDATE

H12 =
BLOCKED_NO_VALIDATED_POLICY_CANDIDATE

NEXT =
H13_VALIDATION_SAMPLE_DENSITY_AND_DESIGN_RESEARCH

PRODUCTION_CHANGE = BLOCKED
```

Policy lane status:

```text
META_ONLY_SHORT_HORIZON_TUNING = CLOSED
SELL_META_065_V1 = REJECTED
BUY = INSUFFICIENT_EVIDENCE
NEW_THRESHOLD_SEARCH = BLOCKED
```

## Research Question

H13 does not ask:

```text
Which threshold should we try next?
```

H13 asks:

```text
Why did 7/9 frozen validation folds fail sample adequacy,
and what validation design can establish robustness
without weakening the frozen quality requirements?
```

H13.0 locks the diagnostic-only question more narrowly:

```text
Why were 7/9 H10 validation folds insufficient,
and which structural factor caused each shortfall?
```

## H13.0 Diagnostic Contract

Phase:

```text
H13.0_VALIDATION_SAMPLE_DENSITY_DIAGNOSTIC
```

Scope:

```text
diagnostic_only = true
policy_search = false
threshold_search = false
candidate_selection = false
```

The diagnostic must account for all seven insufficient H10 validation folds using:

```text
fold_id
selected_policy_candidate_id
selected_policy_family

validation_analysis_count
raw_directional_count
technical_pass_count
posterior_pass_count
meta/pass-policy-eligible count
actionable_count

minimum_required_sample
actual_sample
sample_shortfall

symbol_subset
regime_subset
side
```

Each insufficient fold must receive exactly one terminal root-cause bucket:

```text
ZERO_DIRECTIONAL_DENSITY
TECHNICAL_FILTER_TOO_SPARSE
POSTERIOR_FILTER_TOO_SPARSE
META_FILTER_TOO_SPARSE
SYMBOL_SUBSET_TOO_NARROW
REGIME_FILTER_TOO_NARROW
COMBINED_POLICY_SELECTIVITY
VALIDATION_WINDOW_TOO_SHORT
OTHER_EXPLICIT_CAUSE
```

`VALIDATION_WINDOW_TOO_SHORT` must not be inferred merely from
`actual_sample < minimum_required_sample`. Use it only when the diagnostic
shows the selected candidate produces reasonable relative density and the
one-month validation window is the structural limiter. If the selected policy
or filters are too selective, classify the cause under the relevant density or
selectivity bucket instead.

Critical invariant:

```text
INSUFFICIENT_VALIDATION_FOLDS = 7
INSUFFICIENT_FOLDS_ACCOUNTED_FOR = 7
ROOT_CAUSE_UNIQUENESS = PASS

THRESHOLD_SEARCH_STARTED = NO
POLICY_SEARCH_STARTED = NO
VALIDATION_DESIGN_MUTATED = NO
```

## H13.0 Execution Record

Artifacts:

```text
historical-h13-validation-density/
├── contracts/
│   └── h13_0_validation_sample_density_diagnostic_contract_v1.json
├── data/
│   ├── h13_0_insufficient_fold_diagnostic_input.jsonl
│   └── h13_0_fold_density_diagnostics.jsonl
└── reports/
    ├── h13_0_validation_sample_density_diagnostic.json
    ├── h13_0_validation_sample_density_diagnostic.md
    ├── h13_0_root_cause_distribution.json
    └── h13_0_family_density_diagnostic.json
```

Execution state:

```text
H13_0_EXECUTION_STARTED = YES
H13_0_CONTRACT_FROZEN = YES
H13_0_VALIDATION_SAMPLE_DENSITY_DIAGNOSTIC = PASS

AUTHORITATIVE_INPUT_SOURCE =
RELEASE_LOCAL_H10_FROZEN_ARTIFACTS

H13_0_INPUT_PROVENANCE = PASS

SOURCE_INSUFFICIENT_FOLDS = 7
INPUT_ROWS = 7
INSUFFICIENT_FOLDS_ACCOUNTED_FOR = 7

ROOT_CAUSE_UNIQUENESS = PASS
ROOT_CAUSE_ASSIGNED = 7

H13_0_PRIMARY_FINDING =
SAMPLE_INSUFFICIENCY_DOMINATED_BY_SYMBOL_SUBSET_TOO_NARROW

ROOT_CAUSE_DISTRIBUTION:
SYMBOL_SUBSET_TOO_NARROW = 6
REGIME_FILTER_TOO_NARROW = 1

H10_ARTIFACTS_MUTATED = NO
SOURCE_BYTES_MUTATED = NO
MARKET_REPLAY_V2_RERUN = NO

THRESHOLD_SEARCH_STARTED = NO
POLICY_SEARCH_STARTED = NO
VALIDATION_DESIGN_MUTATED = NO

PRODUCTION_CHANGE = BLOCKED
```

H13.1 opens from this result as symbol-subset density and generalization
research. It is not a longer-validation-window lane: `VALIDATION_WINDOW_TOO_SHORT`
was not assigned to any H13.0 fold.

## H13.1 Symbol-Subset Research Contract

Phase:

```text
H13.1_SYMBOL_SUBSET_DENSITY_AND_GENERALIZATION_RESEARCH
```

Frozen question:

```text
Do symbol-specific research selections preserve
quality and adequate evidence density when their
symbol-selection behavior is evaluated across time,
without weakening H10's sample or quality requirements?
```

Artifacts:

```text
historical-h13-validation-density/
├── contracts/
│   └── h13_1_symbol_subset_density_and_generalization_contract_v1.json
├── data/
│   └── h13_1_symbol_subset_density_source_folds.jsonl
└── reports/
    ├── h13_1_symbol_subset_density_and_generalization_opening_record.json
    └── h13_1_symbol_subset_density_and_generalization_opening_record.md
```

Opening state:

```text
H13_1_OPENED = YES
H13_1_EXECUTION_STARTED = YES
H13_1_SYMBOL_SUBSET_DENSITY_AND_GENERALIZATION_RESEARCH = PASS
H13_1_DIRECTION =
SYMBOL_SUBSET_DENSITY_AND_GENERALIZATION_RESEARCH

LONGER_VALIDATION_WINDOW_RESEARCH_OPENED = NO

SOURCE_F4_INSUFFICIENT_FOLDS = 6
SOURCE_F4_FOLDS_ACCOUNTED_FOR = 6
FROZEN_SYMBOL_SUBSETS_RECOVERED = 6
SYMBOL_DENSITY_FUNNEL_ACCOUNTING = PASS

SYMBOL_SUBSET_SELECTION_STABILITY = MIXED
SELECTIVITY_DENSITY_TRADEOFF = PRESENT
SELECTION_OBJECTIVE_DENSITY_BLIND_SPOT = NOT_PRESENT

H13_1_PRIMARY_FINDING =
MIXED_SYMBOL_SUBSET_DRIFT_AND_SELECTIVITY_DENSITY_TRADEOFF

REGIME_DENSITY_EVIDENCE = LIMITED

H10 = CLOSED_IMMUTABLE
MIN_VALIDATION_SAMPLE_MUTATED = NO
H10_VALIDATION_RESULTS_MUTATED = NO

NEW_THRESHOLD_SEARCH = 0
NEW_META_SEARCH = 0
NEW_POSTERIOR_SEARCH = 0
NEW_POLICY_SEARCH = 0
NEW_POLICY_CANDIDATE = NONE

PRODUCTION_CHANGE = BLOCKED
```

H13.1 diagnosed symbol subset selection stability, symbol-set transitions,
density funnels, comparable broader frozen-catalog parents, and H10.5 runner-up
selection objective evidence. Counterfactual comparisons are diagnostic-only and
not eligible for promotion.

## Validation-Design Research

After H13.1, the next lane must not default to longer validation windows. The
evidence points to mixed symbol-subset drift plus a selectivity-density
trade-off, while selection-objective density blindness is not supported. H13.2
therefore freezes a design-research contract for symbol stability and evidence
accumulation before any new policy search.

## H13.2 Design Research Contract

Phase:

```text
H13.2_SYMBOL_STABILITY_AND_EVIDENCE_ACCUMULATION_DESIGN_RESEARCH
```

Frozen question:

```text
Can symbol-specific policy evidence be evaluated
with a design that preserves temporal validity
despite mixed symbol-subset drift and low sample density,
without weakening H10 quality/sample requirements?
```

Artifacts:

```text
historical-h13-validation-density/
├── contracts/
│   └── h13_2_symbol_stability_and_evidence_accumulation_design_contract_v1.json
└── reports/
    ├── h13_2_symbol_stability_and_evidence_accumulation_design_opening_record.json
    └── h13_2_symbol_stability_and_evidence_accumulation_design_opening_record.md
```

Opening state:

```text
H13_2_SYMBOL_STABILITY_AND_EVIDENCE_ACCUMULATION_DESIGN_RESEARCH =
PASS_WITH_LIMITS

H13_2_EXECUTION_STARTED = YES
DESIGN_CELLS_EVALUATED = 9
H13_2_DESIGN_OUTPUT = MULTI_FACTOR_DESIGN_REQUIRED

SOURCE_H13_1_RESULT = PASS

SYMBOL_SUBSET_SELECTION_STABILITY = MIXED
SELECTIVITY_DENSITY_TRADEOFF = PRESENT
SELECTION_OBJECTIVE_DENSITY_BLIND_SPOT = NOT_PRESENT

DESIGN_DIMENSION_1 =
SYMBOL_MEMBERSHIP_UPDATE_SEMANTICS

DESIGN_DIMENSION_2 =
VALIDATION_EVIDENCE_ACCUMULATION_HORIZON

DESIGN_CELLS_FROZEN = 9

MIN_SAMPLE_REQUIREMENT_MUTATED = NO
QUALITY_GUARDS_MUTATED = NO

NEW_THRESHOLD_SEARCH = 0
NEW_POLICY_PARAMETER_SEARCH = 0
NEW_POLICY_CANDIDATE = NONE

H10_ARTIFACTS_MUTATED = NO
H13_1_ARTIFACTS_MUTATED = NO

LONGER_WINDOW_ONLY_LANE = NOT_JUSTIFIED
SELECTION_OBJECTIVE_REDESIGN = NOT_JUSTIFIED
POLICY_SEARCH = CLOSED
PRODUCTION_CHANGE = BLOCKED
```

H13.2 evaluated dynamic, fixed, and slow-update symbol-membership semantics
against monthly, two-month contiguous, and three-month contiguous evidence
horizons. Primary metrics were studyability and temporal coverage metrics, not
EV-driven design selection. The result is not a policy approval: it shows that
evidence accumulation and symbol-membership stability must be handled together.
Dynamic three-month accumulation can reach sample adequacy on available labeled
data, but one block mixes symbol-subset regimes; fixed/slow-update cells improve
stability by construction but require fresh labeled validation authority before
policy research can reopen.

## H13.3 Multi-Factor Design Contract Freeze

Phase:

```text
H13.3_MULTI_FACTOR_VALIDATION_DESIGN_CONTRACT_FREEZE
```

Frozen question:

```text
Which combination of symbol-membership persistence
evidence-accumulation horizon, and symbol-subset
regime-mixing tolerance provides sufficient validation
density and temporal validity without weakening H10's
quality/sample requirements?
```

Artifacts:

```text
historical-h13-validation-density/
├── contracts/
│   ├── h13_3_multi_factor_validation_design_contract_v1.json
│   └── h13_3_multi_factor_validation_design_contract_freeze_v1.json
├── data/
│   └── h13_3_design_cell_catalog.jsonl
└── reports/
    ├── h13_3_multi_factor_validation_design_contract_freeze.json
    └── h13_3_multi_factor_validation_design_contract_freeze.md
```

Contract state:

```text
H13_3_MULTI_FACTOR_VALIDATION_DESIGN_CONTRACT_FREEZE = PASS

SOURCE_H13_2_RESULT =
MULTI_FACTOR_DESIGN_REQUIRED

DESIGN_SPACE_FROZEN = PASS
SYMBOL_MEMBERSHIP_SEMANTICS_FROZEN = PASS
EVIDENCE_HORIZON_SEMANTICS_FROZEN = PASS
SUBSET_REGIME_MIXING_GUARD_FROZEN = PASS
SUBSET_REGIME_MIXING_SEMANTICS_FROZEN = PASS
DESIGN_SELECTION_RULES_FROZEN = PASS

FROZEN_DESIGN_CELLS = 5

QUALITY_METRICS_USED_FOR_DESIGN_SELECTION = NO
MARKET_REPLAY_V2_USED = NO

NEW_THRESHOLD_SEARCH = 0
NEW_POLICY_PARAMETER_SEARCH = 0
NEW_POLICY_CANDIDATE = NONE

POLICY_SEARCH = CLOSED
PRODUCTION_CHANGE = BLOCKED
```

H13.3 narrows the H13.2 grid to four candidate design cells plus one dynamic
three-month reference cell. H13.4 executed studyability under this frozen
contract; policy search remains closed.

## H13.4 Multi-Factor Design Execution

Phase:

```text
H13.4_MULTI_FACTOR_VALIDATION_DESIGN_EXECUTION
```

Artifacts:

```text
historical-h13-validation-density/
├── data/
│   ├── h13_4_design_block_studyability.jsonl
│   └── h13_4_design_cell_studyability.jsonl
└── reports/
    ├── h13_4_multi_factor_validation_design_execution.json
    └── h13_4_multi_factor_validation_design_execution.md
```

Execution state:

```text
H13_4_MULTI_FACTOR_VALIDATION_DESIGN_EXECUTION =
PASS_WITH_LIMITS

H13_4_DESIGN_OUTPUT =
MULTI_FACTOR_DESIGN_ADEQUATE

DESIGN_CELLS_EXPECTED = 5
DESIGN_CELLS_EVALUATED = 5

DESIGN_BLOCKS_EXPECTED = 12
DESIGN_BLOCKS_ACCOUNTED_FOR = 12

CELL_ID_DUPLICATES = 0
BLOCK_ID_DUPLICATES = 0
DESIGN_CONTRACT_HASH_MISMATCH = 0

MF1_EVIDENCE_MODE = LABELED_EXISTING
MF1_QUALITY_COMPARABILITY = FULL

MF2_TO_MF5_EVIDENCE_MODE = PRE_LABEL_PROXY
MF2_TO_MF5_QUALITY_COMPARABILITY = NOT_AVAILABLE

TOP_STUDYABILITY_TIER = MF2, MF4
TIE_RESOLUTION =
UNRESOLVED_BY_FROZEN_H13_3_HIERARCHY

QUALITY_METRICS_USED_FOR_DESIGN_SELECTION = NO
MARKET_REPLAY_V2_RERUN = NO

NEW_THRESHOLD_SEARCH = 0
NEW_POLICY_PARAMETER_SEARCH = 0
NEW_POLICY_CANDIDATE = NONE

POLICY_SEARCH = CLOSED
PRODUCTION_CHANGE = BLOCKED
```

H13.4 evaluated the five frozen cells using only studyability metrics. MF1
uses existing labels because dynamic three-month semantics match the frozen
H10/H13 evidence, but it remains a reference and has one high-mixing block.
MF2 through MF5 are pre-label proxy lanes because fixed/slow-update membership
semantics require a future frozen membership schedule and counterfactual replay
before quality evidence is comparable.

The frozen H13.3 hierarchy identifies MF2 and MF4 as the top studyability tier:
both have adequate proxy sample density, temporal validity, low subset-regime
mixing, three usable independent two-month blocks, zero churn, and the shorter
evidence horizon. H13.3 did not freeze a preference between slow-update and
fixed membership when those metrics tie, so H13.4 preserves the tie instead of
injecting a post-result quality or preference rule.

## H13.5 Tied Design Membership And Replay Input Freeze

Phase:

```text
H13.5_TIED_DESIGN_MEMBERSHIP_AND_REPLAY_INPUT_FREEZE
```

Artifacts:

```text
historical-h13-validation-density/
├── contracts/
│   └── h13_5_tied_design_membership_and_replay_input_contract_v1.json
├── data/
│   ├── h13_5_design_membership_schedules.jsonl
│   ├── h13_5_hypothetical_decisions.jsonl
│   └── h13_5_design_replay_input.jsonl
└── reports/
    ├── h13_5_tied_design_membership_and_replay_input_freeze.json
    └── h13_5_tied_design_membership_and_replay_input_freeze.md
```

Execution state:

```text
H13_5_TIED_DESIGN_MEMBERSHIP_AND_REPLAY_INPUT_FREEZE = PASS

SOURCE_H13_4 = PASS_WITH_LIMITS
SOURCE_TOP_TIER_DESIGNS = MF2, MF4

TOP_TIER_TIE_PRESERVED = YES
POST_HOC_TIE_BREAK = 0

MF2_MEMBERSHIP_SCHEDULE_FROZEN = PASS
MF4_MEMBERSHIP_SCHEDULE_FROZEN = PASS
MEMBERSHIP_SCHEDULE_FROZEN_BEFORE_REPLAY = PASS

HYPOTHETICAL_DECISIONS_FROZEN = PASS
REPLAY_INPUT_FROZEN = PASS

DESIGNS_FROZEN = 2
DESIGN_BLOCKS_FROZEN = 6
HYPOTHETICAL_DECISIONS_FROZEN_COUNT = 296
REPLAY_INPUT_ROWS = 296
UNIQUE_CANONICAL_EXECUTION_PATHS = 148

MF2_REPLAY_INPUT_HASH =
919dbb38c897c674ee105c67e43d5db19e09a183ff5b3107819555b1b2151da7

MF4_REPLAY_INPUT_HASH =
b4fae1f255b0002078b17257385d2ae8bb9bb10d4ba4b0991347d929e7c8ea5d

MARKET_REPLAY_V2_USED = NO
QUALITY_OUTCOME_ACCESSED = NO

NEW_THRESHOLD_SEARCH = 0
NEW_POLICY_PARAMETER_SEARCH = 0
NEW_POLICY_CANDIDATE = NONE

POLICY_SEARCH = CLOSED
PRODUCTION_CHANGE = BLOCKED
```

H13.5 preserves MF2 and MF4 as co-equal studyable designs. It freezes both
membership schedules and all hypothetical replay inputs from frozen H10
historical analysis records before any quality outcome access. The replay input
contains design-specific rows for both designs, but the canonical execution path
deduplicates to 148 unique paths because MF2 and MF4 share the same frozen
execution candidates under different design semantics.

H13.6 may consume these frozen inputs through Market Replay V2 and independent
quality gates. It still must not choose a design by highest EV; it may only
eliminate a design that fails an independent frozen quality requirement.

## H13.6 Market Replay V2 And Independent Quality Gates

Phase:

```text
H13.6_MARKET_REPLAY_V2_AND_INDEPENDENT_QUALITY_GATES
```

Artifacts:

```text
historical-h13-validation-density/
├── contracts/
│   └── h13_6_market_replay_and_quality_gate_contract_v1.json
├── data/
│   ├── h13_6_canonical_replay_input.jsonl
│   ├── h13_6_canonical_outcomes.jsonl
│   └── h13_6_design_labeled_memberships.jsonl
└── reports/
    ├── h13_6_market_replay_v2_and_quality_gates.json
    ├── h13_6_market_replay_v2_and_quality_gates.md
    ├── h13_6_mf2_quality.json
    ├── h13_6_mf4_quality.json
    └── h13_6_block_quality_stability.json
```

Execution state:

```text
H13_6_MARKET_REPLAY_V2_AND_INDEPENDENT_QUALITY_GATES =
PASS_WITH_LIMITS

H13_6_OUTPUT =
BOTH_DESIGNS_REMAIN_VIABLE

REPLAY_INPUT_ROWS = 296
UNIQUE_REPLAY_KEYS = 148
UNIQUE_REPLAY_KEYS_ACCOUNTED_FOR = 148
REPLAY_KEY_COLLISION = 0

DESIGN_MEMBERSHIPS = 296
DESIGN_MEMBERSHIPS_ACCOUNTED_FOR = 296
CANONICAL_OUTCOMES = 148

LABEL_COMPLETE = 148
INSUFFICIENT_FORWARD_HORIZON = 0
MARKET_DATA_MISSING = 0
MARKET_DATA_GAP = 0
INVALID_TEMPORAL_ALIGNMENT = 0
INVALID_REPLAY_INPUT = 0
TERMINAL_BUCKETS_ACCOUNTED_FOR = 148

MARKET_REPLAY_CONTRACT = V2
MARKET_REPLAY_CONTRACT_HASH =
02f6fa0252185b96d7676ce9f8713be807afd9426be2e6ad2766629b071d8c75
MARKET_REPLAY_CONTRACT_MUTATED = NO

PSEUDO_REPLICATION_GUARD = PASS
GLOBAL_INDEPENDENT_SAMPLE_BASE = CANONICAL_OUTCOMES

MF2_QUALITY_GATE = PASS_WITH_LIMITS
MF4_QUALITY_GATE = PASS_WITH_LIMITS
MF2_QUALITY_STABILITY = MIXED
MF4_QUALITY_STABILITY = MIXED

QUALITY_BASE =
INDEPENDENT_CANONICAL_OUTCOMES_AND_BLOCK_LEVEL_METRICS

QUALITY_RANKING_BETWEEN_MF2_MF4 = FORBIDDEN
POST_HOC_TIE_BREAK = 0

NEW_THRESHOLD_SEARCH = 0
NEW_POLICY_SEARCH = 0
NEW_POLICY_CANDIDATE = NONE

PRODUCTION_CHANGE = BLOCKED
```

H13.6 replayed 148 canonical execution paths once and joined the outcomes back
to 296 design memberships. MF2 and MF4 share the same canonical outcomes under
different validation-design memberships, so the global independent sample base
is 148 outcomes, not 296 memberships.

Both designs remain viable only with limits: pooled quality is positive, but
block-level quality is mixed. For both MF2 and MF4, blocks B01 and B02 fail
the frozen EV/PF quality gate, while B03 passes. H13.6 therefore preserves the
MF2/MF4 tie for H13.7 and does not choose a design by EV/PnL ranking.

## Holdout And Reuse Rules

H10 validation periods:

```text
Nov 2025 -> Jul 2026
```

These periods were already inspected during H10 validation. H13 may reuse them only as research data for methodology design.

Required flags:

```text
H10_VALIDATION_PERIOD_REUSED_FOR_RESEARCH = YES
FRESH_FINAL_HOLDOUT_REQUIRED = YES
```

Any stable candidate/design emerging from H13 requires a separate future or otherwise fresh final holdout lane before production claims.

## Horizon Rule

If sample density is the blocker, prefer acquiring more evidence over lowering the evidence bar:

```text
GET MORE EVIDENCE
NOT
LOWER THE EVIDENCE BAR
```

If market/model lineage allows, H13 may require an 18-24 month acquisition horizon. Do not modify H10-frozen acquisition scripts for that purpose:

```text
fetch_binance_3m_15m.py = FROZEN_FOR_H10_REPRODUCIBILITY
fetch_binance_3m_warmup.py = FROZEN_FOR_H10_REPRODUCIBILITY
```

If H13 requires longer acquisition, create a new versioned acquisition tool and freeze its SHA/content identity.

## Ordered Lane

```text
H13.0
validation sample density diagnostic = PASS
        |
H13.1
symbol-subset density/generalization research = PASS
        |
H13.2
single-factor stability/evidence accumulation = PASS_WITH_LIMITS
        |
H13.3
multi-factor validation design contract freeze = PASS
        |
H13.4
multi-factor validation design execution = PASS_WITH_LIMITS
        |
H13.5
freeze tied designs and exact membership schedules = PASS
        |
H13.6
Market Replay V2 plus independent quality gates = PASS_WITH_LIMITS
        |
H13.7
final validation-design acceptance
```

## Governance Invariants

- H10 remains immutable.
- No H11 work may proceed without a robust input candidate.
- No H12 work may proceed without a validated policy candidate.
- No new threshold search may proceed until H13 demonstrates an evidence-producing validation design.
- No sample threshold may be lowered retroactively to rescue H10.
- No best-available candidate may be promoted from H10.
- No H13 result may claim freshness if it was tuned against H10 validation periods.
